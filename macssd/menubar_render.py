"""Compact menu bar graphics: CPU bar, RAM bar and an internal-SSD ring.

Two layers, so the logic is testable without a screen:

* ``build_compact_model`` turns the existing collectors' output (SystemStats,
  StorageUsage) into plain numbers/strings plus a severity for each block.
* ``render_image`` draws that model into one NSImage for the status item.
  Colours come from dynamic system colours, so the same image looks right on
  light and dark menu bars. Everything is drawn from scratch (no copied art).

Layout, left to right (vertical bars fill from the bottom):

    USED 176.89 GB  (ring)  FREE 317.44 GB   RAM |#| 63%   CPU |#| 30%

Each metric has its own gradient colour (disk purple-pink, RAM green-teal,
CPU amber-orange). Only a *critical* reading turns red, and it blinks (the app
alternates ``blink_off``); warn-level readings keep their normal colour.
"""

from __future__ import annotations

from dataclasses import dataclass

from macssd.collectors.system import SystemStats
from macssd.storage import StorageUsage

INTERNAL_DRIVE = "Internal SSD"

# Usage thresholds for colouring. Orange/red only appear when something is
# worth noticing; normal readings stay in the neutral menu bar colour.
CPU_WARN, CPU_CRIT = 80.0, 95.0
RAM_WARN, RAM_CRIT = 80.0, 92.0
STORAGE_WARN, STORAGE_CRIT = 85.0, 95.0


def usage_severity(percent: float, warn: float, crit: float) -> str:
    if percent >= crit:
        return "critical"
    if percent >= warn:
        return "warn"
    return "ok"


@dataclass(frozen=True)
class BarMetric:
    label: str
    percent: float  # clamped to 0..100
    severity: str

    @property
    def text(self) -> str:
        return f"{self.percent:.0f}%"

    @property
    def fraction(self) -> float:
        return self.percent / 100.0


@dataclass(frozen=True)
class RingMetric:
    available: bool
    used_gb: float = 0.0
    free_gb: float = 0.0
    total_gb: float = 0.0
    severity: str = "neutral"

    @property
    def fraction(self) -> float:
        return min(max(self.used_gb / self.total_gb, 0.0), 1.0) if self.total_gb > 0 else 0.0

    @property
    def used_text(self) -> str:
        return f"{self.used_gb:.2f} GB" if self.available else "-- GB"

    @property
    def free_text(self) -> str:
        return f"{self.free_gb:.2f} GB" if self.available else "-- GB"


@dataclass(frozen=True)
class CompactModel:
    cpu: BarMetric
    ram: BarMetric
    ssd: RingMetric

    @property
    def has_critical(self) -> bool:
        return "critical" in (self.cpu.severity, self.ram.severity, self.ssd.severity)


def _clamp_percent(value: float) -> float:
    return min(max(float(value), 0.0), 100.0)


def build_compact_model(
    stats: SystemStats | None,
    storage: dict[str, StorageUsage] | None,
    drive_name: str = INTERNAL_DRIVE,
) -> CompactModel:
    cpu_pct = _clamp_percent(stats.cpu_percent) if stats else 0.0
    ram_pct = _clamp_percent(stats.ram_percent) if stats else 0.0

    usage = (storage or {}).get(drive_name)
    if usage is not None and usage.available and usage.total_gb > 0:
        free = max(usage.total_gb - usage.used_gb, 0.0)
        pct = usage.used_gb / usage.total_gb * 100.0
        ring = RingMetric(
            True, usage.used_gb, free, usage.total_gb,
            usage_severity(pct, STORAGE_WARN, STORAGE_CRIT),
        )
    else:
        ring = RingMetric(False)

    return CompactModel(
        cpu=BarMetric("CPU", cpu_pct, usage_severity(cpu_pct, CPU_WARN, CPU_CRIT)),
        ram=BarMetric("RAM", ram_pct, usage_severity(ram_pct, RAM_WARN, RAM_CRIT)),
        ssd=ring,
    )


# --- drawing -----------------------------------------------------------------

IMAGE_HEIGHT = 22.0
_RING_SIZE = 19.0
_RING_LINE = 3.4
_BAR_W = 8.0
_BAR_H = 20.0
TEXT_SIZE = 15.0  # shared with the temperature title text in menubar.py
_LABEL_SIZE = TEXT_SIZE
_VALUE_SIZE = TEXT_SIZE
_UNIT_SIZE = 12.0
_GAP = 7.0
_SMALL_GAP = 4.0

# (start, end) RGB per metric. Chosen to read on both light and dark menu bars.
GRADIENTS = {
    "disk": ((0.62, 0.42, 1.00), (1.00, 0.42, 0.72)),   # purple -> pink
    "ram": ((0.16, 0.85, 0.46), (0.10, 0.72, 0.85)),    # green -> teal
    "cpu": ((1.00, 0.80, 0.05), (1.00, 0.52, 0.08)),    # amber -> orange
}


def _rgb(c):
    from AppKit import NSColor

    return NSColor.colorWithSRGBRed_green_blue_alpha_(c[0], c[1], c[2], 1.0)


def _lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _fonts():
    from AppKit import NSFont, NSFontWeightBold, NSFontWeightMedium, NSFontWeightSemibold

    label = NSFont.systemFontOfSize_weight_(_LABEL_SIZE, NSFontWeightBold)
    value = NSFont.monospacedDigitSystemFontOfSize_weight_(_VALUE_SIZE, NSFontWeightSemibold)
    unit = NSFont.systemFontOfSize_weight_(_UNIT_SIZE, NSFontWeightMedium)
    return label, value, unit


def _attr(text: str, font, color):
    from AppKit import NSFontAttributeName, NSForegroundColorAttributeName
    from Foundation import NSAttributedString

    return NSAttributedString.alloc().initWithString_attributes_(
        text, {NSFontAttributeName: font, NSForegroundColorAttributeName: color}
    )


def _w(text: str, font) -> float:
    from AppKit import NSColor

    return _attr(text, font, NSColor.labelColor()).size().width


def _split_gb(text: str) -> tuple[str, str]:
    """'176.89 GB' -> ('176.89', 'GB')."""
    number, _, unit = text.partition(" ")
    return number, unit


def _y_for(attr) -> float:
    return (IMAGE_HEIGHT - attr.size().height) / 2


def layout(model: CompactModel) -> dict[str, float]:
    """x positions and total width, measured with the real fonts."""
    label, value, unit = _fonts()
    pos: dict[str, float] = {}
    x = 1.0

    def gb_width(text: str, with_unit: bool = True) -> float:
        n, u = _split_gb(text)
        return _w(n, value) + ((2.0 + _w(u, unit)) if with_unit else 0.0)

    pos["used_x"] = x
    x += _w("USED", label) + _SMALL_GAP
    pos["used_val_x"] = x
    x += gb_width(model.ssd.used_text, False) + _SMALL_GAP + 1
    pos["ring_x"] = x
    x += _RING_SIZE + _SMALL_GAP + 1
    pos["free_x"] = x
    x += _w("FREE", label) + _SMALL_GAP
    pos["free_val_x"] = x
    x += gb_width(model.ssd.free_text) + _GAP
    for key in ("ram", "cpu"):
        pos[f"{key}_x"] = x
        x += _w("RAM", label) + _SMALL_GAP
        pos[f"{key}_bar_x"] = x
        x += _BAR_W + _SMALL_GAP
        pos[f"{key}_val_x"] = x
        x += _w("99%", value) + _GAP
    pos["width"] = x - _GAP + 1
    return pos


def _metric_colors(key: str, severity: str, blink_off: bool):
    """(start, end) colours for a metric; red only when critical and 'on'."""
    from AppKit import NSColor

    if severity == "critical" and not blink_off:
        red = NSColor.systemRedColor()
        return red, red
    start, end = GRADIENTS[key]
    return _rgb(start), _rgb(end)


def _draw_text(x: float, text: str, font, color) -> None:
    a = _attr(text, font, color)
    a.drawAtPoint_((x, _y_for(a)))


def _draw_gb(x: float, text: str, color, with_unit: bool = True) -> None:
    _, value, unit = _fonts()
    number, u = _split_gb(text)
    _draw_text(x, number, value, color)
    if with_unit:
        _draw_text(x + _w(number, value) + 2.0, u, unit, color)


def _draw_ring(x: float, ssd: RingMetric, blink_off: bool) -> None:
    from AppKit import NSBezierPath, NSColor
    from Foundation import NSMakePoint

    centre = NSMakePoint(x + _RING_SIZE / 2, IMAGE_HEIGHT / 2)
    radius = (_RING_SIZE - _RING_LINE) / 2

    track = NSBezierPath.bezierPath()
    track.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(centre, radius, 0, 360)
    track.setLineWidth_(_RING_LINE)
    NSColor.labelColor().colorWithAlphaComponent_(0.22).setStroke()
    track.stroke()

    if not (ssd.available and ssd.fraction > 0):
        return
    sweep = 360.0 * ssd.fraction  # clockwise from 12 o'clock = share used
    start_c, end_c = GRADIENTS["disk"]
    critical = ssd.severity == "critical" and not blink_off
    steps = max(int(sweep / 6), 2)  # short arcs, each its own gradient colour
    for i in range(steps):
        a0 = 90.0 - sweep * i / steps
        a1 = 90.0 - sweep * (i + 1) / steps
        seg = NSBezierPath.bezierPath()
        seg.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
            centre, radius, a0 + (0.0 if i == 0 else 0.6), a1, True
        )
        seg.setLineWidth_(_RING_LINE)
        seg.setLineCapStyle_(1 if i in (0, steps - 1) else 0)
        (NSColor.systemRedColor() if critical else _rgb(_lerp(start_c, end_c, i / (steps - 1)))).setStroke()
        seg.stroke()


def _draw_bar_block(x: float, bar_x: float, val_x: float, key: str, metric: BarMetric, blink_off: bool) -> None:
    from AppKit import NSBezierPath, NSColor, NSGradient
    from Foundation import NSMakeRect

    label, value, _ = _fonts()
    c0, c1 = _metric_colors(key, metric.severity, blink_off)
    _draw_text(x, metric.label, label, c0)

    bar_y = (IMAGE_HEIGHT - _BAR_H) / 2
    NSColor.labelColor().colorWithAlphaComponent_(0.22).setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(bar_x, bar_y, _BAR_W, _BAR_H), 3.0, 3.0
    ).fill()
    fill_h = _BAR_H * metric.fraction
    if fill_h > 0:
        fill_h = max(fill_h, _BAR_W)  # keep the capsule shape for tiny values
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(bar_x, bar_y, _BAR_W, fill_h), 3.0, 3.0
        )
        NSGradient.alloc().initWithStartingColor_endingColor_(c0, c1).drawInBezierPath_angle_(path, 90.0)

    text_color = c0 if metric.severity == "critical" and not blink_off else NSColor.labelColor()
    _draw_text(val_x, metric.text, value, text_color)


def render_image(model: CompactModel, blink_off: bool = False):
    """Draw the model into a non-template NSImage (dynamic colours).

    ``blink_off`` is the "off" half of the critical blink: critical metrics
    briefly fall back to their normal gradient instead of red.
    """
    from AppKit import NSImage
    from Foundation import NSMakeSize

    pos = layout(model)
    label, _, _ = _fonts()

    def handler(_rect) -> bool:
        try:
            c_disk0, _c = _metric_colors("disk", model.ssd.severity, blink_off)
            _draw_text(pos["used_x"], "USED", label, c_disk0)
            _draw_gb(pos["used_val_x"], model.ssd.used_text, _label_color(), with_unit=False)
            _draw_ring(pos["ring_x"], model.ssd, blink_off)
            _draw_text(pos["free_x"], "FREE", label, c_disk0)
            _draw_gb(pos["free_val_x"], model.ssd.free_text, _label_color())
            _draw_bar_block(pos["ram_x"], pos["ram_bar_x"], pos["ram_val_x"], "ram", model.ram, blink_off)
            _draw_bar_block(pos["cpu_x"], pos["cpu_bar_x"], pos["cpu_val_x"], "cpu", model.cpu, blink_off)
        except Exception:  # noqa: BLE001 - never let a draw failure crash the menu bar
            return False
        return True

    image = NSImage.imageWithSize_flipped_drawingHandler_(
        NSMakeSize(pos["width"], IMAGE_HEIGHT), False, handler
    )
    image.setTemplate_(False)
    return image


def _label_color():
    from AppKit import NSColor

    return NSColor.labelColor()


def render_bitmap(model: CompactModel, scale: int = 2, blink_off: bool = False):
    """Rasterise the status image to an NSBitmapImageRep (for tests/screenshots)."""
    from AppKit import NSBitmapImageRep, NSGraphicsContext
    from Foundation import NSMakeRect

    image = render_image(model, blink_off)
    size = image.size()
    px_w, px_h = int(size.width * scale), int(size.height * scale)
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, px_w, px_h, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
    )
    rep.setSize_(size)
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)
    image.drawInRect_(NSMakeRect(0, 0, size.width, size.height))
    NSGraphicsContext.restoreGraphicsState()
    return rep

"""Compact menu bar graphics: CPU bar, RAM bar and an internal-SSD ring.

Two layers, so the logic is testable without a screen:

* ``build_compact_model`` turns the existing collectors' output (SystemStats,
  StorageUsage) into plain numbers/strings plus a severity for each block.
* ``render_image`` draws that model into one NSImage for the status item.
  Colours come from dynamic system colours, so the same image looks right on
  light and dark menu bars. Everything is drawn from scratch (no copied art).

Layout, left to right. Every item is ONE rounded pill in its own muted
colour, with soft grey-white text (vertical bars fill from the bottom):

    [USED 176.89 (ring) FREE 317.44 GB] [RAM |#| 63%] [CPU |#| 55%] [INT 42°] [EXT 31°]
        storage purple                    RAM green      CPU mustard    INT blue  EXT pink

Only a *critical* reading turns its pill red, and it blinks (the app
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
class TempItem:
    label: str      # "INT", "EXT", "CPU", "Mac"
    value: str      # "42°"
    severity: str   # "neutral" | "warn" | "critical"


@dataclass(frozen=True)
class CompactModel:
    cpu: BarMetric
    ram: BarMetric
    ssd: RingMetric
    temps: tuple = ()  # tuple[TempItem, ...], drawn on the same baseline as the rest

    @property
    def has_critical(self) -> bool:
        return "critical" in (self.cpu.severity, self.ram.severity, self.ssd.severity)


def _clamp_percent(value: float) -> float:
    return min(max(float(value), 0.0), 100.0)


def build_compact_model(
    stats: SystemStats | None,
    storage: dict[str, StorageUsage] | None,
    drive_name: str = INTERNAL_DRIVE,
    temps: tuple = (),
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
        temps=tuple(temps),
    )


# --- drawing -----------------------------------------------------------------

IMAGE_HEIGHT = 22.0
TEXT_SIZE = 13.0
_UNIT_SIZE = 10.5
_PILL_H = 20.0
_PILL_PAD = 7.0
_PILL_RADIUS = 7.0
_PILL_GAP = 5.0
_RING_SIZE = 15.0
_RING_LINE = 3.0
_BAR_W = 7.0
_BAR_H = 14.0
_GAP = 5.0

# (start, end) per item: washed-out mid-tones so soft grey-white text stays
# readable and the pills are still easy to tell apart.
GRADIENTS = {
    "disk": ((0.49, 0.41, 0.71), (0.58, 0.48, 0.78)),   # purple
    "ram": ((0.33, 0.57, 0.42), (0.41, 0.64, 0.50)),    # green
    "cpu": ((0.74, 0.61, 0.26), (0.79, 0.57, 0.28)),    # mustard yellow
    "int": ((0.36, 0.50, 0.74), (0.44, 0.58, 0.80)),    # blue
    "ext": ((0.72, 0.42, 0.57), (0.79, 0.50, 0.65)),    # pink
    "gray": ((0.45, 0.45, 0.50), (0.55, 0.55, 0.61)),   # anything else (Mac thermal ...)
}
_TEMP_KEYS = {"INT": "int", "EXT": "ext", "CPU": "cpu"}


def _rgb(c, alpha: float = 1.0):
    from AppKit import NSColor

    return NSColor.colorWithSRGBRed_green_blue_alpha_(c[0], c[1], c[2], alpha)


def _text_color(alpha: float = 1.0):
    """Soft grey-white: readable on every pill without being a harsh pure white."""
    return _rgb((0.90, 0.90, 0.92), alpha)


def _fonts():
    from AppKit import NSFont, NSFontWeightMedium, NSFontWeightSemibold

    label = NSFont.systemFontOfSize_weight_(TEXT_SIZE, NSFontWeightSemibold)
    value = NSFont.monospacedDigitSystemFontOfSize_weight_(TEXT_SIZE, NSFontWeightSemibold)
    unit = NSFont.systemFontOfSize_weight_(_UNIT_SIZE, NSFontWeightMedium)
    return label, value, unit


def _attr(text: str, font, color):
    from AppKit import NSFontAttributeName, NSForegroundColorAttributeName
    from Foundation import NSAttributedString

    return NSAttributedString.alloc().initWithString_attributes_(
        text, {NSFontAttributeName: font, NSForegroundColorAttributeName: color}
    )


def _w(text: str, font) -> float:
    return _attr(text, font, _text_color()).size().width


def _split_gb(text: str) -> tuple[str, str]:
    number, _, unit = text.partition(" ")
    return number, unit


def _y_for(attr) -> float:
    return (IMAGE_HEIGHT - attr.size().height) / 2


def layout(model: CompactModel) -> dict:
    """x positions of every pill and its contents, measured with the real fonts."""
    label, value, unit = _fonts()
    pos: dict = {"pills": []}

    def gb_width(text: str, with_unit: bool) -> float:
        n, u = _split_gb(text)
        return _w(n, value) + ((2.0 + _w(u, unit)) if with_unit else 0.0)

    # --- storage pill: USED n (ring) FREE n GB
    x0 = 1.0
    x = x0 + _PILL_PAD
    pos["used_x"] = x
    x += _w("USED", label) + _GAP
    pos["used_val_x"] = x
    x += gb_width(model.ssd.used_text, False) + _GAP + 1
    pos["ring_x"] = x
    x += _RING_SIZE + _GAP + 1
    pos["free_x"] = x
    x += _w("FREE", label) + _GAP
    pos["free_val_x"] = x
    x += gb_width(model.ssd.free_text, True) + _PILL_PAD
    pos["pills"].append(("disk", x0, x - x0, model.ssd.severity))
    x += _PILL_GAP

    # --- RAM and CPU pills: LABEL [bar] 100%
    for key, metric in (("ram", model.ram), ("cpu", model.cpu)):
        x0 = x
        x += _PILL_PAD
        pos[f"{key}_x"] = x0 + _PILL_PAD
        x += _w(metric.label, label) + _GAP
        pos[f"{key}_bar_x"] = x
        x += _BAR_W + _GAP
        pos[f"{key}_val_x"] = x
        x += _w("100%", value) + _PILL_PAD
        pos["pills"].append((key, x0, x - x0, metric.severity))
        x += _PILL_GAP

    # --- one pill per temperature: LABEL value
    pos["temps"] = []
    for item in model.temps:
        x0 = x
        x += _PILL_PAD
        label_x = x
        x += _w(item.label, label) + _GAP
        value_x = x
        x += _w(item.value, value) + _PILL_PAD
        key = _TEMP_KEYS.get(item.label, "gray")
        pos["pills"].append((key, x0, x - x0, item.severity))
        pos["temps"].append((item, label_x, value_x))
        x += _PILL_GAP

    pos["width"] = x - _PILL_GAP + 1
    return pos


def _pill_colors(key: str, severity: str, blink_off: bool):
    from AppKit import NSColor

    if severity == "critical" and not blink_off:
        red = NSColor.systemRedColor()
        return red, red
    start, end = GRADIENTS[key]
    return _rgb(start), _rgb(end)


def _draw_pill(key: str, x: float, width: float, severity: str, blink_off: bool) -> None:
    from AppKit import NSBezierPath, NSGradient
    from Foundation import NSMakeRect

    c0, c1 = _pill_colors(key, severity, blink_off)
    rect = NSMakeRect(x, (IMAGE_HEIGHT - _PILL_H) / 2, width, _PILL_H)
    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, _PILL_RADIUS, _PILL_RADIUS)
    NSGradient.alloc().initWithStartingColor_endingColor_(c0, c1).drawInBezierPath_angle_(path, 0.0)


def _draw_text(x: float, text: str, font, color) -> None:
    a = _attr(text, font, color)
    a.drawAtPoint_((x, _y_for(a)))


def _draw_gb(x: float, text: str, with_unit: bool) -> None:
    _, value, unit = _fonts()
    number, u = _split_gb(text)
    _draw_text(x, number, value, _text_color())
    if with_unit:
        _draw_text(x + _w(number, value) + 2.0, u, unit, _text_color(0.85))


def _draw_ring(x: float, ssd: RingMetric) -> None:
    from AppKit import NSBezierPath
    from Foundation import NSMakePoint

    centre = NSMakePoint(x + _RING_SIZE / 2, IMAGE_HEIGHT / 2)
    radius = (_RING_SIZE - _RING_LINE) / 2

    track = NSBezierPath.bezierPath()
    track.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(centre, radius, 0, 360)
    track.setLineWidth_(_RING_LINE)
    _rgb((1, 1, 1), 0.25).setStroke()
    track.stroke()

    if ssd.available and ssd.fraction > 0:
        arc = NSBezierPath.bezierPath()
        start = 90.0
        end = start - 360.0 * ssd.fraction  # clockwise from 12 o'clock = share used
        arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
            centre, radius, start, end, True
        )
        arc.setLineWidth_(_RING_LINE)
        arc.setLineCapStyle_(1)  # round
        _text_color().setStroke()
        arc.stroke()


def _draw_bar_block(x: float, bar_x: float, val_x: float, metric: BarMetric) -> None:
    from AppKit import NSBezierPath
    from Foundation import NSMakeRect

    label, value, _ = _fonts()
    _draw_text(x, metric.label, label, _text_color())

    bar_y = (IMAGE_HEIGHT - _BAR_H) / 2
    _rgb((1, 1, 1), 0.25).setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(bar_x, bar_y, _BAR_W, _BAR_H), 3.0, 3.0
    ).fill()
    fill_h = _BAR_H * metric.fraction
    if fill_h > 0:
        fill_h = max(fill_h, _BAR_W)  # keep the capsule shape for tiny values
        _text_color().setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(bar_x, bar_y, _BAR_W, fill_h), 3.0, 3.0
        ).fill()
    _draw_text(val_x, metric.text, value, _text_color())


def _draw_temp(item: TempItem, label_x: float, value_x: float) -> None:
    label, value, _ = _fonts()
    _draw_text(label_x, item.label, label, _text_color(0.85))
    _draw_text(value_x, item.value, value, _text_color())


def render_image(model: CompactModel, blink_off: bool = False):
    """Draw the model into a non-template NSImage.

    ``blink_off`` is the "off" half of the critical blink: critical pills
    briefly fall back to their normal colour instead of red.
    """
    from AppKit import NSImage
    from Foundation import NSMakeSize

    pos = layout(model)
    label, _, _ = _fonts()

    def handler(_rect) -> bool:
        try:
            for key, x0, width, severity in pos["pills"]:
                _draw_pill(key, x0, width, severity, blink_off)
            _draw_text(pos["used_x"], "USED", label, _text_color(0.85))
            _draw_gb(pos["used_val_x"], model.ssd.used_text, with_unit=False)
            _draw_ring(pos["ring_x"], model.ssd)
            _draw_text(pos["free_x"], "FREE", label, _text_color(0.85))
            _draw_gb(pos["free_val_x"], model.ssd.free_text, with_unit=True)
            _draw_bar_block(pos["ram_x"], pos["ram_bar_x"], pos["ram_val_x"], model.ram)
            _draw_bar_block(pos["cpu_x"], pos["cpu_bar_x"], pos["cpu_val_x"], model.cpu)
            for item, label_x, value_x in pos["temps"]:
                _draw_temp(item, label_x, value_x)
        except Exception:  # noqa: BLE001 - never let a draw failure crash the menu bar
            return False
        return True

    image = NSImage.imageWithSize_flipped_drawingHandler_(
        NSMakeSize(pos["width"], IMAGE_HEIGHT), False, handler
    )
    image.setTemplate_(False)
    return image


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

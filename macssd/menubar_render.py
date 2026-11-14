"""Compact menu bar graphics: CPU bar, RAM bar and an internal-SSD ring.

Two layers, so the logic is testable without a screen:

* ``build_compact_model`` turns the existing collectors' output (SystemStats,
  StorageUsage) into plain numbers/strings plus a severity for each block.
* ``render_image`` draws that model into one NSImage for the status item.
  Colours come from dynamic system colours, so the same image looks right on
  light and dark menu bars. Everything is drawn from scratch (no copied art).

Layout, left to right. Every item is ONE black rounded pill; the text, bar
and ring use that item's own washed-out colour (vertical bars fill from the bottom):

    [USED 176.89 (ring) FREE 317.44 GB] [RAM |#| 63%] [CPU |#| 55%] [INT 42°] [EXT 31°]
        lavender                          sage green     mustard        soft blue soft pink

Only a *critical* reading turns its pill red (soft white text), and it blinks (the app
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

# Washed-out ink colour per item, used for the text, bar and ring on a black
# pill. Pastel enough to be soft, different enough to tell items apart.
INK = {
    "disk": (0.72, 0.64, 0.92),   # lavender   - storage
    "ram": (0.58, 0.80, 0.65),    # sage green - RAM
    "cpu": (0.90, 0.77, 0.42),    # mustard    - CPU
    "int": (0.57, 0.72, 0.94),    # soft blue  - internal SSD temp
    "ext": (0.92, 0.64, 0.78),    # soft pink  - external SSD temp
    "gray": (0.70, 0.70, 0.74),   # anything else (Mac thermal ...)
}
_PILL_BLACK = (0.05, 0.05, 0.06)
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


def _ink(key: str, severity: str, blink_off: bool):
    """Text/bar/ring colour: the item's washed colour, or soft white on the
    red pill while a critical reading is 'on'."""
    if severity == "critical" and not blink_off:
        return _text_color()
    return _rgb(INK[key])


def _draw_pill(key: str, x: float, width: float, severity: str, blink_off: bool) -> None:
    from AppKit import NSBezierPath, NSColor
    from Foundation import NSMakeRect

    critical_on = severity == "critical" and not blink_off
    fill = NSColor.systemRedColor() if critical_on else _rgb(_PILL_BLACK)
    rect = NSMakeRect(x, (IMAGE_HEIGHT - _PILL_H) / 2, width, _PILL_H)
    fill.setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, _PILL_RADIUS, _PILL_RADIUS).fill()


def _draw_text(x: float, text: str, font, color) -> None:
    a = _attr(text, font, color)
    a.drawAtPoint_((x, _y_for(a)))


def _draw_gb(x: float, text: str, with_unit: bool, ink) -> None:
    _, value, unit = _fonts()
    number, u = _split_gb(text)
    _draw_text(x, number, value, ink)
    if with_unit:
        _draw_text(x + _w(number, value) + 2.0, u, unit, ink.colorWithAlphaComponent_(0.8))


def _draw_ring(x: float, ssd: RingMetric, ink) -> None:
    from AppKit import NSBezierPath
    from Foundation import NSMakePoint

    centre = NSMakePoint(x + _RING_SIZE / 2, IMAGE_HEIGHT / 2)
    radius = (_RING_SIZE - _RING_LINE) / 2

    track = NSBezierPath.bezierPath()
    track.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(centre, radius, 0, 360)
    track.setLineWidth_(_RING_LINE)
    ink.colorWithAlphaComponent_(0.28).setStroke()
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
        ink.setStroke()
        arc.stroke()


def _draw_bar_block(x: float, bar_x: float, val_x: float, metric: BarMetric, ink) -> None:
    from AppKit import NSBezierPath
    from Foundation import NSMakeRect

    label, value, _ = _fonts()
    _draw_text(x, metric.label, label, ink)

    bar_y = (IMAGE_HEIGHT - _BAR_H) / 2
    ink.colorWithAlphaComponent_(0.28).setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(bar_x, bar_y, _BAR_W, _BAR_H), 3.0, 3.0
    ).fill()
    fill_h = _BAR_H * metric.fraction
    if fill_h > 0:
        fill_h = max(fill_h, _BAR_W)  # keep the capsule shape for tiny values
        ink.setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(bar_x, bar_y, _BAR_W, fill_h), 3.0, 3.0
        ).fill()
    _draw_text(val_x, metric.text, value, ink)


def _draw_temp(item: TempItem, label_x: float, value_x: float, ink) -> None:
    label, value, _ = _fonts()
    _draw_text(label_x, item.label, label, ink.colorWithAlphaComponent_(0.8))
    _draw_text(value_x, item.value, value, ink)


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
            disk = _ink("disk", model.ssd.severity, blink_off)
            _draw_text(pos["used_x"], "USED", label, disk.colorWithAlphaComponent_(0.8))
            _draw_gb(pos["used_val_x"], model.ssd.used_text, False, disk)
            _draw_ring(pos["ring_x"], model.ssd, disk)
            _draw_text(pos["free_x"], "FREE", label, disk.colorWithAlphaComponent_(0.8))
            _draw_gb(pos["free_val_x"], model.ssd.free_text, True, disk)
            for key, metric in (("ram", model.ram), ("cpu", model.cpu)):
                _draw_bar_block(
                    pos[f"{key}_x"], pos[f"{key}_bar_x"], pos[f"{key}_val_x"], metric,
                    _ink(key, metric.severity, blink_off),
                )
            for (item, label_x, value_x), (pkey, _x0, _w0, psev) in zip(pos["temps"], pos["pills"][-len(pos["temps"]):] if pos["temps"] else []):
                _draw_temp(item, label_x, value_x, _ink(pkey, psev, blink_off))
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

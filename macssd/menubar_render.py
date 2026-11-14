"""Compact menu bar graphics: CPU bar, RAM bar and an internal-SSD ring.

Two layers, so the logic is testable without a screen:

* ``build_compact_model`` turns the existing collectors' output (SystemStats,
  StorageUsage) into plain numbers/strings plus a severity for each block.
* ``render_image`` draws that model into one NSImage for the status item.
  Colours come from dynamic system colours, so the same image looks right on
  light and dark menu bars. Everything is drawn from scratch (no copied art).

Layout, left to right (vertical bars fill from the bottom):

    USED 176.89 GB  (ring)  FREE 317.44 GB   R|#| 63%   C|#| 30%
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

IMAGE_HEIGHT = 18.0
_RING_SIZE = 14.0
_RING_LINE = 2.6
_BAR_W = 6.0
_BAR_H = 16.0
_CAPTION_SIZE = 6.0
_VALUE_SIZE = 9.5
_GAP = 8.0
_SMALL_GAP = 3.0


def _fonts():
    from AppKit import NSFont, NSFontWeightBold, NSFontWeightMedium

    caption = NSFont.systemFontOfSize_weight_(_CAPTION_SIZE, NSFontWeightBold)
    value = NSFont.monospacedDigitSystemFontOfSize_weight_(_VALUE_SIZE, NSFontWeightMedium)
    return caption, value


def _fill_color(severity: str):
    from AppKit import NSColor

    if severity == "critical":
        return NSColor.systemRedColor()
    if severity == "warn":
        return NSColor.systemOrangeColor()
    return NSColor.labelColor()


def _attr(text: str, font, color):
    from AppKit import NSFontAttributeName, NSForegroundColorAttributeName
    from Foundation import NSAttributedString

    return NSAttributedString.alloc().initWithString_attributes_(
        text, {NSFontAttributeName: font, NSForegroundColorAttributeName: color}
    )


def _text_w(text: str, font) -> float:
    from AppKit import NSColor

    return _attr(text, font, NSColor.labelColor()).size().width


def layout(model: CompactModel) -> dict[str, float]:
    """x positions and total width, measured with the real fonts."""
    caption, value = _fonts()
    pos: dict[str, float] = {}
    x = 1.0
    pos["used_x"] = x
    x += max(_text_w(model.ssd.used_text, value), _text_w("USED", caption)) + _SMALL_GAP + 1
    pos["ring_x"] = x
    x += _RING_SIZE + _SMALL_GAP + 1
    pos["free_x"] = x
    x += max(_text_w(model.ssd.free_text, value), _text_w("FREE", caption)) + _GAP
    for key, metric in (("ram", model.ram), ("cpu", model.cpu)):
        pos[f"{key}_x"] = x
        x += _text_w("W", caption) + _SMALL_GAP          # stacked letters
        x += _BAR_W + _SMALL_GAP                          # vertical bar
        x += _text_w("100%", value) + _GAP                # percentage (widest case)
    pos["width"] = x - _GAP + 1
    return pos


def _draw_caption_value(x: float, caption: str, text: str) -> None:
    from AppKit import NSColor

    cap_font, val_font = _fonts()
    _attr(caption, cap_font, NSColor.secondaryLabelColor()).drawAtPoint_((x, IMAGE_HEIGHT - 6.5))
    _attr(text, val_font, NSColor.labelColor()).drawAtPoint_((x, 0.5))


def _draw_vertical_block(x: float, metric: BarMetric) -> None:
    from AppKit import NSBezierPath, NSColor
    from Foundation import NSMakeRect

    cap_font, val_font = _fonts()
    letters = metric.label
    line_h = 5.2
    top = IMAGE_HEIGHT / 2 + line_h * len(letters) / 2
    for i, ch in enumerate(letters):  # stacked label: R / A / M
        _attr(ch, cap_font, NSColor.secondaryLabelColor()).drawAtPoint_((x, top - line_h * (i + 1) - 0.5))

    bar_x = x + _text_w("W", cap_font) + _SMALL_GAP
    bar_y = (IMAGE_HEIGHT - _BAR_H) / 2
    NSColor.labelColor().colorWithAlphaComponent_(0.22).setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(bar_x, bar_y, _BAR_W, _BAR_H), 2.0, 2.0
    ).fill()
    fill_h = _BAR_H * metric.fraction
    if fill_h > 0:
        fill_h = max(fill_h, _BAR_W)  # keep the capsule shape for tiny values
        _fill_color(metric.severity).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(bar_x, bar_y, _BAR_W, fill_h), 2.0, 2.0
        ).fill()

    text = _attr(metric.text, val_font, _fill_color(metric.severity))
    text.drawAtPoint_((bar_x + _BAR_W + _SMALL_GAP, (IMAGE_HEIGHT - text.size().height) / 2))


def _draw_ring(x: float, ssd: RingMetric) -> None:
    from AppKit import NSBezierPath, NSColor
    from Foundation import NSMakePoint

    centre = NSMakePoint(x + _RING_SIZE / 2, IMAGE_HEIGHT / 2)
    radius = (_RING_SIZE - _RING_LINE) / 2

    track = NSBezierPath.bezierPath()
    track.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(centre, radius, 0, 360)
    track.setLineWidth_(_RING_LINE)
    NSColor.labelColor().colorWithAlphaComponent_(0.22).setStroke()
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
        _fill_color(ssd.severity).setStroke()
        arc.stroke()


def render_image(model: CompactModel):
    """Draw the model into a non-template NSImage (dynamic colours)."""
    from AppKit import NSImage
    from Foundation import NSMakeSize

    pos = layout(model)

    def handler(_rect) -> bool:
        try:
            _draw_caption_value(pos["used_x"], "USED", model.ssd.used_text)
            _draw_ring(pos["ring_x"], model.ssd)
            _draw_caption_value(pos["free_x"], "FREE", model.ssd.free_text)
            _draw_vertical_block(pos["ram_x"], model.ram)
            _draw_vertical_block(pos["cpu_x"], model.cpu)
        except Exception:  # noqa: BLE001 - never let a draw failure crash the menu bar
            return False
        return True

    image = NSImage.imageWithSize_flipped_drawingHandler_(
        NSMakeSize(pos["width"], IMAGE_HEIGHT), False, handler
    )
    image.setTemplate_(False)
    return image


def render_bitmap(model: CompactModel, scale: int = 2):
    """Rasterise the status image to an NSBitmapImageRep (for tests/screenshots)."""
    from AppKit import NSBitmapImageRep, NSGraphicsContext
    from Foundation import NSMakeRect

    image = render_image(model)
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

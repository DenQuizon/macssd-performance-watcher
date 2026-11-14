"""Compact menu bar graphics: CPU bar, RAM bar and an internal-SSD ring.

Two layers, so the logic is testable without a screen:

* ``build_compact_model`` turns the existing collectors' output (SystemStats,
  StorageUsage) into plain numbers/strings plus a severity for each block.
* ``render_image`` draws that model into one NSImage for the status item.
  Colours come from dynamic system colours, so the same image looks right on
  light and dark menu bars. Everything is drawn from scratch (no copied art).

Layout (each block is two rows, 22pt menu bar height):

    CPU  27%   RAM  81%   (ring)  221 GB used
    [=====---] [=======-]         24 GB free
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
        return f"{self.used_gb:.0f} GB used" if self.available else "-- GB used"

    @property
    def free_text(self) -> str:
        return f"{self.free_gb:.0f} GB free" if self.available else "-- GB free"


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
_BLOCK_GAP = 9.0
_BAR_WIDTH = 44.0
_BAR_HEIGHT = 4.0
_RING_SIZE = 14.0
_RING_LINE = 2.6
_LABEL_SIZE = 7.5
_VALUE_SIZE = 9.0


def _fonts():
    from AppKit import NSFont, NSFontWeightBold, NSFontWeightMedium, NSFontWeightRegular

    label = NSFont.systemFontOfSize_weight_(_LABEL_SIZE, NSFontWeightBold)
    value = NSFont.monospacedDigitSystemFontOfSize_weight_(_VALUE_SIZE, NSFontWeightMedium)
    small = NSFont.monospacedDigitSystemFontOfSize_weight_(_VALUE_SIZE - 0.5, NSFontWeightRegular)
    return label, value, small


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


def layout(model: CompactModel) -> dict[str, float]:
    """x positions and total width, measured with the real fonts."""
    from AppKit import NSColor

    _, value, small = _fonts()
    colour = NSColor.labelColor()
    ssd_text_w = max(
        _attr(model.ssd.used_text, small, colour).size().width,
        _attr(model.ssd.free_text, small, colour).size().width,
    )
    cpu_x = 1.0
    ram_x = cpu_x + _BAR_WIDTH + _BLOCK_GAP
    ssd_x = ram_x + _BAR_WIDTH + _BLOCK_GAP
    text_x = ssd_x + _RING_SIZE + 4.0
    width = text_x + ssd_text_w + 1.0
    return {"cpu_x": cpu_x, "ram_x": ram_x, "ssd_x": ssd_x, "text_x": text_x, "width": width}


def _draw_bar_block(x: float, metric: BarMetric) -> None:
    from AppKit import NSBezierPath, NSColor
    from Foundation import NSMakeRect

    label_font, value_font, _ = _fonts()
    ink = NSColor.labelColor()
    label = _attr(metric.label, label_font, NSColor.secondaryLabelColor())
    value = _attr(metric.text, value_font, _fill_color(metric.severity) if metric.severity != "ok" else ink)

    top_y = IMAGE_HEIGHT - 9.5
    label.drawAtPoint_((x, top_y + 0.5))
    value.drawAtPoint_((x + _BAR_WIDTH - value.size().width, top_y))

    track = NSMakeRect(x, 2.0, _BAR_WIDTH, _BAR_HEIGHT)
    NSColor.labelColor().colorWithAlphaComponent_(0.22).setFill()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(track, 2.0, 2.0).fill()

    fill_w = max(_BAR_WIDTH * metric.fraction, 0.0)
    if fill_w > 0:
        fill_w = max(fill_w, _BAR_HEIGHT)  # keep the capsule shape for tiny values
        _fill_color(metric.severity).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(x, 2.0, fill_w, _BAR_HEIGHT), 2.0, 2.0
        ).fill()


def _draw_ring_block(x: float, text_x: float, ssd: RingMetric) -> None:
    from AppKit import NSBezierPath, NSColor
    from Foundation import NSMakePoint

    _, _, small = _fonts()
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
        end = start - 360.0 * ssd.fraction  # clockwise from 12 o'clock
        arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
            centre, radius, start, end, True
        )
        arc.setLineWidth_(_RING_LINE)
        arc.setLineCapStyle_(1)  # round
        _fill_color(ssd.severity).setStroke()
        arc.stroke()

    used = _attr(ssd.used_text, small, NSColor.labelColor())
    free = _attr(ssd.free_text, small, NSColor.secondaryLabelColor())
    used.drawAtPoint_((text_x, IMAGE_HEIGHT - 9.5))
    free.drawAtPoint_((text_x, 0.5))


def render_image(model: CompactModel):
    """Draw the model into a non-template NSImage (dynamic colours)."""
    from AppKit import NSImage
    from Foundation import NSMakeSize

    pos = layout(model)

    def handler(_rect) -> bool:
        try:
            _draw_bar_block(pos["cpu_x"], model.cpu)
            _draw_bar_block(pos["ram_x"], model.ram)
            _draw_ring_block(pos["ssd_x"], pos["text_x"], model.ssd)
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

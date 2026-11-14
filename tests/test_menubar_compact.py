"""Tests for the compact menu bar display (CPU/RAM bars + internal SSD ring).

Run with:
    "./.venv/bin/python" -m tests.test_menubar_compact
"""

import sys

from macssd.collectors.health import DriveHealth
from macssd.collectors.system import SystemStats
from macssd.collectors.thermal import ThermalStatus
from macssd.menubar import build_compact_temp_segments, tooltip_text, build_segments, temp_items
from macssd import menubar_render as r
from macssd.storage import StorageUsage

try:
    stats = SystemStats(27.4, 12.0, 16.0, 81.2, 1.0, 1.0, 1.0)
    storage = {
        "Internal SSD": StorageUsage(True, 221.0, 245.0),
        "External SSD": StorageUsage(True, 102.0, 2000.0),
    }

    # Model: percentages, GB values, internal drive only.
    m = r.build_compact_model(stats, storage)
    assert m.cpu.text == "27%" and m.ram.text == "81%", (m.cpu.text, m.ram.text)
    assert m.cpu.severity == "ok" and m.ram.severity == "warn", "81% RAM should warn"
    assert m.ssd.used_text == "221.00 GB" and m.ssd.free_text == "24.00 GB"
    assert abs(m.ssd.fraction - 221 / 245) < 1e-9
    assert m.ssd.severity in ("warn", "critical")

    # Clamping and missing data never crash.
    wild = r.build_compact_model(SystemStats(180.0, 1, 1, -5.0, 0, 0, 0), {})
    assert wild.cpu.percent == 100.0 and wild.ram.percent == 0.0
    assert wild.ssd.available is False and wild.ssd.used_text == "-- GB"
    none = r.build_compact_model(None, None)
    assert none.cpu.text == "0%" and none.ssd.fraction == 0.0
    unmounted = r.build_compact_model(stats, {"Internal SSD": StorageUsage(False)})
    assert unmounted.ssd.available is False

    # Severity thresholds.
    assert r.usage_severity(10, 80, 95) == "ok"
    assert r.usage_severity(80, 80, 95) == "warn"
    assert r.usage_severity(95, 80, 95) == "critical"

    # Temperature text is compact, preserved, and still blinkable when critical.
    settings = {"show_temps": True}
    therm = ThermalStatus(True, "nominal", "ok")
    drives = {
        "Internal SSD": DriveHealth("Internal SSD", True, "ok", 39, 70, 85, 0, 100, 0, "ok"),
        "External SSD": DriveHealth("External SSD", True, "ok", 38, 70, 85, 0, 100, 0, "ok"),
    }
    segs = build_compact_temp_segments(drives, therm, settings, 50.0)
    assert [s.text for s in segs] == ["INT 39°", "  ", "EXT 38°"], [s.text for s in segs]
    hot = dict(drives)
    hot["External SSD"] = DriveHealth("External SSD", True, "critical", 92, 70, 85, 0, 100, 0, "hot")
    segs = build_compact_temp_segments(hot, ThermalStatus(True, "serious", "x"), settings, 97.0)
    ext = next(x for x in segs if x.text == "EXT 92°")
    assert ext.severity == "critical" and ext.blinkable
    assert next(x for x in segs if x.text == "INT 39°").severity == "neutral"
    texts = "".join(s.text for s in segs)
    assert "CPU 97°C" in texts and "Mac serious" in texts
    assert build_compact_temp_segments(drives, therm, {"show_temps": False}) == []

    # Temperatures become drawable items drawn inside the image, same baseline.
    items = temp_items(build_compact_temp_segments(drives, therm, settings, 50.0))
    assert [(i.label, i.value) for i in items] == [("INT", "39°"), ("EXT", "38°")], items
    with_t = r.build_compact_model(stats, storage, temps=items)
    lp = r.layout(with_t)
    assert lp["width"] > r.layout(m)["width"] and len(lp["temps"]) == 2
    assert lp["temps"][0][1] < lp["temps"][1][1], "INT must sit left of EXT"
    trep = r.render_bitmap(with_t)
    t0 = lp["temps"][0][1]
    n = sum(1 for x in range(int(t0 * 2), trep.pixelsWide()) for y in range(trep.pixelsHigh())
            if trep.colorAtX_y_(x, y).alphaComponent() > 0.3)
    assert n > 100, "temperature text is blank"

    # Tooltip carries every reading.
    tip = tooltip_text(build_segments(drives, therm, settings, 50.0), m)
    assert "CPU 27%" in tip and "RAM 81%" in tip and "221.00 GB used, 24.00 GB free" in tip
    assert "Int 39°C" in tip and "Ext 38°C" in tip

    # Drawing: layout is sane and the bitmap actually has ink in all three blocks.
    pos = r.layout(m)
    assert pos["used_x"] < pos["ring_x"] < pos["free_x"] < pos["free_val_x"] < pos["ram_x"] < pos["cpu_x"] < pos["width"]
    assert pos["width"] < 620, f"menu bar graphic too wide: {pos['width']}"
    rep = r.render_bitmap(m)
    w, h = rep.pixelsWide(), rep.pixelsHigh()
    assert (w, h) == (int(pos["width"] * 2), int(r.IMAGE_HEIGHT * 2))

    def ink(x0, x1):
        count = 0
        for x in range(int(x0 * 2), min(int(x1 * 2), w)):
            for y in range(h):
                if rep.colorAtX_y_(x, y).alphaComponent() > 0.3:
                    count += 1
        return count

    assert ink(pos["used_x"], pos["ring_x"]) > 40, "USED text is blank"
    assert pos["used_x"] < pos["used_val_x"] < pos["ring_x"], "USED label must sit left of its number"
    assert ink(pos["ring_x"], pos["free_x"]) > 40, "ring is blank"
    assert ink(pos["free_x"], pos["ram_x"]) > 40, "FREE text is blank"
    assert ink(pos["ram_x"], pos["cpu_x"]) > 40, "RAM block is blank"
    assert ink(pos["cpu_x"], pos["width"]) > 40, "CPU block is blank"

    # Critical blink: red when 'on', normal gradient when 'off'; non-critical never red.
    hot = r.build_compact_model(SystemStats(10.0, 1, 1, 97.0, 0, 0, 0), storage)
    assert hot.ram.severity == "critical" and hot.has_critical
    assert not r.build_compact_model(stats, {}).has_critical or False
    on, off = r.render_bitmap(hot), r.render_bitmap(hot, blink_off=True)

    def reddish(rep, x0, x1):
        n = 0
        for x in range(int(x0 * 2), min(int(x1 * 2), rep.pixelsWide())):
            for y in range(rep.pixelsHigh()):
                c = rep.colorAtX_y_(x, y)
                if c.alphaComponent() > 0.5 and c.redComponent() > 0.8 and c.greenComponent() < 0.4 and c.blueComponent() < 0.4:
                    n += 1
        return n

    hp = r.layout(hot)
    assert reddish(on, hp["ram_x"], hp["cpu_x"]) > 20, "critical RAM should be red"
    assert reddish(off, hp["ram_x"], hp["cpu_x"]) == 0, "blink-off frame must not be red"
    calm = r.render_bitmap(r.build_compact_model(SystemStats(10.0, 1, 1, 50.0, 0, 0, 0), {}))
    assert reddish(calm, 0, hp["width"]) == 0, "normal readings must not be red"

    print("ALL PASS")
except (AssertionError, StopIteration) as e:
    print(f"FAIL {e}")
    sys.exit(1)

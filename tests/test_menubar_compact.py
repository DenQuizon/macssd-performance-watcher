"""Tests for the compact menu bar display (CPU/RAM bars + internal SSD ring).

Run with:
    "./.venv/bin/python" -m tests.test_menubar_compact
"""

import sys

from macssd.collectors.health import DriveHealth
from macssd.collectors.system import SystemStats
from macssd.collectors.thermal import ThermalStatus
from macssd.menubar import build_compact_temp_segments, tooltip_text, build_segments
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
    assert m.ssd.used_text == "221 GB used" and m.ssd.free_text == "24 GB free"
    assert abs(m.ssd.fraction - 221 / 245) < 1e-9
    assert m.ssd.severity in ("warn", "critical")

    # Clamping and missing data never crash.
    wild = r.build_compact_model(SystemStats(180.0, 1, 1, -5.0, 0, 0, 0), {})
    assert wild.cpu.percent == 100.0 and wild.ram.percent == 0.0
    assert wild.ssd.available is False and wild.ssd.used_text == "-- GB used"
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
    assert [s.text for s in segs] == ["39°/38°"], [s.text for s in segs]
    hot = dict(drives)
    hot["External SSD"] = DriveHealth("External SSD", True, "critical", 92, 70, 85, 0, 100, 0, "hot")
    segs = build_compact_temp_segments(hot, ThermalStatus(True, "serious", "x"), settings, 97.0)
    assert segs[0].severity == "critical" and segs[0].blinkable
    texts = "".join(s.text for s in segs)
    assert "CPU 97°C" in texts and "Mac serious" in texts
    assert build_compact_temp_segments(drives, therm, {"show_temps": False}) == []

    # Tooltip carries every reading.
    tip = tooltip_text(build_segments(drives, therm, settings, 50.0), m)
    assert "CPU 27%" in tip and "RAM 81%" in tip and "221 GB used, 24 GB free" in tip
    assert "Int 39°C" in tip and "Ext 38°C" in tip

    # Drawing: layout is sane and the bitmap actually has ink in all three blocks.
    pos = r.layout(m)
    assert pos["cpu_x"] < pos["ram_x"] < pos["ssd_x"] < pos["text_x"] < pos["width"]
    assert pos["width"] < 190, f"menu bar graphic too wide: {pos['width']}"
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

    assert ink(pos["cpu_x"], pos["ram_x"]) > 40, "CPU block is blank"
    assert ink(pos["ram_x"], pos["ssd_x"]) > 40, "RAM block is blank"
    assert ink(pos["ssd_x"], pos["width"]) > 40, "SSD block is blank"

    print("ALL PASS")
except (AssertionError, StopIteration) as e:
    print(f"FAIL {e}")
    sys.exit(1)

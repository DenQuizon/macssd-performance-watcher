"""Regression test: only temperature segments should be marked blinkable, so
a critical CPU/RAM/storage reading stays solid red while a critical
temperature reading is the one that actually flashes.

Run with: "./.venv/bin/python" -m tests.test_menubar_blink
"""

import sys

from macssd.collectors.health import DriveHealth
from macssd.collectors.system import SystemStats
from macssd.collectors.thermal import ThermalStatus
from macssd.menubar import build_segments, has_blinking_critical

settings = {"show_storage": True, "show_temps": True}

try:
    # Critical CPU, everything else normal -> must NOT trigger blinking.
    stats = SystemStats(95, 0, 0, 50, 0, 0, 0)
    health_results = {
        "Internal SSD": DriveHealth("Internal SSD", True, "ok", 40, 70, 85, 0, 100, 0, "Healthy.")
    }
    therm = ThermalStatus(True, "nominal", "ok")
    segs = build_segments(stats, {}, health_results, therm, settings)
    cpu_seg = next(s for s in segs if s.text.startswith("CPU"))
    assert cpu_seg.severity == "critical", "CPU 95% should be classified critical"
    assert cpu_seg.blinkable is False, "CPU must never be marked blinkable"
    assert has_blinking_critical(segs) is False, (
        "a critical CPU alone must not trigger the blink, only temperature does"
    )

    # Critical drive temperature -> SHOULD trigger blinking.
    stats2 = SystemStats(20, 0, 0, 30, 0, 0, 0)
    health_results2 = {
        "Internal SSD": DriveHealth("Internal SSD", True, "critical", 92, 70, 85, 0, 100, 0, "too hot")
    }
    segs2 = build_segments(stats2, {}, health_results2, therm, settings)
    temp_seg = next(s for s in segs2 if s.text.startswith("Int") and "°C" in s.text)
    assert temp_seg.severity == "critical", "92C should be classified critical"
    assert temp_seg.blinkable is True, "drive temperature must be marked blinkable"
    assert has_blinking_critical(segs2) is True, "a critical temperature must trigger the blink"

    # Critical Mac thermal state -> also blinkable.
    therm_crit = ThermalStatus(True, "critical", "overheating")
    segs3 = build_segments(stats2, {}, {}, therm_crit, settings)
    mac_seg = next(s for s in segs3 if s.text.startswith("Mac"))
    assert mac_seg.blinkable is True, "Mac thermal state must be marked blinkable"
    assert has_blinking_critical(segs3) is True

    print("ALL PASS")
except (AssertionError, StopIteration) as e:
    print(f"FAIL {e}")
    sys.exit(1)

"""Regression test: temperature segments (drive or Mac thermal state) are the
only ones marked blinkable, and only actually blink when critical.

Run with: "./.venv/bin/python" -m tests.test_menubar_blink
"""

import sys

from macssd.collectors.health import DriveHealth
from macssd.collectors.thermal import ThermalStatus
from macssd.menubar import build_segments, has_blinking_critical

settings = {"show_temps": True}

try:
    # Normal drive temp, normal thermal state -> no blinking.
    health_results = {
        "Internal SSD": DriveHealth("Internal SSD", True, "ok", 40, 70, 85, 0, 100, 0, "Healthy.")
    }
    therm = ThermalStatus(True, "nominal", "ok")
    segs = build_segments(health_results, therm, settings)
    temp_seg = next(s for s in segs if s.text.startswith("Int") and "°C" in s.text)
    assert temp_seg.severity == "ok", "40C should be classified ok"
    assert temp_seg.blinkable is True, "drive temperature must always be marked blinkable"
    assert has_blinking_critical(segs) is False, "a normal temperature must not trigger the blink"

    # Critical drive temperature -> SHOULD trigger blinking.
    health_results2 = {
        "Internal SSD": DriveHealth("Internal SSD", True, "critical", 92, 70, 85, 0, 100, 0, "too hot")
    }
    segs2 = build_segments(health_results2, therm, settings)
    temp_seg2 = next(s for s in segs2 if s.text.startswith("Int") and "°C" in s.text)
    assert temp_seg2.severity == "critical", "92C should be classified critical"
    assert temp_seg2.blinkable is True, "drive temperature must be marked blinkable"
    assert has_blinking_critical(segs2) is True, "a critical temperature must trigger the blink"

    # Critical Mac thermal state -> also blinkable.
    therm_crit = ThermalStatus(True, "critical", "overheating")
    segs3 = build_segments({}, therm_crit, settings)
    mac_seg = next(s for s in segs3 if s.text.startswith("Mac"))
    assert mac_seg.blinkable is True, "Mac thermal state must be marked blinkable"
    assert has_blinking_critical(segs3) is True

    print("ALL PASS")
except (AssertionError, StopIteration) as e:
    print(f"FAIL {e}")
    sys.exit(1)

"""Tests for the menu bar title formatting (temperature-only, post-simplification).

Run with:
    "./.venv/bin/python" -m tests.test_menubar_title
"""

import sys

from macssd.collectors.health import DriveHealth
from macssd.collectors.thermal import ThermalStatus
from macssd.menubar import render_menubar_title

try:
    # Case one: nothing available -> still a non-empty string, no crash.
    drives_1 = {}
    thermal_1 = ThermalStatus(available=False, state="", reason="unavailable")
    result_1 = render_menubar_title(drives_1, thermal_1)
    assert isinstance(result_1, str) and result_1 != "", "non-empty string when nothing is available"

    # Case two: a drive temp should show up with a degree symbol.
    drives_2 = {
        "Internal SSD": DriveHealth(name="Internal SSD", available=True, status="ok", temp_c=37)
    }
    thermal_2 = ThermalStatus(available=True, state="nominal", reason="System is operating normally.")
    result_2 = render_menubar_title(drives_2, thermal_2)
    assert "37" in result_2 and "°" in result_2, "37 and degree symbol"
    assert "Mac nominal" in result_2, "Mac thermal state should be shown"

    # Case three: drive present but unavailable -> falls back to "--", no crash.
    drives_3 = {"Internal SSD": DriveHealth(name="Internal SSD", available=False)}
    thermal_3 = ThermalStatus(available=False, state="", reason="")
    result_3 = render_menubar_title(drives_3, thermal_3)
    assert isinstance(result_3, str) and result_3 != "", "non-empty string"

    print("ALL PASS")
except AssertionError as e:
    print(f"FAIL {e}")
    sys.exit(1)

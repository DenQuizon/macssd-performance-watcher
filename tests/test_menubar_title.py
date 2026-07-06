"""Tests for the menu bar title formatting.

Authored by agy (Gemini 3.5 Flash, Medium) as the test role in the
orchestration; integrated by Claude. Run with:
    "./.venv/bin/python" -m tests.test_menubar_title
"""

import sys

from macssd.collectors.health import DriveHealth
from macssd.collectors.system import SystemStats
from macssd.collectors.thermal import ThermalStatus
from macssd.menubar import render_menubar_title

try:
    # Case one
    stats_1 = SystemStats(23, 0.0, 0.0, 79, 0.0, 0.0, 0.0)
    drives_1 = {}
    thermal_1 = ThermalStatus(available=False, state="", reason="unavailable")
    result_1 = render_menubar_title(stats_1, drives_1, thermal_1)
    assert any(x in result_1 for x in ["CPU 23 percent", "CPU 23%", "23%", "23"]), "CPU 23 percent"
    assert any(x in result_1 for x in ["RAM 79 percent", "RAM 79%", "79%", "79"]), "RAM 79 percent"

    # Case two
    stats_2 = SystemStats(23, 0.0, 0.0, 79, 0.0, 0.0, 0.0)
    drives_2 = {
        "Internal SSD": DriveHealth(name="Internal SSD", available=True, status="ok", temp_c=37)
    }
    thermal_2 = ThermalStatus(available=True, state="nominal", reason="System is operating normally.")
    result_2 = render_menubar_title(stats_2, drives_2, thermal_2)
    assert "37" in result_2 and ("°" in result_2 or "deg" in result_2 or "degree" in result_2), (
        "37 and degree symbol"
    )

    # Case three
    stats_3 = SystemStats(23, 0.0, 0.0, 79, 0.0, 0.0, 0.0)
    drives_3 = {"Internal SSD": DriveHealth(name="Internal SSD", available=False)}
    thermal_3 = ThermalStatus(available=False, state="", reason="")
    result_3 = render_menubar_title(stats_3, drives_3, thermal_3)
    assert isinstance(result_3, str) and result_3 != "", "non-empty string"

except AssertionError as e:
    print(f"FAIL {e}")
    sys.exit(1)

print("ALL PASS")

"""Tests for the combined drive+thermal hardware-health headline.

Authored by agy (Gemini 3.5 Flash) as the test role in the orchestration;
integrated by Claude. Case 3 and case 4 specifically verify a fix flagged
during review: a critical thermal state must never be hidden by a healthy
drive, and an unavailable thermal reading must never be reported as healthy.
Run with:
    "./.venv/bin/python" -m tests.test_health_headline
"""

import sys

from macssd.app import _health_headline
from macssd.collectors.health import DriveHealth
from macssd.collectors.thermal import ThermalStatus

try:
    dh1 = DriveHealth("disk0", True, "ok", 35, 70, 80, 5, 100, 0, "no error")
    ts1 = ThermalStatus(True, "nominal", "some cool text")
    res1 = _health_headline({"disk0": dh1}, ts1)
    assert "healthy" in res1.lower(), "Case 1: healthy expected"

    dh2 = DriveHealth("disk0", True, "critical", 35, 70, 80, 5, 100, 0, "critical error")
    ts2 = ThermalStatus(True, "nominal", "some cool text")
    res2 = _health_headline({"disk0": dh2}, ts2)
    assert "attention" in res2.lower(), "Case 2: attention expected"

    dh3 = DriveHealth("disk0", True, "ok", 35, 70, 80, 5, 100, 0, "no error")
    ts3 = ThermalStatus(True, "critical", "some hot text")
    res3 = _health_headline({"disk0": dh3}, ts3)
    assert "attention" in res3.lower(), "Case 3: attention expected"

    dh4 = DriveHealth("disk0", True, "ok", 35, 70, 80, 5, 100, 0, "no error")
    ts4 = ThermalStatus(False, "unknown", "unused text")
    res4 = _health_headline({"disk0": dh4}, ts4)
    assert "healthy" in res4.lower(), "Case 4: healthy expected"
    assert "could not be checked" in res4.lower(), "Case 4: could not be checked expected"

    print("ALL PASS")

except AssertionError as e:
    print("FAIL " + str(e))
    sys.exit(1)

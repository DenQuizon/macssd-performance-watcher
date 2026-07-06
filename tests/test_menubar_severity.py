"""Boundary tests for the menu bar severity classifiers.

Authored by agy (Gemini 3.5 Flash, Medium) as the test role in the
orchestration; integrated by Claude. Run with:
    "./.venv/bin/python" -m tests.test_menubar_severity
"""

import sys

from macssd.menubar import _cpu_severity, _ram_severity, _storage_severity

try:
    # CPU severity tests
    assert _cpu_severity(59.9) == "ok", "CPU 59.9% should be ok"
    assert _cpu_severity(60.0) == "warn", "CPU 60.0% should be warn"
    assert _cpu_severity(84.9) == "warn", "CPU 84.9% should be warn"
    assert _cpu_severity(85.0) == "critical", "CPU 85.0% should be critical"

    # RAM severity tests
    assert _ram_severity(59.9) == "ok", "RAM 59.9% should be ok"
    assert _ram_severity(60.0) == "warn", "RAM 60.0% should be warn"
    assert _ram_severity(79.9) == "warn", "RAM 79.9% should be warn"
    assert _ram_severity(80.0) == "critical", "RAM 80.0% should be critical"

    # Storage severity tests
    assert _storage_severity(90, 100) == "critical", "Storage 90/100 (90%) should be critical"
    assert _storage_severity(79, 100) == "ok", "Storage 79/100 (79%) should be ok"
    assert _storage_severity(80, 100) == "warn", "Storage 80/100 (80%) should be warn"
    assert _storage_severity(0, 0) == "neutral", "Storage 0/0 (total is zero) should be neutral"

except AssertionError as e:
    print(f"FAIL: {e}")
    sys.exit(1)

print("ALL PASS")

"""Tests for the SSD health status classifier.

Base cases authored by agy (Gemini 3.5 Flash) as the test role in the
orchestration; integrated by Claude, with one extra case added to verify a
Codex-flagged severity-ordering fix (critical temp must not be masked by a
lower-severity media-error warning). Run with:
    "./.venv/bin/python" -m tests.test_health
"""

import sys

from macssd.collectors.health import _evaluate


def _base(temp: int, passed: bool = True, critical_warning: int = 0, media_errors: int = 0):
    return {
        "smart_status": {"passed": passed},
        "temperature": {"current": temp},
        "nvme_composite_temperature_threshold": {"warning": 70, "critical": 85},
        "nvme_smart_health_information_log": {
            "critical_warning": critical_warning,
            "percentage_used": 2,
            "available_spare": 100,
            "media_errors": media_errors,
        },
    }


try:
    assert _evaluate(_base(38), "disk0").status == "ok", "Healthy drive should return ok"
    assert _evaluate(_base(75), "disk0").status == "warn", "Warm drive should return warn"
    assert _evaluate(_base(90), "disk0").status == "critical", "Hot drive should return critical"
    assert _evaluate(_base(38, passed=False), "disk0").status == "critical", (
        "Failed SMART status drive should return critical"
    )
    assert _evaluate(_base(38, critical_warning=1), "disk0").status == "critical", (
        "Drive with critical warning should return critical"
    )
    # Codex-flagged case: critical temp + media errors must stay critical, not
    # get downgraded to warn by the lower-severity media-errors check.
    assert _evaluate(_base(90, media_errors=3), "disk0").status == "critical", (
        "Critical temperature must not be masked by a media-error warning"
    )
except AssertionError as e:
    print(f"FAIL {e}")
    sys.exit(1)

print("ALL PASS")

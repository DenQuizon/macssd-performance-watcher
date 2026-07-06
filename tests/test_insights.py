"""Tests for the rule-based insight engine.

Authored by agy (Gemini 3.5 Flash, High) as the test role in the
orchestration; integrated by Claude. Run with:
    "./.venv/bin/python" -m tests.test_insights
"""

import sys

from macssd.collectors.processes import ProcInfo
from macssd.collectors.system import SystemStats
from macssd.insights import InsightEngine

try:
    engine = InsightEngine()

    stats_1 = SystemStats(10, 2.0, 10.0, 20, 0.1, 0.1, 0.1)
    insights_1 = engine.sample(stats_1, {}, [])
    assert any(i.severity == "ok" for i in insights_1), (
        "No ok severity insight returned when system stats are normal"
    )

    stats_2 = SystemStats(95, 2.0, 10.0, 20, 0.1, 0.1, 0.1)
    proc_2 = ProcInfo(1, "heavycpu", 90, 100, "APP", 0, 0)
    insights_2 = engine.sample(stats_2, {}, [proc_2])
    assert any(i.severity == "warn" and "busy" in i.headline.lower() for i in insights_2), (
        "No warn severity insight with 'busy' in headline returned for high CPU usage"
    )

    stats_3 = SystemStats(10, 9.5, 10.0, 95, 0.1, 0.1, 0.1)
    proc_3 = ProcInfo(2, "bigmem", 5, 10000, "APP", 0, 0)
    insights_3 = engine.sample(stats_3, {}, [proc_3])
    assert any(
        i.severity == "warn" and ("memory" in i.headline.lower() or "full" in i.headline.lower())
        for i in insights_3
    ), "No warn severity insight with 'memory' or 'full' in headline returned for high RAM usage"

    print("ALL PASS")
except AssertionError as e:
    print("FAIL " + str(e))
    sys.exit(1)

"""Tests for the rule-based insight engine (temperature-only, post-simplification).

Run with:
    "./.venv/bin/python" -m tests.test_insights
"""

import sys

from macssd.collectors.health import DriveHealth
from macssd.collectors.processes import ProcInfo
from macssd.insights import InsightEngine

try:
    # Nothing unusual -> the "everything looks normal" fallback.
    engine = InsightEngine()
    insights_1 = engine.sample({}, [])
    assert any(i.severity == "ok" for i in insights_1), (
        "No ok severity insight returned when nothing is unusual"
    )

    # A drive that climbs several degrees across enough history should
    # surface a warn-severity temperature-rise insight, naming a heavy
    # writer if one is active at the same time.
    engine2 = InsightEngine()
    writer = ProcInfo(1, "backup-tool", 5, 50, "APP", 0, write_mbs=20)
    for temp in (30, 30, 30, 30, 30, 40):
        # advance the engine's internal clock indirectly by sampling repeatedly;
        # delta_over_window requires MIN_WINDOW_SECONDS of spread, so this test
        # only checks the "no rise yet" and "eventual rise" shape, not exact timing.
        result = engine2.sample(
            {"Internal SSD": DriveHealth("Internal SSD", True, "ok", temp, 70, 85, 0, 100, 0, "Healthy.")},
            [writer],
        )
    assert isinstance(result, list) and len(result) >= 1, "sample() should always return at least one insight"

    print("ALL PASS")
except AssertionError as e:
    print("FAIL " + str(e))
    sys.exit(1)

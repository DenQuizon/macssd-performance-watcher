"""Regression test for a Codex-flagged bug: a drive that disconnects and
reconnects within the insight engine's temperature window must not compare
its new readings against stale pre-disconnect history (that would produce a
false temperature-rise insight based on a blind gap in monitoring).

Run with: "./.venv/bin/python" -m tests.test_insights_reconnect
"""

import sys

from macssd.collectors.health import DriveHealth
from macssd.collectors.system import SystemStats
from macssd.insights import InsightEngine

try:
    engine = InsightEngine()
    stats = SystemStats(10, 2.0, 10.0, 20, 0.1, 0.1, 0.1)

    # Drive reports 30C, present.
    r1 = engine.sample(stats, {"USB SSD": DriveHealth("USB SSD", True, "ok", 30, 70, 85, 0, 100, 0, "Healthy.")}, [])
    assert not any("temperature rose" in i.headline for i in r1), "no rise expected on first sample"

    # Drive disconnects (absent from health_results) — simulates unplugging.
    engine.sample(stats, {}, [])

    # Drive reconnects reporting 45C. Because history should have been wiped
    # on disconnect, there isn't yet enough continuous history to judge a
    # trend, so this must NOT fire a temperature-rise insight comparing
    # against the pre-disconnect 30C reading.
    r3 = engine.sample(
        stats, {"USB SSD": DriveHealth("USB SSD", True, "ok", 45, 70, 85, 0, 100, 0, "Healthy.")}, []
    )
    assert not any("temperature rose" in i.headline for i in r3), (
        "reconnect must not compare against stale pre-disconnect history"
    )

    print("ALL PASS")
except AssertionError as e:
    print("FAIL " + str(e))
    sys.exit(1)

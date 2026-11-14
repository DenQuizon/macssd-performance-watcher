"""Shared thermal severity mapping.

Used by both the live menu bar (checking a fresh value every few seconds)
and the periodic background watcher (checking a single snapshot) — a single
source of truth so the two never quietly disagree about what counts as a
problem.
"""

from __future__ import annotations

THERMAL_SEVERITY = {"nominal": "ok", "fair": "ok", "serious": "warn", "critical": "critical"}

# Apple Silicon CPU die temperature (from macmon), independent of Apple's own
# nominal/fair/serious/critical thermal-pressure signal above.
CPU_TEMP_WARN_C = 85.0
CPU_TEMP_CRIT_C = 95.0


def cpu_temp_severity(temp_c: float | None) -> str:
    if temp_c is None:
        return "unknown"
    if temp_c >= CPU_TEMP_CRIT_C:
        return "critical"
    if temp_c >= CPU_TEMP_WARN_C:
        return "warn"
    return "ok"

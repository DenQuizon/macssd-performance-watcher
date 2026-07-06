"""Shared severity thresholds for CPU, RAM, storage, and thermal readings.

Used by both the live menu bar (checking a fresh value every few seconds)
and the hourly background watcher (checking a single snapshot) — a single
source of truth so the two never quietly disagree about what counts as a
problem.
"""

from __future__ import annotations


def cpu_severity(pct: float) -> str:
    if pct >= 85:
        return "critical"
    if pct >= 60:
        return "warn"
    return "ok"


def ram_severity(pct: float) -> str:
    if pct >= 80:
        return "critical"
    if pct >= 60:
        return "warn"
    return "ok"


def storage_severity(used_gb: float, total_gb: float) -> str:
    if total_gb <= 0:
        return "neutral"
    pct = used_gb / total_gb * 100
    if pct >= 90:
        return "critical"
    if pct >= 80:
        return "warn"
    return "ok"


THERMAL_SEVERITY = {"nominal": "ok", "fair": "ok", "serious": "warn", "critical": "critical"}

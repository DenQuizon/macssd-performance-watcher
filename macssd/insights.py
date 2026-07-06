"""The rule-based insight engine: turns raw numbers into plain-English causes.

Deliberately rule-based, not AI-driven — instant, free, and works offline.
Each rule looks at the latest snapshot from the collectors (plus, for the
temperature rule, a short rolling history) and produces zero or more Insight
objects. The panel always shows at least one line: a positive "all clear"
insight when nothing else fires.

Honesty note: the temperature-rise rule names "likely contributors" using
whichever processes are writing heavily *right now*, not a historical replay
of who was writing during the whole window — the app does not keep a full
per-process I/O history, so it would be dishonest to claim otherwise.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from macssd.collectors.health import DriveHealth
from macssd.collectors.processes import ProcInfo
from macssd.collectors.system import SystemStats

WINDOW_SECONDS = 300  # look back up to 5 minutes for the temperature-rise rule
MIN_WINDOW_SECONDS = 90  # need at least this much history before judging a trend
TEMP_RISE_THRESHOLD_C = 5
CPU_BUSY_THRESHOLD = 85
RAM_FULL_THRESHOLD = 85
ACTIVE_WRITE_MBS = 5  # a process writing at least this fast counts as a "contributor"
AI_DEV_DOMINANT_SHARE = 0.5  # AI/DEV tools using over half of busy-process CPU


@dataclass
class Insight:
    severity: str  # "warn" | "info" | "ok"
    headline: str
    detail: str = ""


@dataclass
class _TempHistory:
    samples: deque[tuple[float, int]] = field(default_factory=lambda: deque(maxlen=200))

    def record(self, temp_c: int) -> None:
        self.samples.append((time.monotonic(), temp_c))

    def delta_over_window(self, window: float) -> tuple[int, int, float] | None:
        """Return (current_temp, delta, minutes_covered) if enough history exists."""
        if not self.samples:
            return None
        now, current = self.samples[-1]
        oldest_in_window = None
        for ts, temp in self.samples:
            if now - ts <= window:
                oldest_in_window = (ts, temp)
                break
        if oldest_in_window is None:
            return None
        span = now - oldest_in_window[0]
        if span < MIN_WINDOW_SECONDS:
            return None
        return current, current - oldest_in_window[1], span / 60


class InsightEngine:
    """Call sample() every tick with the latest collector snapshots."""

    def __init__(self) -> None:
        self._temps: dict[str, _TempHistory] = {}

    def sample(
        self,
        stats: SystemStats,
        health_results: dict[str, DriveHealth],
        top_procs: list[ProcInfo],
    ) -> list[Insight]:
        seen = set()
        for name, h in health_results.items():
            if h.temp_c is None:
                continue
            seen.add(name)
            self._temps.setdefault(name, _TempHistory()).record(h.temp_c)

        # A drive that stops reporting a temp (disconnected, or smartctl
        # failed) must not silently resume its old history on reconnect —
        # that would compare against pre-gap data and give a false delta.
        for name in list(self._temps):
            if name not in seen:
                del self._temps[name]

        insights: list[Insight] = []
        insights.extend(self._temperature_insights(top_procs))
        insights.extend(self._cpu_insight(stats, top_procs))
        insights.extend(self._ram_insight(stats, top_procs))
        insights.extend(self._ai_dev_insight(stats, top_procs))

        if not insights:
            insights.append(Insight("ok", "Everything looks normal — no unusual load right now."))
        return insights

    def _temperature_insights(self, top_procs: list[ProcInfo]) -> list[Insight]:
        writers = sorted(
            (p for p in top_procs if p.write_mbs >= ACTIVE_WRITE_MBS),
            key=lambda p: p.write_mbs,
            reverse=True,
        )[:3]

        out = []
        for name, hist in self._temps.items():
            result = hist.delta_over_window(WINDOW_SECONDS)
            if result is None:
                continue
            current, delta, minutes = result
            if delta < TEMP_RISE_THRESHOLD_C:
                continue
            headline = f"{name} temperature rose {delta}°C in the last {minutes:.0f} min."
            if writers:
                names = ", ".join(p.name for p in writers)
                headline += f" Heavy disk writers right now: {names}."
                detail = ", ".join(f"{p.name} {p.write_mbs:.0f} MB/s" for p in writers)
            else:
                detail = ""
            detail = f"Now {current}°C. {detail}".strip()
            out.append(Insight("warn", headline, detail))
        return out

    def _cpu_insight(self, stats: SystemStats, top_procs: list[ProcInfo]) -> list[Insight]:
        if stats.cpu_percent < CPU_BUSY_THRESHOLD:
            return []
        top = sorted(top_procs, key=lambda p: p.cpu, reverse=True)[:3]
        names = ", ".join(p.name for p in top) if top else "no single process stands out"
        headline = f"CPU is very busy ({stats.cpu_percent:.0f}%). Top users: {names}."
        detail = ", ".join(f"{p.name} {p.cpu:.0f}%" for p in top)
        return [Insight("warn", headline, detail)]

    def _ram_insight(self, stats: SystemStats, top_procs: list[ProcInfo]) -> list[Insight]:
        if stats.ram_percent < RAM_FULL_THRESHOLD:
            return []
        top = sorted(top_procs, key=lambda p: p.mem_mb, reverse=True)[:3]
        names = ", ".join(p.name for p in top) if top else "no single process stands out"
        headline = f"Memory is nearly full ({stats.ram_percent:.0f}%). Top users: {names}."
        detail = ", ".join(f"{p.name} {p.mem_mb:.0f} MB" for p in top)
        return [Insight("warn", headline, detail)]

    def _ai_dev_insight(self, stats: SystemStats, top_procs: list[ProcInfo]) -> list[Insight]:
        busy_cpu = sum(p.cpu for p in top_procs)
        if busy_cpu <= 0:
            return []
        ai_cpu = sum(p.cpu for p in top_procs if p.tag == "AI/DEV")
        if ai_cpu / busy_cpu < AI_DEV_DOMINANT_SHARE:
            return []
        headline = "Your AI/developer tools are using most of the CPU right now."
        names = ", ".join(p.name for p in top_procs if p.tag == "AI/DEV")
        detail = f"{ai_cpu:.0f}% of {busy_cpu:.0f}% busy-process CPU: {names}"
        return [Insight("info", headline, detail)]

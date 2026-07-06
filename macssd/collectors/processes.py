"""Top processes by CPU or memory, each tagged AI/DEV, SYSTEM, or APP.

Per-process CPU% works like the whole-system one: the first reading after a
process is first seen is 0, so call prime() once at startup and the next read
reflects real usage.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import psutil

from macssd.collectors import rusage

_MB = 1024 * 1024          # memory (RSS) in mebibytes, the usual convention
_MB_RATE = 1_000_000       # disk speed in decimal MB/s, matching the disk panel

# Substrings that identify Den's AI / developer tools.
_AI_DEV = (
    "claude", "codex", "gemini", "agy", "ollama", "llama", "docker",
    "node", "python", "deno", "bun", "code", "cursor", "java", "jupyter",
)

# Substrings that identify macOS system daemons.
_SYSTEM = (
    "kernel_task", "mds", "mdworker", "spotlight", "windowserver", "launchd",
    "coreaudiod", "bluetoothd", "systemstats", "cfprefsd", "distnoted", "logd",
    "trustd", "secd", "opendirectoryd", "powerd", "thermalmonitord", "backupd",
    "spindump", "hidd", "configd", "notifyd",
)


def _word_start_re(words) -> re.Pattern:
    """Match any keyword at the start of a word (\\bkeyword), case-insensitive.

    Anchoring to a word boundary avoids matching keywords inside other words
    (e.g. 'code' won't match 'decode') while still allowing version suffixes
    (e.g. 'python' matches 'python3.13').
    """
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")", re.IGNORECASE)


_AI_DEV_RE = _word_start_re(_AI_DEV)
_SYSTEM_RE = _word_start_re(_SYSTEM)


@dataclass
class ProcInfo:
    pid: int
    name: str
    cpu: float
    mem_mb: float
    tag: str
    read_mbs: float = 0.0
    write_mbs: float = 0.0
    create_time: float = 0.0  # identifies THIS process instance, distinct from a reused pid


def classify(name: str) -> str:
    """Tag a process by name: AI/DEV, SYSTEM, or APP (case-insensitive)."""
    if _AI_DEV_RE.search(name):
        return "AI/DEV"
    if _SYSTEM_RE.search(name):
        return "SYSTEM"
    return "APP"


_SORT_KEYS = {
    "cpu": lambda p: p.cpu,
    "mem": lambda p: p.mem_mb,
    "disk": lambda p: p.read_mbs + p.write_mbs,
}


class ProcessCollector:
    """Samples all processes once per tick, then serves sorted top-N views.

    Splitting sample() from top() means pressing a sort key re-sorts the last
    snapshot without taking a new (mis-timed) disk-rate reading.
    """

    def __init__(self) -> None:
        # pid -> (read_bytes, write_bytes, create_time). create_time distinguishes
        # a reused pid from the original process so we don't spike on reuse.
        self._disk_prev: dict[int, tuple[int, int, float]] = {}
        self._disk_prev_t: float | None = None
        self._last: list[ProcInfo] = []

    def prime(self) -> None:
        """Prime per-process CPU counters so the next sample() is real."""
        for proc in psutil.process_iter(["cpu_percent"]):
            try:
                _ = proc.info
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def sample(self) -> None:
        """Refresh the snapshot: CPU, memory, and per-process disk rates."""
        now = time.monotonic()
        elapsed = (now - self._disk_prev_t) if self._disk_prev_t is not None else None
        self._disk_prev_t = now

        new_prev: dict[int, tuple[int, int, float]] = {}
        procs: list[ProcInfo] = []
        for proc in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_info", "create_time"]
        ):
            try:
                info = proc.info
                pid = info["pid"]
                name = info.get("name") or "?"
                cpu = info.get("cpu_percent") or 0.0
                mem = info.get("memory_info")
                mem_mb = (mem.rss / _MB) if mem else 0.0
                ctime = info.get("create_time") or 0.0
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            read_mbs = write_mbs = 0.0
            io = rusage.disk_io(pid)
            if io is not None:
                new_prev[pid] = (io[0], io[1], ctime)
                prev = self._disk_prev.get(pid)
                # only a delta if it is the same process (matching start time)
                if prev is not None and elapsed and prev[2] == ctime:
                    read_mbs = max(0.0, (io[0] - prev[0]) / elapsed / _MB_RATE)
                    write_mbs = max(0.0, (io[1] - prev[1]) / elapsed / _MB_RATE)

            procs.append(
                ProcInfo(pid, name, cpu, mem_mb, classify(name), read_mbs, write_mbs, ctime)
            )

        self._disk_prev = new_prev  # forget pids that have gone away
        self._last = procs

    def top(self, sort_by: str = "cpu", limit: int = 8) -> list[ProcInfo]:
        key = _SORT_KEYS.get(sort_by, _SORT_KEYS["cpu"])
        return sorted(self._last, key=key, reverse=True)[:limit]

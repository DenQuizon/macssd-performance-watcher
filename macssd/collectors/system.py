"""CPU and RAM stats via psutil.

CPU percent is measured since the previous call (non-blocking), so the very
first reading after startup would be 0.0. Call prime() once at startup so the
first real read reflects actual usage.

RAM on macOS: "used" is derived from available memory (total - available) and
the percentage is psutil's mem.percent, which is based on the same figure. This
keeps the GB shown and the percentage consistent, and reflects real memory
pressure rather than the misleading "used" counter macOS reports separately.

RAM reads can intermittently fail on some macOS builds: psutil.virtual_memory()
occasionally raises RuntimeError("host_statistics64(HOST_VM_INFO64) syscall
failed") — observed to fail in bursts of several consecutive calls (roughly
40% of calls in one measured run). Mid-session, read() falls back to the last
successful RAM reading rather than crashing the caller. On the very first
call (no fallback value exists yet), it retries a few times before giving up
and reporting RAM as 0 — confirmed to actually happen in practice, not just
theoretically. CPU% and load are unaffected since they come from a different,
unaffected psutil call.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import psutil

_GB = 1024 ** 3
_last_mem = None  # last successful psutil.virtual_memory() result, for fallback
_FIRST_CALL_RETRIES = 3  # only worth retrying before there's a fallback value to use


@dataclass
class SystemStats:
    cpu_percent: float
    ram_used_gb: float
    ram_total_gb: float
    ram_percent: float
    load_1: float
    load_5: float
    load_15: float


def prime() -> None:
    """Prime the CPU counter so the next read() reflects real usage."""
    psutil.cpu_percent(interval=None)


def read() -> SystemStats:
    """Return a snapshot of overall CPU and RAM usage."""
    global _last_mem
    cpu = psutil.cpu_percent(interval=None)
    try:
        mem = psutil.virtual_memory()
        _last_mem = mem
    except RuntimeError:
        if _last_mem is not None:
            mem = _last_mem  # mid-session: fall straight back to the last good value
        else:
            # No fallback value exists yet (this is the very first-ever
            # read). A single retry usually isn't enough — failures were
            # observed in bursts of several consecutive calls — but most
            # bursts are short, so a few quick retries meaningfully cut the
            # odds of showing "RAM 0%" on a cold start.
            mem = None
            for _ in range(_FIRST_CALL_RETRIES):
                time.sleep(0.05)
                try:
                    mem = psutil.virtual_memory()
                    _last_mem = mem
                    break
                except RuntimeError:
                    continue
            if mem is None:
                class _Zero:
                    total = available = percent = 0
                mem = _Zero()
    load_1, load_5, load_15 = os.getloadavg()
    return SystemStats(
        cpu_percent=cpu,
        ram_used_gb=(mem.total - mem.available) / _GB,
        ram_total_gb=mem.total / _GB,
        ram_percent=mem.percent,
        load_1=load_1,
        load_5=load_5,
        load_15=load_15,
    )


def describe_cpu(percent: float) -> str:
    """Plain-English label for a CPU load percentage."""
    if percent < 25:
        return "light load"
    if percent < 60:
        return "moderate load"
    if percent < 85:
        return "working hard"
    return "very busy"


def describe_ram(percent: float) -> str:
    """Plain-English label for a RAM usage percentage."""
    if percent < 60:
        return "plenty free"
    if percent < 80:
        return "getting full"
    return "nearly full"

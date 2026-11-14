"""Overall system thermal pressure, via macOS's public ProcessInfo API.

True fan RPM is not available on Apple Silicon without either root privileges
(powermetrics) or Apple's undocumented private SMC interface, so this uses the
officially supported alternative instead: NSProcessInfo.thermalState(), the
same signal macOS itself uses to decide when to throttle. It answers "is this
Mac thermally stressed" reliably, even though it can't report a raw RPM number.

Apple's documented enum (ProcessInfoThermalState):
  0 = nominal   -- no thermal pressure
  1 = fair      -- slightly elevated, no action needed
  2 = serious   -- fans at or near maximum, performance may be reduced
  3 = critical  -- system is actively cooling itself, expect slowdown
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass

try:
    from Foundation import NSProcessInfo
    _AVAILABLE = True
except ImportError:  # pyobjc not installed, or not on macOS
    _AVAILABLE = False

_STATES = {
    0: ("nominal", "Running cool, no thermal pressure."),
    1: ("fair", "Slightly warm, but nothing to worry about."),
    2: ("serious", "Working hard to stay cool — fans are likely near maximum."),
    3: ("critical", "Overheating — macOS is actively slowing things down to cool off."),
}


@dataclass
class ThermalStatus:
    available: bool
    state: str = "unknown"
    reason: str = "Thermal state is not available on this machine."


def available() -> bool:
    return _AVAILABLE


def read() -> ThermalStatus:
    """Return the current system-wide thermal pressure state."""
    if not _AVAILABLE:
        return ThermalStatus(False)
    raw = NSProcessInfo.processInfo().thermalState()
    state, reason = _STATES.get(raw, ("unknown", f"Unrecognised thermal state ({raw})."))
    return ThermalStatus(True, state, reason)


# --- Numeric CPU temperature, via macmon (no sudo required) ----------------
#
# NSProcessInfo.thermalState() above answers "is the Mac under thermal
# pressure" but never gives a number. macmon (https://github.com/vladkens/macmon)
# reads Apple Silicon's real SMC temperature sensors without root, so this
# gives an actual degrees-C reading to show alongside the two SSD temps.
#
# Shelling out takes ~0.3-0.5s even with a short sample interval, so this
# caches like health.py's smartctl calls do — call cpu_temp() every tick,
# it only actually runs macmon every REFRESH_SECONDS.

CPU_TEMP_REFRESH_SECONDS = 8.0

_macmon_cache: float | None = None
_macmon_last_run: float | None = None


def _macmon_path() -> str | None:
    return shutil.which("macmon") or (
        "/opt/homebrew/bin/macmon" if shutil.which("/opt/homebrew/bin/macmon") else None
    )


def cpu_temp_available() -> bool:
    return _macmon_path() is not None


def cpu_temp_c(force: bool = False) -> float | None:
    """Current CPU temperature in Celsius, or None if macmon isn't installed
    or the reading failed. Cached for CPU_TEMP_REFRESH_SECONDS between calls."""
    global _macmon_cache, _macmon_last_run
    now = time.monotonic()
    due = _macmon_last_run is None or (now - _macmon_last_run) >= CPU_TEMP_REFRESH_SECONDS
    if not due and not force:
        return _macmon_cache

    _macmon_last_run = now
    cmd = _macmon_path()
    if cmd is None:
        _macmon_cache = None
        return None

    try:
        proc = subprocess.run(
            [cmd, "pipe", "-i", "200", "-s", "1"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        data = json.loads(proc.stdout)
        _macmon_cache = float(data["temp"]["cpu_temp_avg"])
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        _macmon_cache = None
    return _macmon_cache

"""SSD temperature and SMART health for both drives, via smartctl.

Requires the smartmontools package (`brew install smartmontools`). Reuses the
same mountpoint -> physical disk mapping as the disk-speed collector.

Temperature changes slowly compared to CPU/RAM, and shelling out to smartctl
on every 2s UI tick is wasteful, so this collector throttles itself: sample()
can be called every tick, but only actually runs smartctl every
REFRESH_SECONDS, returning the cached result the rest of the time.

Apple's internal SSD firmware does not report warning/critical temperature
thresholds via NVMe SMART, so we fall back to conservative NVMe defaults
(70C warning, 85C critical) when a drive does not report its own.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass

from macssd.collectors.disk import DRIVES, physical_io_key

REFRESH_SECONDS = 10.0
_DEFAULT_WARN_C = 70
_DEFAULT_CRIT_C = 85
_SMARTCTL_TIMEOUT = 6


@dataclass
class DriveHealth:
    name: str
    available: bool
    status: str = "unknown"  # "ok" | "warn" | "critical" | "unknown"
    temp_c: int | None = None
    warn_c: int = _DEFAULT_WARN_C
    crit_c: int = _DEFAULT_CRIT_C
    wear_pct: int | None = None
    spare_pct: int | None = None
    media_errors: int | None = None
    reason: str = ""


_SMARTCTL_FALLBACK_PATHS = [
    "/opt/homebrew/bin/smartctl",
    "/usr/local/bin/smartctl",
]


def _smartctl_path() -> str | None:
    found = shutil.which("smartctl")
    if found:
        return found
    for p in _SMARTCTL_FALLBACK_PATHS:
        if shutil.which(p):
            return p
    return None


def smartctl_available() -> bool:
    return _smartctl_path() is not None


def _read_smart(device: str) -> dict | None:
    """Run smartctl -a -j on a whole-disk device, returning parsed JSON or None."""
    cmd = _smartctl_path() or "smartctl"
    try:
        proc = subprocess.run(
            [cmd, "-a", "-j", device],
            capture_output=True,
            timeout=_SMARTCTL_TIMEOUT,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _evaluate(data: dict, name: str) -> DriveHealth:
    """Turn raw smartctl JSON into a DriveHealth verdict.

    Checks run most-severe first, so a critical condition is never masked by
    a lower-severity one found earlier (e.g. a critical temperature must win
    over a merely-logged media error).
    """
    temp = (data.get("temperature") or {}).get("current")
    thresholds = data.get("nvme_composite_temperature_threshold") or {}
    # thresholds keys may be present but explicitly null in the JSON, so `or`
    # (not just .get's default) is needed to fall back correctly.
    warn_c = thresholds.get("warning") or _DEFAULT_WARN_C
    crit_c = thresholds.get("critical") or _DEFAULT_CRIT_C

    log = data.get("nvme_smart_health_information_log") or {}
    health_passed = (data.get("smart_status") or {}).get("passed")
    critical_warning = log.get("critical_warning", 0)
    wear_pct = log.get("percentage_used")
    spare_pct = log.get("available_spare")
    media_errors = log.get("media_errors")

    status, reason = "ok", "Healthy."
    if health_passed is False or critical_warning not in (0, None):
        status, reason = "critical", "The drive reports a critical warning."
    elif temp is not None and temp >= crit_c:
        status, reason = "critical", f"Temperature {temp}C is at or above the critical limit."
    elif media_errors is not None and media_errors > 0:
        status, reason = "warn", f"{media_errors} data integrity error(s) logged."
    elif temp is not None and temp >= warn_c:
        status, reason = "warn", f"Temperature {temp}C is at or above the safe threshold."
    elif wear_pct is not None and wear_pct >= 90:
        status, reason = "warn", f"Drive wear is at {wear_pct}%."
    elif temp is None:
        status, reason = "unknown", "Temperature not reported by this drive."

    return DriveHealth(
        name, True, status, temp, warn_c, crit_c, wear_pct, spare_pct, media_errors, reason
    )


class HealthCollector:
    def __init__(self, drives=DRIVES) -> None:
        self._drives = list(drives)
        self._keys: dict[str, str | None] = {}
        self._cache: dict[str, DriveHealth] = {}
        self._last_run: float | None = None

    def _resolve(self, name: str, mountpoint: str) -> str | None:
        key = self._keys.get(name, "?")
        if key == "?" or key is None:
            key = physical_io_key(mountpoint)
            self._keys[name] = key
        return key

    def sample(self, force: bool = False) -> dict[str, DriveHealth]:
        """Return per-drive health, re-checking smartctl at most every REFRESH_SECONDS."""
        now = time.monotonic()
        due = self._last_run is None or (now - self._last_run) >= REFRESH_SECONDS
        if not due and not force:
            return self._cache

        self._last_run = now
        if not smartctl_available():
            for name, _ in self._drives:
                self._cache[name] = DriveHealth(
                    name, False, reason="smartctl is not installed."
                )
            return self._cache

        for name, mountpoint in self._drives:
            key = self._resolve(name, mountpoint)
            if key is None:
                self._cache[name] = DriveHealth(name, False, reason="Drive not connected.")
                continue
            data = _read_smart(f"/dev/{key}")
            if not data or "temperature" not in data and "nvme_smart_health_information_log" not in data:
                self._keys[name] = None  # allow re-resolve if it comes back
                self._cache[name] = DriveHealth(
                    name, False, reason="Health data unavailable for this drive."
                )
                continue
            self._cache[name] = _evaluate(data, name)

        return self._cache

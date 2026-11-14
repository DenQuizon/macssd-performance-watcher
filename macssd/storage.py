"""Shared storage-capacity snapshot helpers for GUI and menu bar views."""

from __future__ import annotations

import os
import plistlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

import psutil

from macssd.collectors.disk import discover_drives

_PROJECT_DIR = Path(__file__).resolve().parent.parent
_LAUNCH_AGENT_LABEL = "com.macssd.menubar"
_LAUNCH_AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCH_AGENT_LABEL}.plist"


@dataclass
class StorageUsage:
    available: bool
    used_gb: float = 0.0
    total_gb: float = 0.0


def _volume_capacity(mountpoint: str) -> tuple[float, float] | None:
    """(total_gb, available_gb) the way System Settings > Storage reports it.

    "Available for important usage" counts purgeable space (local snapshots,
    caches macOS can reclaim) as free. psutil/df only see raw free blocks, so
    they report far more "used" than Settings does.
    """
    try:
        from Foundation import NSURL

        url = NSURL.fileURLWithPath_(mountpoint)
        keys = ["NSURLVolumeTotalCapacityKey", "NSURLVolumeAvailableCapacityForImportantUsageKey"]
        values, _err = url.resourceValuesForKeys_error_(keys, None)
        if not values:
            return None
        total = float(values["NSURLVolumeTotalCapacityKey"])
        avail = float(values["NSURLVolumeAvailableCapacityForImportantUsageKey"])
    except Exception:  # noqa: BLE001 - fall back to psutil below
        return None
    if total <= 0 or avail < 0:
        return None
    return total / 1_000_000_000, min(avail, total) / 1_000_000_000


def read_storage() -> dict[str, StorageUsage]:
    """Used/total GB per drive (used = total - available, as in System Settings)."""
    result = {}
    for drive in discover_drives():
        name, mountpoint = drive.name, drive.mountpoint
        if mountpoint is None:
            result[name] = StorageUsage(False)
            continue
        cap = _volume_capacity(mountpoint)
        if cap is not None:
            total_gb, avail_gb = cap
            result[name] = StorageUsage(True, total_gb - avail_gb, total_gb)
            continue
        try:
            usage = psutil.disk_usage(mountpoint)
            result[name] = StorageUsage(
                True,
                (usage.total - usage.free) / 1_000_000_000,
                usage.total / 1_000_000_000,
            )
        except OSError:
            result[name] = StorageUsage(False)
    return result


def _launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def is_login_item_enabled() -> bool:
    """The LaunchAgent file's presence is the source of truth."""
    return _LAUNCH_AGENT_PATH.exists()


def enable_login_item() -> tuple[bool, str]:
    python = _PROJECT_DIR / ".venv" / "bin" / "python"
    plist = {
        "Label": _LAUNCH_AGENT_LABEL,
        "ProgramArguments": [str(python), "-m", "macssd.menubar"],
        "WorkingDirectory": str(_PROJECT_DIR),
        "RunAtLoad": True,
        "KeepAlive": False,
    }
    _LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LAUNCH_AGENT_PATH, "wb") as f:
        plistlib.dump(plist, f)
    # bootstrap/bootout (not the legacy load/unload) is the reliable, clearly
    # error-reporting way to register a LaunchAgent on modern macOS.
    result = subprocess.run(
        ["launchctl", "bootstrap", _launchctl_domain(), str(_LAUNCH_AGENT_PATH)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _LAUNCH_AGENT_PATH.unlink(missing_ok=True)  # don't claim "enabled" if it wasn't
        return False, result.stderr.strip()
    return True, ""


def disable_login_item() -> None:
    if _LAUNCH_AGENT_PATH.exists():
        subprocess.run(
            ["launchctl", "bootout", f"{_launchctl_domain()}/{_LAUNCH_AGENT_LABEL}"],
            capture_output=True,
        )
        _LAUNCH_AGENT_PATH.unlink()

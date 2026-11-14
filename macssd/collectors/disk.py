"""Per-drive disk read/write speed via psutil counter deltas.

macOS reports IO counters per physical disk (disk0, disk9, ...). We map each
drive we care about (by its mount point) to that physical disk using diskutil,
then turn the byte counters into MB/s by dividing the change by the elapsed time
between samples.
"""

from __future__ import annotations

import os
import plistlib
import re
import subprocess
import time
from collections import deque
from dataclasses import dataclass

import psutil

_MB = 1_000_000  # storage speeds are quoted in decimal megabytes
_GB = 1_000_000_000
_DISCOVERY_REFRESH_SECONDS = 30.0
_drive_cache: tuple[float, list[DriveTarget]] | None = None

@dataclass
class DriveSpeed:
    name: str
    available: bool
    read_mbs: float = 0.0
    write_mbs: float = 0.0
    free_gb: float = 0.0
    total_gb: float = 0.0


@dataclass(frozen=True)
class DriveTarget:
    """A physical SSD and one of its mounted volumes, if it has one."""

    name: str
    device: str
    mountpoint: str | None


def _whole_disk(device: str) -> str:
    """'disk9s2' -> 'disk9'."""
    match = re.match(r"(disk\d+)", device)
    return match.group(1) if match else device


def physical_io_key(mountpoint: str) -> str | None:
    """Return the psutil perdisk key (e.g. 'disk0') backing a mount point, or None."""
    try:
        out = subprocess.run(
            ["diskutil", "info", "-plist", mountpoint],
            capture_output=True,
            timeout=5,
            check=True,
        ).stdout
        info = plistlib.loads(out)
    except (subprocess.SubprocessError, OSError, plistlib.InvalidFileException):
        return None
    stores = info.get("APFSPhysicalStores")
    if stores:
        return _whole_disk(stores[0].get("APFSPhysicalStore", ""))
    parent = info.get("ParentWholeDisk") or info.get("DeviceIdentifier")
    return _whole_disk(parent) if parent else None


def _physical_disk_ids() -> list[str]:
    """Return macOS physical disk identifiers, such as ``disk0``.

    ``diskutil list`` is the source of truth here.  Volume names and paths are
    user-configurable and therefore unsuitable for deciding what is internal
    versus external (especially when the Mac is booted from an external SSD).
    """
    try:
        out = subprocess.run(
            ["diskutil", "list", "-plist", "physical"],
            capture_output=True,
            timeout=5,
            check=True,
        ).stdout
        disks = plistlib.loads(out).get("AllDisks", [])
    except (subprocess.SubprocessError, OSError, plistlib.InvalidFileException):
        return []
    return [disk for disk in disks if re.fullmatch(r"disk\d+", disk)]


def _disk_info(device: str) -> dict:
    try:
        out = subprocess.run(
            ["diskutil", "info", "-plist", f"/dev/{device}"],
            capture_output=True,
            timeout=5,
            check=True,
        ).stdout
        return plistlib.loads(out)
    except (subprocess.SubprocessError, OSError, plistlib.InvalidFileException):
        return {}


def discover_drives() -> list[DriveTarget]:
    """Discover one internal and one external mounted SSD at runtime.

    A mount is matched to its physical backing disk, so an external boot disk
    is correctly called external even though it is mounted at ``/``.
    """
    global _drive_cache
    now = time.monotonic()
    if _drive_cache and now - _drive_cache[0] < _DISCOVERY_REFRESH_SECONDS:
        return list(_drive_cache[1])

    # A physical disk can have many APFS helper volumes.  Retain the largest
    # mounted volume for storage usage, rather than an early tiny system mount
    # such as /System/Volumes/xarts.
    mounted_by_disk: dict[str, tuple[str, int]] = {}
    for part in psutil.disk_partitions(all=False):
        key = physical_io_key(part.mountpoint)
        if not key:
            continue
        try:
            total_bytes = psutil.disk_usage(part.mountpoint).total
        except OSError:
            total_bytes = 0
        current = mounted_by_disk.get(key)
        if current is None or total_bytes > current[1]:
            mounted_by_disk[key] = (part.mountpoint, total_bytes)

    candidates: list[tuple[bool, str, str | None]] = []
    for device in _physical_disk_ids():
        info = _disk_info(device)
        if not info.get("SolidState"):
            continue
        mount = mounted_by_disk.get(device)
        candidates.append((bool(info.get("Internal")), device, mount[0] if mount else None))

    result: list[DriveTarget] = []
    for internal, name in (
        (True, "Internal SSD"),
        (False, "External SSD"),
    ):
        match = next(
            ((device, mountpoint) for is_internal, device, mountpoint in candidates if is_internal == internal),
            None,
        )
        if match:
            device, mountpoint = match
            result.append(DriveTarget(name, device, mountpoint))
    _drive_cache = (now, result)
    return result


class DiskMonitor:
    """Stateful sampler: call sample() on each refresh to get per-drive speeds."""

    def __init__(self, drives: list[DriveTarget] | None = None, history: int = 12, reresolve_every: int = 15) -> None:
        self._drives = list(drives) if drives is not None else discover_drives()
        self._reresolve_every = reresolve_every
        self._keys: dict[str, str | None] = {}
        self._ticks: dict[str, int] = {}
        # prev is keyed by drive name and tagged with the disk id it was read
        # from: (read_bytes, write_bytes, io_key). A different tag means the drive
        # was replugged / reassigned, so we restart at zero instead of spiking.
        self._prev: dict[str, tuple[int, int, str]] = {}
        self._prev_t: float | None = None
        self.read_hist = {drive.name: deque(maxlen=history) for drive in self._drives}
        self.write_hist = {drive.name: deque(maxlen=history) for drive in self._drives}

    def _resolve_key(self, name: str, device: str, mounted: bool) -> str | None:
        """Cached disk-id lookup, re-resolved periodically to catch reassignment."""
        if not mounted:
            self._keys[name] = None
            self._ticks[name] = 0
            return None
        key = self._keys.get(name)
        self._ticks[name] = self._ticks.get(name, 0) + 1
        if key is None or self._ticks[name] > self._reresolve_every:
            key = device
            self._keys[name] = key
            self._ticks[name] = 0
        return key

    def sample(self) -> dict[str, DriveSpeed]:
        io = psutil.disk_io_counters(perdisk=True)
        now = time.monotonic()
        elapsed = (now - self._prev_t) if self._prev_t is not None else None
        self._prev_t = now

        result: dict[str, DriveSpeed] = {}
        for drive in self._drives:
            name, mountpoint = drive.name, drive.mountpoint
            mounted = mountpoint is not None and os.path.ismount(mountpoint)
            key = self._resolve_key(name, drive.device, mounted)
            counters = io.get(key) if key else None

            if not mounted or counters is None:
                self._prev.pop(name, None)  # clean restart when it returns
                self.read_hist[name].append(0.0)
                self.write_hist[name].append(0.0)
                result[name] = DriveSpeed(name, available=False)
                continue

            read_b, write_b = counters.read_bytes, counters.write_bytes
            prev = self._prev.get(name)
            self._prev[name] = (read_b, write_b, key)

            # Only measure a delta against the same disk id over a real interval.
            if prev is None or prev[2] != key or not elapsed:
                read_mbs = write_mbs = 0.0
            else:
                read_mbs = max(0.0, (read_b - prev[0]) / elapsed / _MB)
                write_mbs = max(0.0, (write_b - prev[1]) / elapsed / _MB)

            self.read_hist[name].append(read_mbs)
            self.write_hist[name].append(write_mbs)

            free_gb = total_gb = 0.0
            try:
                usage = psutil.disk_usage(mountpoint)
                free_gb, total_gb = usage.free / _GB, usage.total / _GB
            except OSError:
                pass

            result[name] = DriveSpeed(
                name, True, read_mbs, write_mbs, free_gb, total_gb
            )
        return result

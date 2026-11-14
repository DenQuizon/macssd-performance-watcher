"""Regression tests for runtime SSD discovery and SMART access fallback."""

import json
import sys
from types import SimpleNamespace

from macssd.collectors import disk, health


def test_discovery_uses_physical_metadata_not_volume_names() -> None:
    original_cache = disk._drive_cache
    original_partitions = disk.psutil.disk_partitions
    original_key = disk.physical_io_key
    original_ids = disk._physical_disk_ids
    original_info = disk._disk_info
    try:
        disk._drive_cache = None
        disk.psutil.disk_partitions = lambda all=False: [
            SimpleNamespace(mountpoint="/"),
            SimpleNamespace(mountpoint="/Volumes/Internal"),
        ]
        disk.physical_io_key = lambda mount: {"/": "disk8", "/Volumes/Internal": "disk0"}.get(mount)
        disk._physical_disk_ids = lambda: ["disk0", "disk4", "disk8"]
        disk._disk_info = lambda device: {
            "disk0": {"SolidState": True, "Internal": True},
            "disk4": {"SolidState": False, "Internal": False},
            "disk8": {"SolidState": True, "Internal": False},
        }[device]

        drives = disk.discover_drives()
        assert drives == [
            disk.DriveTarget("Internal SSD", "disk0", "/Volumes/Internal"),
            disk.DriveTarget("External SSD", "disk8", "/"),
        ]
    finally:
        disk._drive_cache = original_cache
        disk.psutil.disk_partitions = original_partitions
        disk.physical_io_key = original_key
        disk._physical_disk_ids = original_ids
        disk._disk_info = original_info


def test_smart_tries_without_sudo_before_falling_back() -> None:
    original_path = health._smartctl_path
    original_run = health.subprocess.run
    calls = []
    try:
        health._smartctl_path = lambda: "/opt/homebrew/bin/smartctl"

        def run(args, **_kwargs):
            calls.append(args)
            return SimpleNamespace(stdout=json.dumps({"temperature": {"current": 42}}).encode())

        health.subprocess.run = run
        assert health._read_smart("/dev/disk8") == {"temperature": {"current": 42}}
        assert calls == [["/opt/homebrew/bin/smartctl", "-a", "-j", "/dev/disk8"]]
    finally:
        health._smartctl_path = original_path
        health.subprocess.run = original_run


try:
    test_discovery_uses_physical_metadata_not_volume_names()
    test_smart_tries_without_sudo_before_falling_back()
except AssertionError as exc:
    print(f"FAIL {exc}")
    sys.exit(1)

print("ALL PASS")

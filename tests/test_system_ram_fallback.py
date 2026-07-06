"""Regression test for a real macOS/psutil issue found while testing the menu
bar app: psutil.virtual_memory() intermittently raises RuntimeError
("host_statistics64 syscall failed") on this machine's macOS build, in bursts
of several consecutive calls (measured ~40% failure rate over 30 calls, not
isolated one-offs). system.read() must fall back to the last known-good RAM
reading rather than crashing every caller (both the TUI and the menu bar
depend on this collector).

Run with: "./.venv/bin/python" -m tests.test_system_ram_fallback
"""

import sys
from unittest.mock import patch

import macssd.collectors.system as sysmod

try:
    sysmod.prime()
    good = sysmod.read()
    assert good.ram_percent >= 0, "a normal read should succeed"

    def failing(*_a, **_k):
        raise RuntimeError(
            "host_statistics64(HOST_VM_INFO64) syscall failed: (ipc/mig) array not large enough"
        )

    with patch("psutil.virtual_memory", side_effect=failing):
        for i in range(5):
            during = sysmod.read()
            assert during.ram_percent == good.ram_percent, (
                f"call {i}: RAM should fall back to the last good value during a failing burst"
            )
            assert during.cpu_percent >= 0, "CPU reading must be unaffected by the RAM failure"

    after = sysmod.read()
    assert after.ram_percent >= 0, "a real read should succeed again once the burst ends"

    print("ALL PASS")
except AssertionError as e:
    print(f"FAIL {e}")
    sys.exit(1)

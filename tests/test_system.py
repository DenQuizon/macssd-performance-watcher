"""Boundary tests for the plain-English CPU/RAM labels and the collector.

Plain Python (no pytest needed): run with
    "./.venv/bin/python" -m tests.test_system
Exits non-zero on the first failed assertion.
"""

import sys

from macssd.collectors import system


def check_cpu() -> None:
    assert system.describe_cpu(0) == "light load", "0% should be light load"
    assert system.describe_cpu(24.9) == "light load", "24.9% is still light load"
    assert system.describe_cpu(25) == "moderate load", "25% crosses into moderate"
    assert system.describe_cpu(59.9) == "moderate load", "59.9% is still moderate"
    assert system.describe_cpu(60) == "working hard", "60% crosses into working hard"
    assert system.describe_cpu(84.9) == "working hard", "84.9% is still working hard"
    assert system.describe_cpu(85) == "very busy", "85% crosses into very busy"
    assert system.describe_cpu(100) == "very busy", "100% is very busy"


def check_ram() -> None:
    assert system.describe_ram(0) == "plenty free", "0% should be plenty free"
    assert system.describe_ram(59.9) == "plenty free", "59.9% is still plenty free"
    assert system.describe_ram(60) == "getting full", "60% crosses into getting full"
    assert system.describe_ram(79.9) == "getting full", "79.9% is still getting full"
    assert system.describe_ram(80) == "nearly full", "80% crosses into nearly full"
    assert system.describe_ram(100) == "nearly full", "100% is nearly full"


def check_read_is_consistent() -> None:
    system.prime()
    stats = system.read()
    assert stats.ram_total_gb > 0, "total RAM must be positive"
    assert 0 <= stats.ram_percent <= 100, "RAM percent must be 0-100"
    # the GB shown and the percentage must tell the same story
    derived = stats.ram_used_gb / stats.ram_total_gb * 100
    assert abs(derived - stats.ram_percent) < 1.5, (
        f"GB and percent disagree: {derived:.0f}% vs {stats.ram_percent:.0f}%"
    )
    assert stats.cpu_percent >= 0, "CPU percent must be non-negative"


def main() -> None:
    for check in (check_cpu, check_ram, check_read_is_consistent):
        try:
            check()
        except AssertionError as exc:
            print(f"FAIL ({check.__name__}): {exc}")
            sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()

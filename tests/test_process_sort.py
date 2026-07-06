"""Tests for ProcessCollector.top() sort ordering.

Authored by agy (Gemini 3.5 Flash) as the test role in the orchestration;
integrated by Claude. Run with:
    "./.venv/bin/python" -m tests.test_process_sort
"""

import sys

from macssd.collectors.processes import ProcInfo, ProcessCollector

try:
    collector = ProcessCollector()
    p1 = ProcInfo(1, "proc1", 10.0, 100.0, "user", 50.0, 50.0)
    p2 = ProcInfo(2, "proc2", 80.0, 50.0, "user", 10.0, 10.0)
    p3 = ProcInfo(3, "proc3", 5.0, 500.0, "user", 1.0, 1.0)

    collector._last = [p1, p2, p3]

    res_cpu = collector.top("cpu", 3)
    assert res_cpu[0] == p2, "CPU sort highest first"

    res_mem = collector.top("mem", 3)
    assert res_mem[0] == p3, "Mem sort highest first"

    res_disk = collector.top("disk", 3)
    assert res_disk[0] == p1, "Disk sort highest first"

    res_limit = collector.top("cpu", 1)
    assert len(res_limit) == 1, "Limit returns one item"
except AssertionError as e:
    print(f"FAIL {e}")
    sys.exit(1)

print("ALL PASS")

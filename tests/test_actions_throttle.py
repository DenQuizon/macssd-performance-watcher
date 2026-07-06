"""Tests for the throttle_process() action (green-tier: slows a process
down via taskpolicy -b, never kills it).

Authored by agy (Gemini 3.5 Flash, Medium) as the test role in the
orchestration; integrated by Claude. Run with:
    "./.venv/bin/python" -m tests.test_actions_throttle
"""

import subprocess
import sys
import time

import psutil

from macssd.actions import throttle_process

try:
    p1 = subprocess.Popen(["sleep", "30"])
    time.sleep(1 / 3)
    try:
        proc1 = psutil.Process(p1.pid)
        create_time1 = proc1.create_time()
        success1, msg1 = throttle_process(p1.pid, create_time1)
        assert success1 is True, f"Case 1 throttle failed: {msg1}"
        assert proc1.is_running(), "Case 1 process is not running"
    finally:
        p1.terminate()
        p1.wait()

    p2 = subprocess.Popen(["sleep", "30"])
    time.sleep(1 / 3)
    try:
        proc2 = psutil.Process(p2.pid)
        create_time2 = proc2.create_time()
        wrong_create_time = create_time2 - 999
        success2, msg2 = throttle_process(p2.pid, wrong_create_time)
        assert success2 is False, "Case 2 mismatch create time was not refused"
        assert proc2.is_running(), "Case 2 process was terminated or not running"
    finally:
        p2.terminate()
        p2.wait()

    success3, msg3 = throttle_process(999999, 0)
    assert success3 is False, "Case 3 non-existent PID was not refused"

    print("ALL PASS")

except AssertionError as e:
    print(f"FAIL {e}")
    sys.exit(1)

"""Regression test for a Codex-flagged HIGH-severity bug: the safety tier and
impact preview are computed when the user opens the close-process dialog, but
the process could exit and macOS could reuse its pid for a different process
before they confirm. close_process() must refuse to act unless the process's
create_time still matches what was captured when the preview opened — proving
this closes the window rather than trusting a pid that may no longer mean
what it did a moment ago.

Run with: "./.venv/bin/python" -m tests.test_actions_pid_reuse
"""

import subprocess
import sys
import time

import psutil

from macssd.actions import close_process

try:
    # Correct identity: closing should succeed.
    good = subprocess.Popen(["sleep", "30"])
    time.sleep(0.3)
    real_ctime = psutil.Process(good.pid).create_time()
    ok, msg = close_process(good.pid, real_ctime)
    assert ok, f"a matching create_time should be allowed to close: {msg}"
    good.wait(timeout=2)
    assert good.returncode is not None, "process should have actually terminated"

    # Mismatched identity (simulates a reused pid): closing must be refused,
    # and the real, still-running process must be left completely untouched.
    stale = subprocess.Popen(["sleep", "30"])
    time.sleep(0.3)
    wrong_ctime = psutil.Process(stale.pid).create_time() - 999
    ok, msg = close_process(stale.pid, wrong_ctime)
    assert not ok, "a mismatched create_time must never be allowed to close"
    assert "changed" in msg.lower(), "the refusal reason should explain why"
    assert psutil.Process(stale.pid).is_running(), (
        "the real process must be untouched when identity verification fails"
    )
    stale.terminate()
    stale.wait(timeout=2)

    print("ALL PASS")
except AssertionError as e:
    print(f"FAIL {e}")
    sys.exit(1)

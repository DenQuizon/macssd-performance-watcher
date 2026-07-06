"""Process-closing action with a safety check.

Matches the safety model locked at project design time: red-tier processes
are refused outright (the app never even asks), yellow-tier processes always
require the user's explicit confirmation first. There is no green (automatic)
tier for closing a process in Phase 1 — that only applies to reversible
actions like throttling, which come later.
"""

from __future__ import annotations

import subprocess

import psutil

from macssd.collectors.processes import ProcInfo


def classify_kill_safety(proc: ProcInfo, own_pid: int) -> tuple[str, str]:
    """Return (tier, reason) for closing this process. tier is "red" or "yellow".

    The SYSTEM tag comes from a keyword list (see collectors/processes.py) and
    won't catch every privileged daemon by name, so some system processes can
    land in yellow tier. This is an accepted gap: those processes run as
    root/another user, so terminate() hits macOS's own AccessDenied and
    close_process() reports it as a failure rather than actually closing
    anything. The OS permission model is the real backstop here, not the tag.
    """
    if proc.pid == own_pid:
        return "red", "This is MACSSD_Performance Watcher itself."
    if proc.pid == 1:
        return "red", "This is launchd, the Mac's core process manager."
    if proc.tag == "SYSTEM":
        return "red", "This is a macOS system process — closing it could destabilise the Mac."
    return "yellow", "Closing this will end the program. Unsaved work in it will be lost."


def close_process(pid: int, expected_create_time: float) -> tuple[bool, str]:
    """Ask the process to close gracefully (SIGTERM). Returns (success, message).

    expected_create_time must match the process's actual start time. The
    safety tier and impact preview are computed when the user opens the
    dialog, but the process could exit and macOS could reuse its pid for a
    completely different (possibly red-tier) process before they confirm —
    re-checking identity here closes that window instead of trusting a pid
    that may no longer mean what it did a moment ago.
    """
    try:
        proc = psutil.Process(pid)
        # psutil's create_time() is stable to the microsecond for a given
        # process (verified: repeated reads return a bit-identical value), so
        # a tight tolerance still safely absorbs float noise while closing
        # the reused-pid window a looser tolerance would leave open.
        if abs(proc.create_time() - expected_create_time) > 0.01:
            return False, "That process has changed since you selected it — nothing was closed."
        name = proc.name()
        proc.terminate()
    except psutil.NoSuchProcess:
        return False, "That process is already gone."
    except psutil.AccessDenied:
        return False, "Permission denied — this process belongs to another user."
    except OSError as exc:
        return False, f"Could not close it: {exc}"
    return True, f"Asked {name} (pid {pid}) to close."


def throttle_process(pid: int, expected_create_time: float) -> tuple[bool, str]:
    """Move a process to background QoS (taskpolicy -b) so macOS deprioritises
    its CPU and disk I/O. Reversible and loses no data — this is the green-tier
    action the automatic watcher uses; it never kills anything on its own.

    expected_create_time is verified for the same reason as close_process():
    the process could have exited and had its pid reused between when it was
    identified as the cause and when this runs.
    """
    try:
        proc = psutil.Process(pid)
        if abs(proc.create_time() - expected_create_time) > 0.01:
            return False, "That process has changed since it was identified — nothing was throttled."
        name = proc.name()
    except psutil.NoSuchProcess:
        return False, "That process is already gone."
    except psutil.AccessDenied:
        return False, "Permission denied — this process belongs to another user."

    try:
        result = subprocess.run(
            ["/usr/sbin/taskpolicy", "-b", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return False, "taskpolicy did not respond in time."
    except OSError as exc:
        return False, f"Could not throttle it: {exc}"
    if result.returncode != 0:
        detail = result.stderr.strip() or f"taskpolicy exited with code {result.returncode}"
        return False, f"Could not throttle it: {detail}"
    return True, f"Throttled {name} (pid {pid}) to background priority."

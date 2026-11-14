"""MACSSD_Performance Watcher — periodic background check.

Meant to be triggered every 30 minutes by a launchd LaunchAgent, not run as a
long-lived loop itself. Always sends a compact heartbeat to Telegram (drive
temps + Mac thermal state only); on critical drive temperature it throttles
the top CPU consumer and escalates to a 5-minute shutdown warning.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

import psutil

from macssd import action_log, telegram
from macssd.actions import throttle_process
from macssd.collectors.health import HealthCollector
from macssd.collectors.thermal import cpu_temp_c, read as thermal_read
from macssd.severity import THERMAL_SEVERITY, cpu_temp_severity

_LOG_PATH = Path.home() / ".macssd" / "watcher.log"
_SHUTDOWN_WAIT_SECONDS = 300
_HEARTBEAT_INTERVAL_SECONDS = 1800  # must match the launchd StartCalendarInterval spacing

_SEVERITY_RANK = {"ok": 0, "unknown": 0, "warn": 1, "critical": 2}
_SEVERITY_EMOJI = {"ok": "✅", "warn": "⚠️", "critical": "🔥", "unknown": "❔"}


def _worst(severities: list[str]) -> str:
    return max(severities, key=lambda s: _SEVERITY_RANK.get(s, 0), default="ok")


def _throttle_top_process() -> str:
    try:
        candidates = list(psutil.process_iter(["pid", "name"]))
    except (psutil.Error, PermissionError, OSError):
        return "Could not list processes to find one to throttle."

    # cpu_percent(interval=None) always returns 0.0 on a process's first
    # call — it measures against the *previous* call, not a moment in time.
    # Prime every candidate, wait briefly, then take a real second reading.
    for proc in candidates:
        try:
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    time.sleep(0.2)

    top_proc = None
    top_cpu = -1.0
    for proc in candidates:
        try:
            cpu = proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        if cpu > top_cpu:
            top_cpu = cpu
            top_proc = proc
    if top_proc is None:
        return "No process found to throttle."
    try:
        pid = top_proc.pid
        name = top_proc.name()
        create_time = top_proc.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return "Top process vanished before it could be throttled."
    ok, detail = throttle_process(pid, create_time)
    message = f"Throttle {name} (pid {pid}): {detail}" if not ok else detail
    if ok:
        action_log.record(message)
    return message


def _shut_down_if_no_reply(after_update_id: int) -> None:
    time.sleep(_SHUTDOWN_WAIT_SECONDS)
    if telegram.has_new_reply(after_update_id):
        logging.info("Reply received before shutdown deadline — standing down.")
        return
    try:
        # -n: fail instead of hanging on a password prompt — launchd runs
        # this with no TTY, so an interactive sudo prompt would just hang
        # forever rather than warn anyone. Requires a scoped NOPASSWD
        # sudoers entry for this exact command (via visudo) to actually work
        # unattended; without it this will fail every time and only log.
        result = subprocess.run(
            ["sudo", "-n", "/sbin/shutdown", "-h", "now"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logging.error(
                "Shutdown command failed (rc=%s): %s",
                result.returncode,
                result.stderr.strip() or "no stderr output",
            )
    except (subprocess.SubprocessError, OSError) as exc:
        logging.error("Failed to run shutdown: %s", exc)


def run_once() -> None:
    health_results = HealthCollector().sample(force=True)
    therm = thermal_read()
    cpu_temp = cpu_temp_c(force=True)

    # DriveHealth.status is already a severity word ("ok"/"warn"/"critical"/
    # "unknown") — THERMAL_SEVERITY's keys are SMART condition names, not
    # this, so mapping through it here would silently drop "warn".
    drive_sevs = {
        name: (drive.status if drive.status in ("ok", "warn", "critical") else "ok")
        for name, drive in health_results.items()
    }
    mac_sev = THERMAL_SEVERITY.get(therm.state, "unknown") if therm.available else "unknown"
    cpu_sev = cpu_temp_severity(cpu_temp)

    overall = _worst([*drive_sevs.values(), mac_sev, cpu_sev])

    lines = [f"{_SEVERITY_EMOJI[overall]} MACSSD heartbeat — {overall.upper()}"]
    if cpu_temp is not None:
        lines.append(f"{_SEVERITY_EMOJI[cpu_sev]} CPU: {cpu_temp:.0f}°C")
    for name, drive in health_results.items():
        temp = f"{drive.temp_c}°C" if drive.temp_c is not None else "n/a"
        sev = drive_sevs[name]
        lines.append(f"{_SEVERITY_EMOJI[sev]} {name}: {temp}")
    if therm.available:
        lines.append(f"{_SEVERITY_EMOJI[mac_sev]} Mac thermal: {therm.state}")

    if overall == "critical":
        _throttle_top_process()  # logs to action_log itself; picked up below

    recent_actions = action_log.recent(_HEARTBEAT_INTERVAL_SECONDS)
    if recent_actions:
        lines.append("🛠️ Auto-actions taken:")
        lines.extend(f"  {a}" for a in recent_actions)

    telegram.send_message("\n".join(lines))

    critical_drive = any(sev == "critical" for sev in drive_sevs.values())
    if critical_drive:
        after_update_id = telegram.latest_update_id()
        telegram.send_message(
            "WARNING: a drive is at a critical temperature. This Mac will shut "
            "down automatically in 5 minutes unless you reply to this message."
        )
        _shut_down_if_no_reply(after_update_id)


def main() -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=_LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        run_once()
    except Exception:
        logging.exception("watcher run_once() failed")


if __name__ == "__main__":
    main()

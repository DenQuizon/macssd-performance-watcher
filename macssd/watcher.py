"""MACSSD_Performance Watcher — hourly background check.

Meant to be triggered once per hour by a launchd LaunchAgent, not run as a
long-lived loop itself. Always sends a compact heartbeat to Telegram; on
critical CPU/RAM/storage severity it throttles the top CPU consumer; on
critical drive temperature it escalates to a 5-minute shutdown warning.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

import psutil

from macssd import telegram
from macssd.actions import throttle_process
from macssd.collectors import system
from macssd.collectors.health import HealthCollector
from macssd.dashboard_image import render_dashboard_image
from macssd.severity import cpu_severity, ram_severity, storage_severity
from macssd.storage import read_storage

_LOG_PATH = Path.home() / ".macssd" / "watcher.log"
_SHUTDOWN_WAIT_SECONDS = 300

_SEVERITY_RANK = {"ok": 0, "unknown": 0, "warn": 1, "critical": 2}


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
    return f"Throttle {name} (pid {pid}): {detail}" if not ok else detail


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
    stats = system.read()
    cpu_sev = cpu_severity(stats.cpu_percent)
    ram_sev = ram_severity(stats.ram_percent)

    storage = read_storage()
    storage_sevs = {
        name: storage_severity(usage.used_gb, usage.total_gb) if usage.available else "ok"
        for name, usage in storage.items()
    }

    health_results = HealthCollector().sample(force=True)
    # DriveHealth.status is already a severity word ("ok"/"warn"/"critical"/
    # "unknown") — THERMAL_SEVERITY's keys are SMART condition names, not
    # this, so mapping through it here would silently drop "warn".
    thermal_sevs = {
        name: (drive.status if drive.status in ("ok", "warn", "critical") else "ok")
        for name, drive in health_results.items()
    }

    overall = _worst([cpu_sev, ram_sev, *storage_sevs.values(), *thermal_sevs.values()])

    lines = [
        f"MACSSD hourly heartbeat — {overall.upper()}",
        f"CPU {stats.cpu_percent:.0f}% ({cpu_sev})  RAM {stats.ram_percent:.0f}% ({ram_sev})",
    ]
    for name, drive in health_results.items():
        temp = f"{drive.temp_c}C" if drive.temp_c is not None else "n/a"
        lines.append(f"{name}: {temp}, {drive.status}")

    if overall == "critical":
        lines.append(_throttle_top_process())

    caption = "\n".join(lines)
    try:
        image_path = render_dashboard_image()
    except Exception:  # noqa: BLE001
        logging.exception("render_dashboard_image() failed — falling back to a text heartbeat")
        telegram.send_message(caption)
    else:
        ok, detail = telegram.send_photo(image_path, caption=caption)
        if not ok:
            logging.error("send_photo failed (%s) — falling back to a text heartbeat", detail)
            telegram.send_message(caption)

    critical_drive = any(sev == "critical" for sev in thermal_sevs.values())
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

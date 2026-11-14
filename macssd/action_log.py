"""Shared log of automatic actions (throttle/restore), so the periodic
Telegram heartbeat can report what the live menu bar app did on its own
between heartbeats, not just what the watcher itself triggered.

Plain newline-delimited "<unix_ts> <message>" text file — deliberately
simple, no locking needed since both writers only ever append.
"""

from __future__ import annotations

import time
from pathlib import Path

_LOG_PATH = Path.home() / ".macssd" / "actions.log"


def record(message: str) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a") as f:
        f.write(f"{time.time():.0f} {message}\n")


def recent(since_seconds: float) -> list[str]:
    """Messages recorded within the last `since_seconds`, oldest first."""
    try:
        lines = _LOG_PATH.read_text().splitlines()
    except OSError:
        return []
    cutoff = time.time() - since_seconds
    out = []
    for line in lines:
        ts_str, _, message = line.partition(" ")
        try:
            ts = float(ts_str)
        except ValueError:
            continue
        if ts >= cutoff:
            out.append(message)
    return out

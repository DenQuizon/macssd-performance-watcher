"""Telegram messaging for MACSSD alerts.

Reuses Den's existing bot token (~/.claude/channels/telegram/.env) — the same
one already used elsewhere in his setup — via a plain HTTPS POST to
Telegram's Bot API. No new bot, no AI/LLM calls, no extra dependency (uses
the standard library's urllib rather than adding `requests`).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

_ENV_PATH = Path.home() / ".claude" / "channels" / "telegram" / ".env"


def _read_env_var(name: str, env_path: Path = _ENV_PATH) -> str | None:
    """Read a single KEY=value out of the existing env file (never committed
    to this repo — chat ID and bot token both live there, not in source)."""
    try:
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{name}="):
                value = line.split("=", 1)[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]  # .env values are sometimes quoted
                return value
    except OSError:
        return None
    return None


CHAT_ID = _read_env_var("TELEGRAM_CHAT_ID") or ""


def load_token(env_path: Path = _ENV_PATH) -> str | None:
    """Read TELEGRAM_BOT_TOKEN out of the existing env file."""
    return _read_env_var("TELEGRAM_BOT_TOKEN", env_path)


def send_message(text: str, chat_id: str = CHAT_ID, token: str | None = None) -> tuple[bool, str]:
    """Send a plain-text message via the Telegram Bot API. Returns (ok, detail)."""
    token = token if token is not None else load_token()
    if not token:
        return False, "No Telegram bot token found."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            if resp.status == 200:
                return True, "sent"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return False, str(exc.reason)
    except Exception:  # noqa: BLE001
        # Catch-all so a transport hiccup never crashes the caller (this
        # runs unattended from a background watcher) and never risks
        # echoing the token-bearing url in an error message.
        return False, "Unexpected error sending the Telegram message."


def send_photo(
    photo_path: str,
    caption: str | None = None,
    chat_id: str = CHAT_ID,
    token: str | None = None,
) -> tuple[bool, str]:
    """Send a PNG/JPEG image via the Telegram Bot API's sendPhoto endpoint,
    hand-building the multipart body so no extra dependency (`requests`) is
    needed — same style as send_message above."""
    token = token if token is not None else load_token()
    if not token:
        return False, "No Telegram bot token found."

    try:
        with open(photo_path, "rb") as f:
            photo_data = f.read()
    except OSError as exc:
        return False, f"Could not read the image file: {exc}"

    boundary = f"boundary-{uuid.uuid4().hex}"

    def _field(name: str, value: str) -> bytes:
        return (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}'
        ).encode()

    parts = [_field("chat_id", str(chat_id))]
    if caption is not None:
        parts.append(_field("caption", caption))
    parts.append(
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="photo"; filename="dashboard.png"\r\n'
        f'Content-Type: image/png\r\n\r\n'.encode() + photo_data
    )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"\r\n".join(parts)

    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True, "sent"
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        return False, str(exc.reason)
    except Exception:  # noqa: BLE001
        return False, "Unexpected error sending the Telegram photo."


def latest_update_id(token: str | None = None) -> int:
    """The highest update_id currently pending. Used as a starting point so a
    later wait-for-reply check only sees messages sent AFTER this moment,
    not something Den already sent hours ago."""
    token = token if token is not None else load_token()
    if not token:
        return 0
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read())
    except Exception:  # noqa: BLE001
        return 0
    updates = body.get("result", [])
    return max((u["update_id"] for u in updates), default=0)


def has_new_reply(after_update_id: int, chat_id: str = CHAT_ID, token: str | None = None) -> bool:
    """True if a message from chat_id has arrived with update_id greater than
    after_update_id. Polling `getUpdates` with `offset` also acknowledges
    those updates to Telegram, so each check only ever sees new messages."""
    token = token if token is not None else load_token()
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = urllib.parse.urlencode({"offset": after_update_id + 1, "timeout": 0})
    try:
        with urllib.request.urlopen(f"{url}?{params}", timeout=10) as resp:
            body = json.loads(resp.read())
    except Exception:  # noqa: BLE001
        return False
    for update in body.get("result", []):
        msg = update.get("message", {})
        if str(msg.get("chat", {}).get("id")) == str(chat_id):
            return True
    return False

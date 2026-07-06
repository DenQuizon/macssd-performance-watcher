"""Tests for the Telegram messaging helper.

Base cases authored by agy (Gemini 3.5 Flash, Medium) as the test role in
the orchestration; integrated by Claude, with one extra case added to
verify a Codex-flagged fix (quoted .env values). Run with:
    "./.venv/bin/python" -m tests.test_telegram
"""

import sys
import tempfile
from pathlib import Path

from macssd.telegram import load_token, send_message

try:
    # Case one
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("TELEGRAM_BOT_TOKEN=abc123xyz\n")
        f_path = Path(f.name)
    try:
        val1 = load_token(f_path)
        assert val1 == "abc123xyz", "Case one: Expected token abc123xyz"
    finally:
        f_path.unlink(missing_ok=True)

    # Case two
    non_existent = Path(tempfile.gettempdir()) / "never_created_directory" / "token.txt"
    val2 = load_token(non_existent)
    assert val2 is None, "Case two: Expected None for non-existent file path"

    # Case three
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("SOME_OTHER_KEY=hello\n")
        f_path = Path(f.name)
    try:
        val3 = load_token(f_path)
        assert val3 is None, "Case three: Expected None for missing token key"
    finally:
        f_path.unlink(missing_ok=True)

    # Case four
    res = send_message("Test message", token="")
    assert res[0] is False, "Case four: Expected False for empty token in send_message"

    # Case five (Codex-flagged): quoted .env values must be unquoted.
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write('TELEGRAM_BOT_TOKEN="quoted-token-456"\n')
        f_path = Path(f.name)
    try:
        val5 = load_token(f_path)
        assert val5 == "quoted-token-456", (
            f"Case five: quoted value should be unquoted, got {val5!r}"
        )
    finally:
        f_path.unlink(missing_ok=True)

except AssertionError as e:
    print(f"FAIL {e}")
    sys.exit(1)

print("ALL PASS")

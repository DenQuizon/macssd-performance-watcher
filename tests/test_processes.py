"""Tests for the process tag classifier.

Authored by agy (Gemini 3.5 Flash) as the test role in the orchestration;
integrated by Claude. Run with:
    "./.venv/bin/python" -m tests.test_processes
"""

import sys

from macssd.collectors.processes import classify

try:
    for name in ["docker", "python", "node", "claude", "ollama", "cursor"]:
        for n in (name, name.lower(), name.upper()):
            res = classify(n)
            assert res == "AI/DEV", f"Expected AI/DEV for {n}, got {res}"

    for name in ["kernel_task", "mds_stores", "WindowServer", "launchd"]:
        for n in (name, name.lower(), name.upper()):
            res = classify(n)
            assert res == "SYSTEM", f"Expected SYSTEM for {n}, got {res}"

    for name in ["Safari", "Slack", "Spotify", "Finder"]:
        for n in (name, name.lower(), name.upper()):
            res = classify(n)
            assert res == "APP", f"Expected APP for {n}, got {res}"

except AssertionError as e:
    print(f"FAIL {e}")
    sys.exit(1)

print("ALL PASS")

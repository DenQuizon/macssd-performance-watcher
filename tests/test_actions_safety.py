"""Safety-tier tests for the process-close classifier.

Authored by agy (Gemini 3.5 Flash, High) as the test role in the
orchestration; integrated by Claude. Run with:
    "./.venv/bin/python" -m tests.test_actions_safety
"""

import sys

from macssd.actions import classify_kill_safety
from macssd.collectors.processes import ProcInfo

try:
    # Case 1: Caller process attempting to close itself
    proc1 = ProcInfo(1000, "mycompanion", 5, 50, "AI/DEV", 0, 0)
    tier1, reason1 = classify_kill_safety(proc1, 1000)
    assert tier1 == "red", "Caller process must be protected from killing itself to prevent sudden app crash"

    # Case 2: System launch daemon (PID 1)
    proc2 = ProcInfo(1, "launchd", 0, 10, "SYSTEM", 0, 0)
    tier2, reason2 = classify_kill_safety(proc2, 9999)
    assert tier2 == "red", "PID 1 is the operating system launch daemon and must never be terminated to avoid system panic"

    # Case 3: Process tagged as SYSTEM
    proc3 = ProcInfo(2000, "somedaemon", 1, 20, "SYSTEM", 0, 0)
    tier3, reason3 = classify_kill_safety(proc3, 9999)
    assert tier3 == "red", "SYSTEM-tagged processes are essential OS components and must remain active"

    # Case 4: Normal application (APP)
    proc4 = ProcInfo(3000, "GoogleChrome", 10, 500, "APP", 0, 0)
    tier4, reason4 = classify_kill_safety(proc4, 9999)
    assert tier4 == "yellow", "Normal user apps can be closed but require user confirmation to prevent data loss"

    # Case 5: Developer tool application (AI/DEV)
    proc5 = ProcInfo(4000, "docker", 10, 500, "AI/DEV", 0, 0)
    tier5, reason5 = classify_kill_safety(proc5, 9999)
    assert tier5 == "yellow", "Developer and AI workflow utilities can be closed but require confirmation to avoid breaking environment state"

except AssertionError as e:
    print(f"FAIL {e}")
    sys.exit(1)

print("ALL PASS")

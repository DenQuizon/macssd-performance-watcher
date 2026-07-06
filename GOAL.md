# GOAL — MACSSD_Performance Watcher

**Status:** awaiting Den's approval · **Created:** 2 July 2026
**Owner:** Den (Alden Quizon) · **Orchestrator:** Claude Code

---

## 1. Mission

A standalone terminal dashboard app (`macssd`) for Den's Mac mini M4 that:

1. Shows live CPU, RAM, and disk activity for **both** the internal Mac SSD and the external DensMate SSD.
2. Explains problems in **plain English** ("Your drive is getting warm because of Docker"), with a details key for the technical numbers.
3. Watches Den's AI/dev tools specifically: Claude, Codex, Gemini, Ollama, Docker, VS Code, Cursor, node, python, Chrome.
4. Offers **safe actions** — slow down, pause, or close the process causing the problem — with a plain-English preview of what will happen before anything destructive.
5. Confirms hardware is **fully working**: fan spinning, SSDs reporting healthy, no overheating/throttling. Green panel when all good, alert when not.
6. Escalates repeat problems: same issue 3+ times in 24h → offers a permanent background rule (launchd). Safe (green-tier) rules can be created automatically; anything that kills a process needs Den's one-time yes.
7. Runs from login as a quiet background watcher; alerts via macOS notifications **and** Telegram (chat ID configured via a local `.env` file, not committed) even when the dashboard is closed. Includes an optional daily "hardware healthy" heartbeat.

## 2. Success criteria

- [ ] `macssd` opens the dashboard in any terminal; runs with no Claude/IDE dependency
- [ ] Both SSDs monitored (activity + temperature, graceful "unknown" if the enclosure hides sensors)
- [ ] Hardware health panel: fan status, SSD SMART health, thermal state — all green on a healthy Mac
- [ ] An artificial disk-write storm is correctly identified with the causing process named in plain English within 2 refresh cycles
- [ ] Fan-failure simulation (temp high + fan 0 rpm) raises a red alert
- [ ] Safety tiers enforced: green = auto + notify, yellow = confirm first, red = refused always
- [ ] Background watcher survives reboot; Telegram + macOS alerts arrive with dashboard closed
- [ ] Every module reviewed by Codex before being marked done

## 3. Safety model

| Tier | Examples | Behaviour |
|---|---|---|
| 🟢 Green | slow a process down, pause Spotlight, send alert | acts automatically, tells Den after |
| 🟡 Yellow | close Docker/Claude/apps with unsaved work | always asks first, shows impact preview |
| 🔴 Red | anything the Mac needs to run (system processes) | refused, even from a saved rule |

## 4. Architecture

```
collectors/   raw metrics: psutil, proc_pid_rusage (ctypes), smartctl, SMC fan/thermal
analyzer/     rolling history, deltas, correlation, rule-based insight engine
knowledge/    per-process facts: safe-to-kill?, respawns?, better alternative?
actions/      kill, throttle (taskpolicy), Spotlight (mdutil), launchd rule generator
alerts/       macOS notifications, Telegram (via Hermes bridge)
ui/           Textual dashboard: panels, process table, insights, previews, details toggle
watcher/      headless background mode (LaunchAgent, starts at login)
```

UI never touches the OS directly. Explanation engine is rule-based — no AI needed at runtime.

## 5. Orchestration — who does what

| Role | Agent | How it's invoked |
|---|---|---|
| Plan, architecture, teaching, integration | **Claude Code** | this session — orchestrator |
| Phase 1 coding (step by step with Den) | **Claude Code** | direct |
| Code review after every step | **Codex CLI** | Claude runs it automatically via the Codex plugin/Bash after each module lands |
| Bulk/boilerplate builds in Phases 2–3 (from Claude's locked specs) | **AGY CLI** (Gemini) | Claude generates the spec prompt and runs `agy` via Bash; Claude reviews the output before merge |
| Whole-repo consistency sweep at each phase end | **AGY CLI** (large context) | same mechanism |
| Telegram alert channel + delivery testing | **Hermes** (Quen) | Claude messages Hermes via the hermes bridge; Hermes owns the Telegram bot the app will use |
| Final review + sign-off per phase | **Claude Code** | direct, then Den accepts |

Honest limits: Claude can genuinely drive Codex and AGY from the terminal (both are CLIs). The Antigravity **IDE** (GUI) stays manual — if a task needs it, Claude writes the exact prompt for Den to paste. If any CLI is missing or unauthenticated, Claude reports it and continues solo rather than faking it.

Loop per step: **Claude codes & explains → Den runs it & sees it work → Codex reviews → Claude fixes findings → next step.**

## 6. Phases

**Phase 1 — dashboard (build first)**
1. Skeleton: venv, deps (textual, psutil), empty dashboard shell that runs
2. CPU + RAM live panels
3. Disk activity for both drives, with sparklines
4. Top-processes table, AI-tool tags, sorting keys
5. Per-process disk read/write (ctypes → proc_pid_rusage)
6. SSD temperatures + SMART health, both drives, best-effort
7. Hardware health panel: fan status + thermal state (SMC helper, graceful "unknown")
8. Plain-English insight engine + details toggle
9. Close-a-process action with impact preview dialog
→ Codex review at every step; AGY consistency sweep at phase end.

**Phase 2 — actions & rules:** throttle, Spotlight pause, safety-tier enforcement, knowledge base, escalation + launchd rule generator. AGY builds boilerplate from Claude's specs.

**Phase 3 — always watching:** login LaunchAgent, macOS notifications, Telegram alerts via Hermes, daily "hardware healthy" heartbeat, fan-failure and SMART-failure alerts.

## 7. Approval gate

Nothing beyond this document is built until Den approves. On approval, work starts at Phase 1 step 1, one taught step at a time.

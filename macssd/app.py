"""The terminal dashboard shell (Phase 1, Step 1).

Draws the five empty panels. Later steps fill each one with live data.
"""

import os

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Static

from macssd.actions import classify_kill_safety, close_process
from macssd.collectors import disk, health, processes, system, thermal
from macssd.collectors.processes import ProcInfo
from macssd.insights import Insight, InsightEngine
from macssd.sparkline import spark

REFRESH_SECONDS = 2.0

_TAG_STYLE = {"AI/DEV": "magenta", "SYSTEM": "grey58", "APP": "cyan"}


class Panel(Static):
    """A bordered, titled panel. Shows placeholder text until a step fills it."""


def _tag_cell(tag: str) -> Text:
    """A coloured tag for the process table."""
    return Text(tag, style=_TAG_STYLE.get(tag, "white"))


def _fmt_mem(mem_mb: float) -> str:
    return f"{mem_mb / 1024:.1f} GB" if mem_mb >= 1024 else f"{mem_mb:.0f} MB"


def _rate_cell(mbs: float, color: str) -> Text:
    """A disk-rate cell: dim dot when idle, coloured number when active."""
    if mbs < 0.5:
        return Text("·", style="grey37")
    return Text(f"{mbs:.0f}", style=color)


def render_system(stats: system.SystemStats) -> str:
    """Build the System panel text: plain-English headline, then raw numbers."""
    cpu_word = system.describe_cpu(stats.cpu_percent)
    ram_word = system.describe_ram(stats.ram_percent)
    return (
        f"[b]CPU[/b] is under {cpu_word}, memory is {ram_word}.\n\n"
        f"[dim]CPU[/dim]   {stats.cpu_percent:.0f}%\n"
        f"[dim]RAM[/dim]   {stats.ram_used_gb:.1f} GB of "
        f"{stats.ram_total_gb:.0f} GB  ({stats.ram_percent:.0f}%)\n"
        f"[dim]Load[/dim]  {stats.load_1:.2f}  {stats.load_5:.2f}  {stats.load_15:.2f}"
    )


def _busiest(speeds: dict[str, disk.DriveSpeed]) -> str:
    """Plain-English headline for the disks."""
    active = [s for s in speeds.values() if s.available]
    if not active:
        return "No drives being monitored."
    peak = max(active, key=lambda s: max(s.read_mbs, s.write_mbs))
    busy = max(peak.read_mbs, peak.write_mbs)
    if busy < 5:
        return "Both drives are quiet right now."
    doing = "writing" if peak.write_mbs >= peak.read_mbs else "reading"
    return f"{peak.name} is busy {doing}."


def render_storage(monitor: disk.DiskMonitor, speeds: dict[str, disk.DriveSpeed]) -> str:
    """Build the Storage panel text: headline, then a line per drive with sparklines."""
    lines = [f"[b]{_busiest(speeds)}[/b]", ""]
    for name, _ in monitor._drives:
        s = speeds.get(name) or disk.DriveSpeed(name, available=False)
        if not s.available:
            lines.append(f"[dim]{name:12}[/dim] not connected")
            continue
        read_spark = spark(monitor.read_hist[name], width=8)
        write_spark = spark(monitor.write_hist[name], width=8)
        lines.append(
            f"[dim]{name:12}[/dim] "
            f"R {read_spark} {s.read_mbs:5.0f} MB/s   "
            f"W {write_spark} {s.write_mbs:5.0f} MB/s"
        )
        lines.append(
            f"[dim]{'':12} free {s.free_gb:,.0f} GB of {s.total_gb:,.0f} GB[/dim]"
        )
    return "\n".join(lines)


_STATUS_ICON = {"ok": "[green]OK[/green]", "warn": "[yellow]WARN[/yellow]",
                 "critical": "[bold red]CRITICAL[/bold red]", "unknown": "[dim]--[/dim]"}

# Apple's thermalState mapped onto the same ok/warn/critical vocabulary as
# drive health, so both signals share one severity ordering in the headline.
_THERMAL_STATUS = {"nominal": "ok", "fair": "ok", "serious": "warn", "critical": "critical"}


def _health_headline(results: dict[str, health.DriveHealth], therm: thermal.ThermalStatus) -> str:
    """Plain-English headline for the hardware health panel, worst status first."""
    therm_status = _THERMAL_STATUS.get(therm.state, "unknown") if therm.available else "unknown"

    for status, verb in (("critical", "needs attention"), ("warn", "is worth watching")):
        if therm_status == status:
            return f"The Mac {verb}: {therm.reason}"
        bad = next((h for h in results.values() if h.status == status), None)
        if bad:
            return f"{bad.name} {verb}: {bad.reason}"

    # Nothing critical or warn — but "unknown" must never be reported as healthy.
    drives_known = [h for h in results.values() if h.status == "ok"]
    drives_unknown = any(h.status == "unknown" for h in results.values()) or not results
    therm_unknown = therm_status == "unknown"

    if drives_unknown and therm_unknown:
        return "Hardware health could not be checked."
    if therm_unknown:
        return "Drives are healthy. Thermal status could not be checked."
    if drives_unknown:
        return "Thermals look fine. Drive health could not be checked."
    return "Everything looks healthy — drives and thermals both OK."


def render_health(results: dict[str, health.DriveHealth], therm: thermal.ThermalStatus) -> str:
    """Build the Hardware health panel text: headline, thermal line, then per-drive lines."""
    lines = [f"[b]{_health_headline(results, therm)}[/b]", ""]

    therm_status = _THERMAL_STATUS.get(therm.state, "unknown") if therm.available else "unknown"
    therm_icon = _STATUS_ICON.get(therm_status, _STATUS_ICON["unknown"])
    lines.append(f"[dim]{'System temp':12}[/dim] {therm_icon}  {therm.reason}")

    if not health.smartctl_available():
        lines.append("[dim]smartctl is not installed — drive health unavailable.[/dim]")
        return "\n".join(lines)
    for name, h in results.items():
        icon = _STATUS_ICON.get(h.status, _STATUS_ICON["unknown"])
        if not h.available or h.temp_c is None:
            lines.append(f"[dim]{name:12}[/dim] {icon}  {h.reason}")
            continue
        wear = f"{h.wear_pct}%" if h.wear_pct is not None else "unknown"
        lines.append(
            f"[dim]{name:12}[/dim] {icon}  {h.temp_c}°C "
            f"[dim](warns at {h.warn_c}°C)[/dim]  wear {wear}"
        )
    return "\n".join(lines)


_INSIGHT_ICON = {"warn": "[yellow]![/yellow]", "info": "[blue]i[/blue]", "ok": "[green]✓[/green]"}


def render_insights(insights: list[Insight], show_details: bool) -> str:
    """Build the Insights panel text: one line per insight, worst-first, icon-coded."""
    order = {"warn": 0, "info": 1, "ok": 2}
    ordered = sorted(insights, key=lambda i: order.get(i.severity, 3))
    lines = []
    for i in ordered:
        icon = _INSIGHT_ICON.get(i.severity, "[dim]?[/dim]")
        lines.append(f"{icon} {i.headline}")
        if show_details and i.detail:
            lines.append(f"  [dim]{i.detail}[/dim]")
    hint = "hide details" if show_details else "show details"
    lines.append(f"\n[dim]press x to {hint}[/dim]")
    return "\n".join(lines)


class ClosePreviewScreen(ModalScreen[bool]):
    """Impact-preview dialog shown before closing a process.

    Red-tier processes show a refusal with no way to proceed. Yellow-tier
    processes show what will happen and require an explicit y/n before
    dismiss(True) is sent back to the caller.
    """

    DEFAULT_CSS = """
    ClosePreviewScreen {
        align: center middle;
    }
    #preview-box {
        width: 56;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, proc: ProcInfo, tier: str, reason: str) -> None:
        super().__init__()
        self._proc = proc
        self._tier = tier
        self._reason = reason

    def compose(self) -> ComposeResult:
        p = self._proc
        lines = [f"[b]Close {p.name}?[/b] [dim](pid {p.pid})[/dim]", ""]
        lines.append(f"[dim]Tag[/dim]    {p.tag}")
        lines.append(f"[dim]CPU[/dim]    {p.cpu:.0f}%")
        lines.append(f"[dim]Memory[/dim] {_fmt_mem(p.mem_mb)}")
        lines.append(f"[dim]Disk[/dim]   write {p.write_mbs:.0f} MB/s, read {p.read_mbs:.0f} MB/s")
        lines.append("")
        if self._tier == "red":
            lines.append(f"[bold red]Can't close this — {self._reason}[/bold red]")
            lines.append("")
            lines.append("[dim]press any key to go back[/dim]")
        else:
            lines.append(f"[yellow]{self._reason}[/yellow]")
            lines.append("")
            lines.append("[b]y[/b] close it    [b]n[/b] / [b]esc[/b] cancel")
        yield Static("\n".join(lines), id="preview-box")

    def on_key(self, event) -> None:
        if self._tier == "red":
            self.dismiss(False)
            return
        if event.key in ("y", "enter"):
            self.dismiss(True)
        elif event.key in ("n", "escape"):
            self.dismiss(False)


class MacssdApp(App):
    """MACSSD_Performance Watcher dashboard."""

    TITLE = "MACSSD_Performance Watcher"
    SUB_TITLE = "Mac mini M4"

    CSS = """
    #top-row {
        height: 10;
    }

    .panel {
        border: round $accent;
        padding: 0 1;
        margin: 0 1;
        color: $text-muted;
    }

    #system, #storage {
        width: 1fr;
    }

    #processes {
        height: 1fr;
        border: round $accent;
        margin: 0 1;
    }

    #health {
        height: 8;
    }

    #insights {
        height: 12;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "sort_cpu", "Sort by CPU"),
        ("m", "sort_mem", "Sort by memory"),
        ("d", "sort_disk", "Sort by disk"),
        ("x", "toggle_details", "Toggle details"),
        ("k", "close_selected", "Close process"),
    ]

    _timer = None
    _disk: disk.DiskMonitor
    _procs: processes.ProcessCollector
    _health: health.HealthCollector
    _insights: InsightEngine
    _proc_sort: str = "cpu"
    _show_details: bool = False
    _last_insights: list[Insight] = []
    _proc_by_pid: dict[int, ProcInfo] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top-row"):
            yield Panel("Waiting for data…", id="system", classes="panel")
            yield Panel("Waiting for data…", id="storage", classes="panel")
        yield DataTable(id="processes")
        yield Panel("Waiting for data…", id="health", classes="panel")
        yield Panel("Waiting for data…", id="insights", classes="panel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#system").border_title = "System"
        self.query_one("#storage").border_title = "Storage"
        self.query_one("#health").border_title = "Hardware health"
        self.query_one("#insights").border_title = "Insights"

        table = self.query_one("#processes", DataTable)
        table.cursor_type = "row"
        table.add_columns("PID", "Name", "CPU%", "Memory", "Write/s", "Read/s", "Tag")
        table.border_title = "Top processes"

        system.prime()
        self._disk = disk.DiskMonitor()
        self._disk.sample()  # prime disk counters so the first speed is real
        self._procs = processes.ProcessCollector()
        self._procs.prime()  # prime per-process CPU counters
        self._procs.sample()  # baseline for per-process disk rates
        self._health = health.HealthCollector()
        self._insights = InsightEngine()
        for pid in ("#system", "#storage"):
            self.query_one(pid, Panel).update("Measuring… first reading in 2s")
        self.query_one("#health", Panel).update("Checking drive health…")
        self.query_one("#insights", Panel).update("Watching for patterns…")
        if self._timer is None:
            self._timer = self.set_interval(REFRESH_SECONDS, self.tick)

    def tick(self) -> None:
        stats = system.read()
        self.query_one("#system", Panel).update(render_system(stats))

        speeds = self._disk.sample()
        self.query_one("#storage", Panel).update(render_storage(self._disk, speeds))

        self._procs.sample()
        shown = self.refresh_processes()
        top_procs = self._procs.top(sort_by="disk", limit=8)
        # everything currently on screen (in whichever sort) plus the
        # disk-sorted list used for insights — this is the full set of pids
        # the user could possibly select or that insights could reference.
        self._proc_by_pid = {p.pid: p for p in (*shown, *top_procs)}

        results = self._health.sample()
        therm = thermal.read()
        self.query_one("#health", Panel).update(render_health(results, therm))

        self._last_insights = self._insights.sample(stats, results, top_procs)
        self.query_one("#insights", Panel).update(
            render_insights(self._last_insights, self._show_details)
        )

    def refresh_processes(self) -> list[ProcInfo]:
        table = self.query_one("#processes", DataTable)
        top = self._procs.top(sort_by=self._proc_sort, limit=8)
        keep_cursor = table.cursor_row
        table.clear()
        for p in top:
            name = p.name if len(p.name) <= 20 else p.name[:19] + "…"
            table.add_row(
                str(p.pid), name, f"{p.cpu:.0f}", _fmt_mem(p.mem_mb),
                _rate_cell(p.write_mbs, "#F0997B"), _rate_cell(p.read_mbs, "#5DCAA5"),
                _tag_cell(p.tag),
                key=str(p.pid),
            )
        if table.row_count and keep_cursor is not None:
            table.cursor_coordinate = (min(keep_cursor, table.row_count - 1), 0)
        label = {"cpu": "CPU", "mem": "MEMORY", "disk": "DISK"}[self._proc_sort]
        table.border_title = f"Top processes — sort: {label}  (keys c · m · d, k close)"
        return top

    def action_sort_cpu(self) -> None:
        self._proc_sort = "cpu"
        self.refresh_processes()

    def action_sort_mem(self) -> None:
        self._proc_sort = "mem"
        self.refresh_processes()

    def action_sort_disk(self) -> None:
        self._proc_sort = "disk"
        self.refresh_processes()

    def action_toggle_details(self) -> None:
        self._show_details = not self._show_details
        self.query_one("#insights", Panel).update(
            render_insights(self._last_insights, self._show_details)
        )

    def action_close_selected(self) -> None:
        table = self.query_one("#processes", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            return
        try:
            pid = int(table.ordered_rows[table.cursor_row].key.value)
        except (IndexError, TypeError, ValueError):
            return
        proc = self._proc_by_pid.get(pid)
        if proc is None:
            self.notify("That process is no longer in the list.", severity="warning")
            return

        tier, reason = classify_kill_safety(proc, os.getpid())

        create_time = proc.create_time

        def handle_result(proceed: bool | None) -> None:
            if not proceed:
                return
            ok, msg = close_process(pid, create_time)
            self.notify(msg, severity="information" if ok else "error")
            self.refresh_processes()

        self.push_screen(ClosePreviewScreen(proc, tier, reason), handle_result)


def main() -> None:
    MacssdApp().run()


if __name__ == "__main__":
    main()

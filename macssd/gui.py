"""MACSSD_Performance Watcher — native macOS GUI (Step B: live CPU/RAM cards).

A real AppKit window built directly with PyObjC — no new dependency, reuses
the same framework already proven in thermal.py and menubar.py. Reuses the
existing collectors and severity thresholds; this file is presentation only.

Run with: "./.venv/bin/python" -m macssd.gui
"""

import threading
import traceback
import warnings
import os

import objc
from AppKit import (
    NSApp,
    NSApplication,
    NSAlert,
    NSAlertFirstButtonReturn,
    NSAlertStyleInformational,
    NSAlertStyleWarning,
    NSBackingStoreBuffered,
    NSBezelStyleCircular,
    NSBezelStyleRounded,
    NSButton,
    NSButtonTypeMomentaryPushIn,
    NSButtonTypeSwitch,
    NSColor,
    NSFont,
    NSMakeRect,
    NSMakeSize,
    NSMinYEdge,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSTextField,
    NSScrollView,
    NSTimer,
    NSView,
    NSViewController,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject

from macssd.actions import classify_kill_safety, close_process
from macssd.collectors import disk, health, processes, system, thermal
from macssd.insights import InsightEngine
from macssd.severity import THERMAL_SEVERITY, cpu_severity, ram_severity, storage_severity
from macssd.storage import is_login_item_enabled, read_storage

warnings.filterwarnings("ignore", category=objc.ObjCPointerWarning)

WINDOW_WIDTH = 640
# Extra height gives the process list room to breathe while keeping the
# dashboard anchored as a compact popover under the 700px width cap.
WINDOW_HEIGHT = 736
FOOTER_HEIGHT = 54
REFRESH_SECONDS = 2.0
PROCESS_ROWS = 15

_TAG_COLOR = {
    "AI/DEV": NSColor.systemPurpleColor,
    "SYSTEM": NSColor.systemGrayColor,
    "APP": NSColor.systemTealColor,
}

_STYLE = (
    NSWindowStyleMaskTitled
    | NSWindowStyleMaskClosable
    | NSWindowStyleMaskMiniaturizable
    # Deliberately not resizable — the layout uses fixed positions, not a
    # reflowing one, so resizing the window would leave cards misplaced and
    # cut off rather than adapting.
)

_SEVERITY_COLOR = {
    "ok": NSColor.systemGreenColor,
    "warn": NSColor.systemOrangeColor,
    "critical": NSColor.systemRedColor,
}


def _label(text: str, x: float, y: float, w: float, h: float, size: float, bold: bool = False) -> NSTextField:
    field = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    field.setStringValue_(text)
    field.setBezeled_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    field.setFont_(font)
    field.setTextColor_(NSColor.secondaryLabelColor() if not bold else NSColor.labelColor())
    return field


def _button(title: str, x: float, y: float, w: float, h: float, target, action: str) -> NSButton:
    button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    button.setTitle_(title)
    button.setBezelStyle_(NSBezelStyleRounded)
    button.setButtonType_(NSButtonTypeSwitch)
    button.setTarget_(target)
    button.setAction_(action)
    return button


def _colored_view(frame, color, corner_radius: float | None = None) -> NSView:
    """corner_radius=None means "pill" (half the height) — correct for thin
    bars, but wrong for tall card containers, where it makes them render as
    a giant circle instead of a rounded rectangle. Cards must pass an
    explicit small radius."""
    view = NSView.alloc().initWithFrame_(frame)
    view.setWantsLayer_(True)
    view.layer().setBackgroundColor_(color.CGColor())
    radius = corner_radius if corner_radius is not None else frame.size.height / 2
    view.layer().setCornerRadius_(radius)
    return view


CARD_RADIUS = 10


class MetricCard:
    """A label, a big value, and a coloured progress bar — one per metric."""

    def __init__(self, parent: NSView, title: str, x: float, y: float, w: float, h: float = 78) -> None:
        container = _colored_view(
            NSMakeRect(x, y, w, h), NSColor.controlBackgroundColor(), corner_radius=CARD_RADIUS
        )
        parent.addSubview_(container)
        self.container = container

        container.addSubview_(_label(title, 14, h - 26, w - 28, 16, 12))
        self.value_label = _label("--", 14, h - 54, w - 28, 26, 22, bold=True)
        container.addSubview_(self.value_label)

        track_w = w - 28
        self.track = _colored_view(NSMakeRect(14, 14, track_w, 6), NSColor.separatorColor())
        container.addSubview_(self.track)
        self.fill = _colored_view(NSMakeRect(14, 14, 0, 6), NSColor.systemGreenColor())
        container.addSubview_(self.fill)
        self._track_w = track_w

    def update(self, percent: float, severity: str, value_text: str | None = None) -> None:
        self.value_label.setStringValue_(value_text if value_text is not None else f"{percent:.0f}%")
        color_fn = _SEVERITY_COLOR.get(severity, NSColor.systemGreenColor)
        self.fill.layer().setBackgroundColor_(color_fn().CGColor())
        frame = self.fill.frame()
        frame.size.width = max(0.0, min(1.0, percent / 100)) * self._track_w
        self.fill.setFrame_(frame)


STORAGE_CARD_HEIGHT = 96


class StorageCard(MetricCard):
    """A drive's used/total capacity plus live read/write throughput."""

    def __init__(self, parent: NSView, title: str, x: float, y: float, w: float) -> None:
        super().__init__(parent, title, x, y, w, h=STORAGE_CARD_HEIGHT)
        self.speed_label = _label("R -- MB/s   W -- MB/s", 14, 22, w - 28, 16, 11)
        self.container.addSubview_(self.speed_label)

    def update_storage(self, used_gb: float, total_gb: float) -> None:
        pct = (used_gb / total_gb * 100) if total_gb > 0 else 0
        severity = storage_severity(used_gb, total_gb)
        self.update(pct, severity, value_text=f"{used_gb:.0f} / {total_gb:.0f} GB")

    def update_speed(self, read_mbs: float, write_mbs: float, available: bool) -> None:
        if not available:
            self.speed_label.setStringValue_("R -- MB/s   W -- MB/s")
            return
        self.speed_label.setStringValue_(f"R {read_mbs:5.0f} MB/s   W {write_mbs:5.0f} MB/s")


class TempCard:
    """A drive's (or the Mac's) temperature — no bar, just a value and a status word."""

    def __init__(self, parent: NSView, title: str, x: float, y: float, w: float) -> None:
        h = 78
        container = _colored_view(
            NSMakeRect(x, y, w, h), NSColor.controlBackgroundColor(), corner_radius=CARD_RADIUS
        )
        parent.addSubview_(container)

        container.addSubview_(_label(title, 14, h - 26, w - 28, 16, 12))
        self.value_label = _label("--", 14, h - 54, w - 28, 26, 22, bold=True)
        container.addSubview_(self.value_label)
        self.status_label = _label("--", 14, 14, w - 28, 16, 12)
        container.addSubview_(self.status_label)

    def update(self, temp_c: int | None, status: str) -> None:
        color_fn = _SEVERITY_COLOR.get(status, NSColor.secondaryLabelColor)
        if temp_c is not None:
            self.value_label.setStringValue_(f"{temp_c}°C")
            self.value_label.setTextColor_(color_fn())
            self.status_label.setStringValue_(status)
        else:
            self.value_label.setStringValue_("--")
            self.value_label.setTextColor_(NSColor.labelColor())
            self.status_label.setStringValue_("unavailable")


class ThermalStateLine:
    """Compact system-wide Apple thermal pressure line."""

    def __init__(self, parent: NSView, x: float, y: float, w: float) -> None:
        self.title_label = _label("Apple thermal", x, y, 110, 18, 12)
        parent.addSubview_(self.title_label)
        self.value_label = _label("--", x + 112, y, w - 112, 18, 12, bold=True)
        parent.addSubview_(self.value_label)

    def update(self, therm) -> None:
        if not therm.available:
            self.value_label.setStringValue_("unavailable")
            self.value_label.setTextColor_(NSColor.secondaryLabelColor())
            return
        status = THERMAL_SEVERITY.get(therm.state, "unknown")
        color_fn = _SEVERITY_COLOR.get(status, NSColor.secondaryLabelColor)
        self.value_label.setStringValue_(f"{therm.state} - {therm.reason}")
        self.value_label.setTextColor_(color_fn())


class InsightBanner:
    """A single-line banner showing the worst current insight, colour-coded."""

    def __init__(self, parent: NSView, x: float, y: float, w: float) -> None:
        h = 40
        self.container = _colored_view(
            NSMakeRect(x, y, w, h), NSColor.systemGreenColor(), corner_radius=8
        )
        parent.addSubview_(self.container)
        self.text_label = _label("Watching for patterns…", 14, 11, w - 28, 18, 13)
        self.container.addSubview_(self.text_label)

    def update(self, insights) -> None:
        order = {"warn": 0, "info": 1, "ok": 2}
        worst = sorted(insights, key=lambda i: order.get(i.severity, 3))[0] if insights else None
        if worst is None:
            self.text_label.setStringValue_("Everything looks normal.")
            color = NSColor.systemGreenColor()
        else:
            self.text_label.setStringValue_(worst.headline)
            color = {
                "warn": NSColor.systemOrangeColor(),
                "info": NSColor.systemBlueColor(),
                "ok": NSColor.systemGreenColor(),
            }.get(worst.severity, NSColor.systemGreenColor())
        # Tint, not a solid fill, so the text (labelColor) stays readable.
        self.container.layer().setBackgroundColor_(color.colorWithAlphaComponent_(0.15).CGColor())
        self.text_label.setTextColor_(NSColor.labelColor())


class ProcessRow:
    def __init__(self, parent: NSView, y: float, w: float, target, index: int) -> None:
        self.proc = None
        self.name_label = _label("", 14, y, w * 0.4, 20, 15)
        parent.addSubview_(self.name_label)
        self.tag_label = _label("", w * 0.45, y, w * 0.2, 20, 13)
        parent.addSubview_(self.tag_label)
        self.cpu_label = _label("", w - 86, y, 46, 20, 15)
        self.cpu_label.setAlignment_(1)  # right-aligned
        parent.addSubview_(self.cpu_label)
        self.close_button = NSButton.alloc().initWithFrame_(NSMakeRect(w - 30, y - 1, 26, 22))
        self.close_button.setTitle_("x")
        self.close_button.setFont_(NSFont.boldSystemFontOfSize_(13))
        self.close_button.setBezelStyle_(NSBezelStyleCircular)
        self.close_button.setButtonType_(NSButtonTypeMomentaryPushIn)
        self.close_button.setTarget_(target)
        self.close_button.setAction_("processCloseClicked:")
        self.close_button.setTag_(index)
        self.close_button.setEnabled_(False)
        parent.addSubview_(self.close_button)

    def update(self, proc) -> None:
        self.proc = proc
        if proc is None:
            self.name_label.setStringValue_("")
            self.tag_label.setStringValue_("")
            self.cpu_label.setStringValue_("")
            self.close_button.setEnabled_(False)
            self.close_button.setHidden_(True)
            return
        self.name_label.setStringValue_(proc.name[:28])
        self.tag_label.setStringValue_(proc.tag)
        color_fn = _TAG_COLOR.get(proc.tag, NSColor.secondaryLabelColor)
        self.tag_label.setTextColor_(color_fn())
        self.cpu_label.setStringValue_(f"{proc.cpu:.0f}%")
        self.close_button.setEnabled_(True)
        self.close_button.setHidden_(False)


class ProcessList:
    def __init__(self, parent: NSView, x: float, y: float, w: float, h: float, target) -> None:
        scroll_view = NSScrollView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setHasHorizontalScroller_(False)
        scroll_view.setAutohidesScrollers_(True)
        scroll_view.setBorderType_(0)
        scroll_view.setDrawsBackground_(False)
        scroll_view.setWantsLayer_(True)
        scroll_view.layer().setBackgroundColor_(NSColor.controlBackgroundColor().CGColor())
        scroll_view.layer().setCornerRadius_(CARD_RADIUS)
        scroll_view.layer().setMasksToBounds_(True)
        parent.addSubview_(scroll_view)
        self.scroll_view = scroll_view

        row_h = 40
        content_h = max(h, 24 + 6 + row_h * PROCESS_ROWS + 14)
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, content_h))
        content.setWantsLayer_(True)
        content.layer().setBackgroundColor_(NSColor.controlBackgroundColor().CGColor())
        scroll_view.setDocumentView_(content)
        self.content = content

        content.addSubview_(_label("Top processes", 14, content_h - 24, w - 78, 16, 12))
        hint = _label("x closes", w - 76, content_h - 24, 62, 16, 11)
        hint.setAlignment_(1)
        content.addSubview_(hint)
        self.rows = [
            ProcessRow(content, content_h - 24 - row_h * (i + 1) - 6, w - 28, target, i)
            for i in range(PROCESS_ROWS)
        ]

    def update(self, procs) -> None:
        for i, row in enumerate(self.rows):
            row.update(procs[i] if i < len(procs) else None)

    def process_for_sender(self, sender):
        index = sender.tag()
        if index < 0 or index >= len(self.rows):
            return None
        return self.rows[index].proc


class DashboardWindowController(NSObject):
    """Owns the dashboard window. Reusable from either the standalone
    `python -m macssd.gui` entry point or the menu bar app — both host it
    inside their own NSApplication run loop rather than starting a second one.
    """

    def build(self) -> None:
        rect = NSMakeRect(200, 200, WINDOW_WIDTH, WINDOW_HEIGHT)
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, _STYLE, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("MACSSD Performance Watcher")
        self.window.setMovable_(False)  # a fixed small panel, not something to drag around

        content = self.window.contentView()
        self._build_dashboard_content(content)

    def _build_dashboard_content(self, content: NSView, include_footer: bool = False) -> None:
        card_w = (WINDOW_WIDTH - 14 * 3) / 2
        metric_y = WINDOW_HEIGHT - 78 - 14
        self.cpu_card = MetricCard(content, "CPU", 14, metric_y, card_w)
        self.ram_card = MetricCard(content, "Memory", 14 * 2 + card_w, metric_y, card_w)

        storage_y = metric_y - STORAGE_CARD_HEIGHT - 14
        self.internal_storage = StorageCard(content, "Internal SSD", 14, storage_y, card_w)
        self.densmate_storage = StorageCard(content, "DensMate SSD", 14 * 2 + card_w, storage_y, card_w)

        temp_y = storage_y - 78 - 14
        self.internal_temp = TempCard(content, "Internal SSD temp", 14, temp_y, card_w)
        self.densmate_temp = TempCard(content, "DensMate SSD temp", 14 * 2 + card_w, temp_y, card_w)

        thermal_y = temp_y - 24
        self.thermal_state = ThermalStateLine(content, 14, thermal_y, WINDOW_WIDTH - 28)

        insight_y = thermal_y - 14 - 40
        self.insight_banner = InsightBanner(content, 14, insight_y, WINDOW_WIDTH - 28)

        process_y = 14 + FOOTER_HEIGHT if include_footer else 14
        process_h = insight_y - 14 - process_y
        self.process_list = ProcessList(content, 14, process_y, WINDOW_WIDTH - 28, process_h, self)
        if include_footer:
            self._build_footer(content)

        self._health = health.HealthCollector()
        self._procs = processes.ProcessCollector()
        self._disk = disk.DiskMonitor()
        self._insights = InsightEngine()
        self._sampling = threading.Lock()
        self._procs.prime()
        system.prime()
        self._disk.sample()  # prime disk counters so the first speed reading is real
        self.refresh_(None)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            REFRESH_SECONDS, self, "refresh:", None, True
        )

    def show(self) -> None:
        """Build the window on first use, then just bring it to front on
        every later call — the timer and collectors keep running whether the
        window is visible or not, so data doesn't go stale while it's hidden."""
        if not hasattr(self, "window"):
            self.build()
        if self.window.isMiniaturized():
            self.window.deminiaturize_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)
        self.window.orderFrontRegardless()

    def toggle(self) -> None:
        if (
            hasattr(self, "window")
            and self.window.isVisible()
            and not self.window.isMiniaturized()
        ):
            self.window.miniaturize_(None)
        else:
            self.show()

    def refresh_(self, _timer) -> None:
        """Kick off sampling on a background thread — health.py can shell out
        to smartctl with a multi-second timeout, and doing that on the main
        thread would freeze the whole window until it returns.

        If a previous sample is still running when the timer fires again
        (e.g. a slow smartctl call), skip this tick rather than starting a
        second thread — DiskMonitor.sample() mutates shared counters/history
        with no lock of its own, so two overlapping samples could compute a
        speed delta against the wrong previous reading."""
        if not self._sampling.acquire(blocking=False):
            return
        threading.Thread(target=self._sample_in_background, daemon=True).start()

    def _sample_in_background(self) -> None:
        try:
            stats = system.read()
            storage = read_storage()
            speeds = self._disk.sample()
            health_results = self._health.sample()
            therm = thermal.read()
            self._procs.sample()
            top_procs = self._procs.top(sort_by="cpu", limit=PROCESS_ROWS)
            insights = self._insights.sample(stats, health_results, top_procs)
        except Exception:  # noqa: BLE001
            # A single bad sample (a transient OS syscall failure, a smartctl
            # hiccup) must never crash the app or freeze the UI on stale
            # data — skip this tick and try again on the next timer fire.
            traceback.print_exc()
            return
        finally:
            self._sampling.release()
        result = (stats, storage, speeds, health_results, therm, top_procs, insights)
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "applyResult:", result, False
        )

    def applyResult_(self, result) -> None:
        stats, storage, speeds, health_results, therm, top_procs, insights = result

        self.cpu_card.update(stats.cpu_percent, cpu_severity(stats.cpu_percent))
        self.ram_card.update(stats.ram_percent, ram_severity(stats.ram_percent))

        drives = (
            ("Internal SSD", self.internal_storage, self.internal_temp),
            ("DensMate SSD", self.densmate_storage, self.densmate_temp),
        )
        for name, storage_card, temp_card in drives:
            s = storage.get(name)
            sp = speeds.get(name)
            h = health_results.get(name)
            if s and s.available:
                storage_card.update_storage(s.used_gb, s.total_gb)
            storage_card.update_speed(
                sp.read_mbs if sp else 0.0, sp.write_mbs if sp else 0.0, bool(sp and sp.available)
            )
            temp_c = h.temp_c if h and h.available else None
            temp_status = h.status if h else "unknown"
            temp_card.update(temp_c, temp_status)

        self.thermal_state.update(therm)
        self.process_list.update(top_procs)
        self.insight_banner.update(insights)

    def processCloseClicked_(self, sender) -> None:
        proc = self.process_list.process_for_sender(sender)
        if proc is None:
            return

        tier, reason = classify_kill_safety(proc, os.getpid())
        if tier == "red":
            self._show_process_alert(
                "Cannot close process",
                f"{proc.name} (pid {proc.pid}) cannot be closed.\n\n{reason}",
                NSAlertStyleInformational,
            )
            return

        alert = NSAlert.alloc().init()
        alert.setAlertStyle_(NSAlertStyleWarning)
        alert.setMessageText_(f"Close {proc.name}?")
        alert.setInformativeText_(
            f"pid {proc.pid}\n\n{reason}"
        )
        alert.addButtonWithTitle_("Close")
        alert.addButtonWithTitle_("Cancel")
        buttons = alert.buttons()
        if buttons and buttons[0].respondsToSelector_("setHasDestructiveAction:"):
            buttons[0].setHasDestructiveAction_(True)
        if alert.runModal() != NSAlertFirstButtonReturn:
            return

        pid = proc.pid
        create_time = proc.create_time
        threading.Thread(
            target=self._close_process_in_background,
            args=(pid, create_time),
            daemon=True,
        ).start()

    @objc.python_method
    def _close_process_in_background(self, pid: int, create_time: float) -> None:
        try:
            result = close_process(pid, create_time)
        except Exception as exc:  # noqa: BLE001
            result = (False, f"Could not close it: {exc}")
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "closeProcessFinished:", result, False
        )

    def closeProcessFinished_(self, result) -> None:
        ok, message = result
        self._show_process_alert(
            "Close request sent" if ok else "Close failed",
            message,
            NSAlertStyleInformational if ok else NSAlertStyleWarning,
        )

    @objc.python_method
    def _show_process_alert(self, title: str, message: str, style) -> None:
        alert = NSAlert.alloc().init()
        alert.setAlertStyle_(style)
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_("OK")
        alert.runModal()


class DashboardPopoverController(DashboardWindowController):
    """Menu-bar attached dashboard surface.

    This uses NSPopover so the dashboard behaves like a status-item dropdown,
    not like a normal desktop window that appears in Mission Control.
    """

    def build(self) -> None:
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WINDOW_WIDTH, WINDOW_HEIGHT))
        self._build_dashboard_content(content, include_footer=True)

        self.view_controller = NSViewController.alloc().init()
        self.view_controller.setView_(content)

        self.popover = NSPopover.alloc().init()
        self.popover.setBehavior_(NSPopoverBehaviorTransient)
        self.popover.setContentSize_(NSMakeSize(WINDOW_WIDTH, WINDOW_HEIGHT))
        self.popover.setContentViewController_(self.view_controller)

    @objc.python_method
    def configure_controls(
        self,
        storage_callback,
        temps_callback,
        login_callback,
        quit_callback,
        settings: dict | None = None,
    ) -> None:
        self._storage_callback = storage_callback
        self._temps_callback = temps_callback
        self._login_callback = login_callback
        self._quit_callback = quit_callback
        self._footer_settings = dict(settings) if settings is not None else {}

    @objc.python_method
    def _build_footer(self, content: NSView) -> None:
        from AppKit import NSControlStateValueOff, NSControlStateValueOn
        s = getattr(self, "_footer_settings", {})
        footer = _colored_view(
            NSMakeRect(14, 14, WINDOW_WIDTH - 28, 40),
            NSColor.controlBackgroundColor(),
            corner_radius=CARD_RADIUS,
        )
        content.addSubview_(footer)
        footer.addSubview_(_label("Settings", 14, 11, 70, 18, 12))
        self._storage_btn = _button("Storage", 90, 7, 90, 26, self, "storageClicked:")
        self._storage_btn.setState_(
            NSControlStateValueOn if s.get("show_storage", True) else NSControlStateValueOff
        )
        self._temps_btn = _button("Temps", 188, 7, 78, 26, self, "tempsClicked:")
        self._temps_btn.setState_(
            NSControlStateValueOn if s.get("show_temps", True) else NSControlStateValueOff
        )
        self._login_btn = _button("Login", 274, 7, 76, 26, self, "loginClicked:")
        self._login_btn.setState_(
            NSControlStateValueOn if is_login_item_enabled() else NSControlStateValueOff
        )
        footer.addSubview_(self._storage_btn)
        footer.addSubview_(self._temps_btn)
        footer.addSubview_(self._login_btn)
        footer.addSubview_(_button("Quit", WINDOW_WIDTH - 28 - 78, 7, 64, 26, self, "quitClicked:"))

    def storageClicked_(self, _sender) -> None:
        callback = getattr(self, "_storage_callback", None)
        if callback is not None:
            callback()

    def tempsClicked_(self, _sender) -> None:
        callback = getattr(self, "_temps_callback", None)
        if callback is not None:
            callback()

    def loginClicked_(self, _sender) -> None:
        from AppKit import NSControlStateValueOff, NSControlStateValueOn

        callback = getattr(self, "_login_callback", None)
        if callback is not None:
            callback()
        # AppKit already flipped the switch's visual state on click, before
        # we know whether enable/disable actually succeeded — resync it to
        # the real login-item status rather than trust that assumption.
        self._login_btn.setState_(
            NSControlStateValueOn if is_login_item_enabled() else NSControlStateValueOff
        )

    def quitClicked_(self, _sender) -> None:
        callback = getattr(self, "_quit_callback", None)
        if callback is not None:
            callback()

    @objc.python_method
    def show_attached_to(self, anchor_view) -> None:
        if not hasattr(self, "popover"):
            self.build()
        if self.popover.isShown():
            return
        self.popover.showRelativeToRect_ofView_preferredEdge_(
            anchor_view.bounds(), anchor_view, NSMinYEdge
        )

    @objc.python_method
    def toggle_attached_to(self, anchor_view) -> None:
        if hasattr(self, "popover") and self.popover.isShown():
            self.popover.close()
            return
        if anchor_view is None:
            return
        self.show_attached_to(anchor_view)


class _StandaloneAppDelegate(NSObject):
    """Entry point for `python -m macssd.gui` on its own — the menu bar app
    hosts DashboardWindowController differently, inside its own run loop,
    and doesn't use this class."""

    def applicationDidFinishLaunching_(self, _notification) -> None:
        self.controller = DashboardWindowController.alloc().init()
        self.controller.show()

    def applicationShouldTerminateAfterLastWindowClosed_(self, _sender) -> bool:
        return True


def main() -> None:
    app = NSApplication.sharedApplication()
    delegate = _StandaloneAppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.activateIgnoringOtherApps_(True)
    app.run()


if __name__ == "__main__":
    main()

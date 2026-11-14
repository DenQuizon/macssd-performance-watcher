"""MACSSD_Performance Watcher — macOS menu bar mode.

A second, lightweight view on top of the same collectors used by the
terminal dashboard (macssd/app.py). It reuses them as-is — no new backend
logic here, only presentation.

Run with: "./.venv/bin/python" -m macssd.menubar
"""

from __future__ import annotations

import json
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import psutil
import rumps
from Foundation import NSMutableAttributedString, NSObject, NSRange

from macssd import action_log, gui, menubar_render, severity
from macssd.actions import classify_kill_safety, restore_process, throttle_process
from macssd.collectors import health, system, thermal
from macssd.collectors.processes import classify
from macssd.storage import (
    StorageUsage,
    disable_login_item,
    enable_login_item,
    is_login_item_enabled,
    read_storage,
)

REFRESH_SECONDS = 3.0
STORAGE_REFRESH_SECONDS = 30.0  # used/free GB changes slowly; diskutil discovery is not free
BLINK_SECONDS = 0.6  # how fast the title flashes when something is critical

# Continuous throttling: deliberately much slower than REFRESH_SECONDS above.
# Scanning every process's CPU% is real work — doing it every 3s the way temps
# refresh would add a constant, avoidable drain of its own (the exact
# counterintuitive problem this feature exists to prevent). Every 25s, only
# acting after a process is confirmed hot across two consecutive scans (~50s
# sustained, not a brief spike), keeps the added overhead small and bounded.
THROTTLE_SCAN_SECONDS = 60.0
THROTTLE_CPU_THRESHOLD = 85.0
THROTTLE_CONFIRM_SCANS = 2  # ~2 minutes of sustained high CPU before acting
THROTTLE_RESTORE_BELOW = 40.0

_SETTINGS_PATH = Path.home() / ".macssd" / "menubar_settings.json"
_DEFAULT_SETTINGS = {"show_temps": True}


def load_settings() -> dict:
    try:
        loaded = json.loads(_SETTINGS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULT_SETTINGS)
    if not isinstance(loaded, dict):
        return dict(_DEFAULT_SETTINGS)  # valid JSON but the wrong shape (list, string, null, ...)
    return {**_DEFAULT_SETTINGS, **loaded}


def save_settings(settings: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(settings))


def _drive_label(name: str) -> str:
    if "Internal" in name:
        return "Int"
    if "External" in name:
        return "Ext"
    return name[:3]


# Re-exported under the old private name so existing imports/tests are
# unaffected — the actual logic now lives in severity.py, shared with the
# hourly watcher, so the two never quietly disagree about thresholds.
_THERMAL_SEVERITY = severity.THERMAL_SEVERITY


@dataclass
class TitleSegment:
    text: str
    severity: str = "neutral"  # "ok" | "warn" | "critical" | "neutral"
    blinkable: bool = False  # only temperature segments flash when critical


def build_segments(
    health_results: dict[str, health.DriveHealth],
    therm: thermal.ThermalStatus,
    settings: dict,
    cpu_temp_c: float | None = None,
) -> list[TitleSegment]:
    """Build the coloured menu bar segments: CPU temp + per-drive temps + Mac thermal state."""
    segs: list[TitleSegment] = []

    if not settings.get("show_temps", True):
        return [TitleSegment("MACSSD (temps hidden)")]

    cpu_sev = severity.cpu_temp_severity(cpu_temp_c)
    if cpu_temp_c is not None:
        segs.append(TitleSegment(f"CPU {cpu_temp_c:.0f}°C", cpu_sev, blinkable=True))
    else:
        segs.append(TitleSegment("CPU --"))

    for name, h in health_results.items():
        if segs:
            segs.append(TitleSegment("  "))
        label = _drive_label(name)
        if h.available and h.temp_c is not None:
            sev = h.status if h.status in ("ok", "warn", "critical") else "neutral"
            segs.append(TitleSegment(f"{label} {h.temp_c}°C", sev, blinkable=True))
        else:
            segs.append(TitleSegment(f"{label} --"))

    if therm.available and therm.state:
        if segs:
            segs.append(TitleSegment("  "))
        segs.append(TitleSegment(
            f"Mac {therm.state}", _THERMAL_SEVERITY.get(therm.state, "neutral"), blinkable=True
        ))

    return segs or [TitleSegment("MACSSD --")]


def build_compact_temp_segments(
    health_results: dict[str, health.DriveHealth],
    therm: thermal.ThermalStatus,
    settings: dict,
    cpu_temp_c: float | None = None,
) -> list[TitleSegment]:
    """Short temperature text shown beside the CPU/RAM/SSD graphics.

    Always shows each drive's temperature with its label (e.g. "INT 42°  EXT 31°").
    The CPU temperature
    and Mac thermal state only appear when they need attention; the full list
    stays in the tooltip and dashboard. Empty when temperatures are hidden.
    """
    if not settings.get("show_temps", True):
        return []

    segs: list[TitleSegment] = []
    for name, h in health_results.items():
        if not (h.available and h.temp_c is not None):
            continue
        sev = h.status if h.status in ("warn", "critical") else "neutral"
        if segs:
            segs.append(TitleSegment("  "))
        segs.append(TitleSegment(f"{_drive_label(name).upper()} {h.temp_c}°", sev, blinkable=True))

    cpu_sev = severity.cpu_temp_severity(cpu_temp_c)
    if cpu_temp_c is not None and cpu_sev in ("warn", "critical"):
        segs.append(TitleSegment(f" CPU {cpu_temp_c:.0f}°C", cpu_sev, blinkable=True))

    therm_sev = _THERMAL_SEVERITY.get(therm.state, "neutral") if therm.available else "neutral"
    if therm_sev in ("warn", "critical"):
        segs.append(TitleSegment(f" Mac {therm.state}", therm_sev, blinkable=True))
    return segs


def tooltip_text(segments: list[TitleSegment], model: menubar_render.CompactModel | None = None) -> str:
    """One reading per line, for hovering over the (deliberately compact)
    menu bar title to see everything spelled out."""
    lines = ["MACSSD_Performance Watcher"]
    if model is not None:
        lines.append(f"CPU {model.cpu.text}")
        lines.append(f"RAM {model.ram.text}")
        if model.ssd.available:
            lines.append(
                f"Internal SSD {model.ssd.used_gb:.2f} GB used, {model.ssd.free_gb:.2f} GB free"
                f" of {model.ssd.total_gb:.2f} GB"
            )
        else:
            lines.append("Internal SSD --")
    text = "".join(s.text for s in segments).strip()
    lines.extend(p.strip() for p in text.split("  ") if p.strip())
    return "\n".join(lines)


def has_blinking_critical(segments: list[TitleSegment]) -> bool:
    """True only when a temperature reading (not CPU/RAM/storage) is critical."""
    return any(s.severity == "critical" and s.blinkable for s in segments)


def render_menubar_title(
    health_results: dict[str, health.DriveHealth],
    therm: thermal.ThermalStatus,
    settings: dict | None = None,
    cpu_temp_c: float | None = None,
) -> str:
    """Plain-text rendering of the segments — kept for headless testing and
    as the fallback when PyObjC colour attributes aren't available."""
    settings = settings if settings is not None else _DEFAULT_SETTINGS
    segs = build_segments(health_results, therm, settings, cpu_temp_c)
    return "".join(s.text for s in segs)


_SEVERITY_COLOR_NAME = {
    # "ok" and "neutral" are left uncoloured (system default, adapts to
    # light/dark menu bar automatically) — colour only appears to flag
    # something worth noticing, not on every normal reading.
    "warn": "systemOrangeColor",
    "critical": "systemRedColor",
}


def _attributed_title(segments: list[TitleSegment], blink_off: bool = False):
    """Build an NSAttributedString with per-segment foreground colours.

    CPU/RAM/storage stay solid red when critical — they never blink. Only
    blinkable segments (temperature) flash: blink_off briefly reverts them to
    the default (unhighlighted) look, then the next frame turns them red
    again, giving temperature specifically an attention-grabbing flash.
    """
    from AppKit import NSColor, NSFont, NSFontAttributeName, NSForegroundColorAttributeName

    full = "".join(s.text for s in segments)
    attr = NSMutableAttributedString.alloc().initWithString_(full)
    # Same size as the CPU/RAM/SSD graphics so the whole strip reads evenly.
    attr.addAttribute_value_range_(
        NSFontAttributeName, NSFont.systemFontOfSize_(menubar_render.TEXT_SIZE), NSRange(0, len(full))
    )
    pos = 0
    for seg in segments:
        skip = seg.blinkable and seg.severity == "critical" and blink_off
        color_name = _SEVERITY_COLOR_NAME.get(seg.severity)
        if color_name and not skip:
            color = getattr(NSColor, color_name)()
            attr.addAttribute_value_range_(
                NSForegroundColorAttributeName, color, NSRange(pos, len(seg.text))
            )
        pos += len(seg.text)
    return attr


class MenuBarApp(rumps.App):
    """rumps.App already adds a Quit item to the menu by default."""

    def __init__(self) -> None:
        self.settings = load_settings()
        self._dashboard = gui.DashboardPopoverController.alloc().init()
        self._dashboard.configure_controls(
            lambda: self.toggle_temps(),
            lambda: self.toggle_login_item(),
            lambda: rumps.quit_application(),
            settings=self.settings,
        )

        super().__init__(
            "MACSSD",
            title="MACSSD starting…",
            menu=[],
            quit_button=None,
        )

        self._health = health.HealthCollector()
        system.prime()
        self._blink_on = True
        self._last_segments: list[TitleSegment] = []
        self._compact_segments: list[TitleSegment] = []
        self._model = menubar_render.build_compact_model(None, None)
        self._storage: dict[str, StorageUsage] = {}
        self._storage_at = 0.0
        self._storage_busy = False

        self._timer = rumps.Timer(self.refresh, REFRESH_SECONDS)
        self._timer.start()
        self._blink_timer = rumps.Timer(self.blink, BLINK_SECONDS)
        self._blink_timer.start()
        self._status_click_target = _StatusItemClickTarget.alloc().init()
        self._status_click_target.callback = self.open_dashboard
        self._install_status_click_timer = rumps.Timer(self._install_status_click_handler, 0.1)
        self._install_status_click_timer.start()

    def open_dashboard(self, _sender=None) -> None:
        """Toggle the dashboard as a menu-bar attached popover."""
        status_button = getattr(getattr(self, "_nsapp", None), "nsstatusitem", None)
        anchor_view = status_button.button() if status_button is not None else None
        self._dashboard.toggle_attached_to(anchor_view)

    def _install_status_click_handler(self, timer) -> None:
        timer.stop()
        status_item = getattr(getattr(self, "_nsapp", None), "nsstatusitem", None)
        if status_item is None:
            return
        status_item.setMenu_(None)
        button = status_item.button()
        button.setTarget_(self._status_click_target)
        button.setAction_("callback:")

    def toggle_temps(self, sender=None) -> None:
        self.settings["show_temps"] = not self.settings.get("show_temps", True)
        save_settings(self.settings)
        self.refresh()

    def toggle_login_item(self, sender=None) -> None:
        if is_login_item_enabled():
            disable_login_item()
        else:
            ok, error = enable_login_item()
            if not ok:
                rumps.alert(title="Couldn't enable Start at Login", message=error)

    def refresh(self, _sender=None) -> None:
        # A single bad refresh (e.g. a transient OS syscall failure, a
        # smartctl hiccup) must never crash the menu bar or freeze it on a
        # stale error state — skip this tick and try again next time.
        try:
            health_results = self._health.sample()
            therm = thermal.read()
            cpu_temp_c = thermal.cpu_temp_c()
            self._last_segments = build_segments(health_results, therm, self.settings, cpu_temp_c)
            self._compact_segments = build_compact_temp_segments(
                health_results, therm, self.settings, cpu_temp_c
            )
            self._refresh_storage_async()
            self._model = menubar_render.build_compact_model(system.read(), self._storage)
            self._apply_title()
        except Exception:  # noqa: BLE001
            print("menubar refresh skipped, full error below:")
            traceback.print_exc()

    def _refresh_storage_async(self) -> None:
        """Read internal SSD used/free off the main thread, at most every 30s
        (drive discovery shells out to diskutil)."""
        now = time.monotonic()
        if self._storage_busy or now - self._storage_at < STORAGE_REFRESH_SECONDS:
            return
        self._storage_busy = True
        self._storage_at = now

        def work() -> None:
            try:
                self._storage = read_storage()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            finally:
                self._storage_busy = False

        threading.Thread(target=work, daemon=True).start()

    def blink(self, _sender=None) -> None:
        """Flash critical readings on/off (temperatures, and CPU/RAM/storage usage
        turning red); a no-op when nothing is critical."""
        if not (has_blinking_critical(self._last_segments) or self._model.has_critical):
            return
        self._blink_on = not self._blink_on
        self._apply_title()

    def _apply_title(self) -> None:
        try:
            item = self._nsapp.nsstatusitem
            button = item.button()
            button.setImage_(menubar_render.render_image(self._model, blink_off=not self._blink_on))
            button.setImagePosition_(2)  # NSImageLeft: graphics first, temps after
            attr = _attributed_title(self._compact_segments, blink_off=not self._blink_on)
            item.setAttributedTitle_(attr)
            button.setToolTip_(tooltip_text(self._last_segments, self._model))
        except Exception:  # noqa: BLE001
            # Fall back to plain text if PyObjC drawing/colouring isn't available.
            traceback.print_exc()
            m = self._model
            self.title = f"CPU {m.cpu.text} RAM {m.ram.text} " + "".join(
                s.text for s in self._compact_segments
            )


class _StatusItemClickTarget(NSObject):
    def callback_(self, _sender) -> None:
        self.callback()


def main() -> None:
    MenuBarApp().run()


if __name__ == "__main__":
    main()

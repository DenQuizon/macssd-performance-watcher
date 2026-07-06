"""MACSSD_Performance Watcher — macOS menu bar mode.

A second, lightweight view on top of the same collectors used by the
terminal dashboard (macssd/app.py). It reuses them as-is — no new backend
logic here, only presentation.

Run with: "./.venv/bin/python" -m macssd.menubar
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from pathlib import Path

import rumps
from Foundation import NSMutableAttributedString, NSObject, NSRange

from macssd import gui, severity
from macssd.collectors import health, system, thermal
from macssd.storage import (
    StorageUsage,
    disable_login_item,
    enable_login_item,
    is_login_item_enabled,
    read_storage,
)

REFRESH_SECONDS = 3.0
BLINK_SECONDS = 0.6  # how fast the title flashes when something is critical

_SETTINGS_PATH = Path.home() / ".macssd" / "menubar_settings.json"
_DEFAULT_SETTINGS = {"show_storage": True, "show_temps": True}


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
    if "DensMate" in name:
        return "Ext"
    return name[:3]


# Re-exported under the old private names so existing imports/tests are
# unaffected — the actual logic now lives in severity.py, shared with the
# hourly watcher, so the two never quietly disagree about thresholds.
_cpu_severity = severity.cpu_severity
_ram_severity = severity.ram_severity
_storage_severity = severity.storage_severity
_THERMAL_SEVERITY = severity.THERMAL_SEVERITY


@dataclass
class TitleSegment:
    text: str
    severity: str = "neutral"  # "ok" | "warn" | "critical" | "neutral"
    blinkable: bool = False  # only temperature segments flash when critical


def build_segments(
    stats: system.SystemStats,
    storage: dict[str, StorageUsage],
    health_results: dict[str, health.DriveHealth],
    therm: thermal.ThermalStatus,
    settings: dict,
) -> list[TitleSegment]:
    """Build the coloured menu bar segments. Storage/temps are optional per settings."""
    segs = [
        TitleSegment(f"CPU {stats.cpu_percent:.0f}%", _cpu_severity(stats.cpu_percent)),
        TitleSegment("  "),
        TitleSegment(f"RAM {stats.ram_percent:.0f}%", _ram_severity(stats.ram_percent)),
    ]

    if settings.get("show_storage", True):
        for name, s in storage.items():
            segs.append(TitleSegment("  "))
            label = _drive_label(name)
            if s.available and s.total_gb > 0:
                segs.append(TitleSegment(
                    f"{label} {s.used_gb:.0f}/{s.total_gb:.0f}GB",
                    _storage_severity(s.used_gb, s.total_gb),
                ))
            else:
                segs.append(TitleSegment(f"{label} --"))

    if settings.get("show_temps", True):
        if therm.available and therm.state:
            segs.append(TitleSegment("  "))
            segs.append(TitleSegment(
                f"Mac {therm.state}", _THERMAL_SEVERITY.get(therm.state, "neutral"), blinkable=True
            ))
        for name, h in health_results.items():
            segs.append(TitleSegment("  "))
            label = _drive_label(name)
            if h.available and h.temp_c is not None:
                sev = h.status if h.status in ("ok", "warn", "critical") else "neutral"
                segs.append(TitleSegment(f"{label} {h.temp_c}°C", sev, blinkable=True))
            else:
                segs.append(TitleSegment(f"{label} --"))

    return segs


def tooltip_text(segments: list[TitleSegment]) -> str:
    """One reading per line, for hovering over the (deliberately compact)
    menu bar title to see everything spelled out."""
    text = "".join(s.text for s in segments).strip()
    parts = [p.strip() for p in text.split("  ") if p.strip()]
    return "MACSSD_Performance Watcher\n" + "\n".join(parts)


def has_blinking_critical(segments: list[TitleSegment]) -> bool:
    """True only when a temperature reading (not CPU/RAM/storage) is critical."""
    return any(s.severity == "critical" and s.blinkable for s in segments)


def render_menubar_title(
    stats: system.SystemStats,
    health_results: dict[str, health.DriveHealth],
    therm: thermal.ThermalStatus,
    storage: dict[str, StorageUsage] | None = None,
    settings: dict | None = None,
) -> str:
    """Plain-text rendering of the segments — kept for headless testing and
    as the fallback when PyObjC colour attributes aren't available."""
    storage = storage if storage is not None else {}
    settings = settings if settings is not None else _DEFAULT_SETTINGS
    segs = build_segments(stats, storage, health_results, therm, settings)
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
    from AppKit import NSColor, NSForegroundColorAttributeName

    full = "".join(s.text for s in segments)
    attr = NSMutableAttributedString.alloc().initWithString_(full)
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
            lambda: self.toggle_storage(),
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

    def toggle_storage(self, sender=None) -> None:
        self.settings["show_storage"] = not self.settings.get("show_storage", True)
        save_settings(self.settings)
        self.refresh()

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
            stats = system.read()
            storage = read_storage()
            health_results = self._health.sample()
            therm = thermal.read()
            self._last_segments = build_segments(stats, storage, health_results, therm, self.settings)
            self._apply_title()
        except Exception:  # noqa: BLE001
            print("menubar refresh skipped, full error below:")
            traceback.print_exc()

    def blink(self, _sender=None) -> None:
        """Flash temperature segments on/off when critical; a no-op otherwise.
        CPU/RAM/storage never blink, even when critical — they stay solid red."""
        if not has_blinking_critical(self._last_segments):
            return
        self._blink_on = not self._blink_on
        self._apply_title()

    def _apply_title(self) -> None:
        try:
            attr = _attributed_title(self._last_segments, blink_off=not self._blink_on)
            self._nsapp.nsstatusitem.setAttributedTitle_(attr)
            self._nsapp.nsstatusitem.button().setToolTip_(tooltip_text(self._last_segments))
        except Exception:  # noqa: BLE001
            # Fall back to plain text if PyObjC colouring isn't available.
            self.title = "".join(s.text for s in self._last_segments)


class _StatusItemClickTarget(NSObject):
    def callback_(self, _sender) -> None:
        self.callback()


def main() -> None:
    MenuBarApp().run()


if __name__ == "__main__":
    main()

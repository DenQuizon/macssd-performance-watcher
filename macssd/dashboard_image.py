"""Renders a dashboard-style PNG snapshot for the hourly Telegram heartbeat.

The watcher runs headless via launchd with no GUI open, so this can't
literally screenshot the live popover — instead it draws a synthetic image
in the same dark-card style, using the same severity vocabulary as the rest
of the app (macssd.severity / DriveHealth.status), via Pillow.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

from macssd.collectors.health import HealthCollector
from macssd.collectors.system import read as system_read
from macssd.collectors.thermal import read as thermal_read
from macssd.severity import THERMAL_SEVERITY, cpu_severity, ram_severity, storage_severity
from macssd.storage import read_storage

_DRIVE_ORDER = ["Internal SSD", "DensMate SSD"]

_FONT_CANDIDATES = [
    "Arial Bold",
    "Helvetica-Bold",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.dfont",
]


def _load_fonts() -> tuple:
    for font_name in _FONT_CANDIDATES:
        try:
            return (
                ImageFont.truetype(font_name, 32),
                ImageFont.truetype(font_name, 18),
                ImageFont.truetype(font_name, 14),
            )
        except Exception:  # noqa: BLE001
            continue
    default = ImageFont.load_default()
    return default, default, default


def _color(severity: str) -> tuple[int, int, int]:
    return {
        "ok": (46, 204, 113),
        "warn": (230, 126, 34),
        "critical": (231, 76, 60),
    }.get(severity, (200, 200, 200))


def render_dashboard_image() -> str:
    sys_info = system_read()
    storage_data = read_storage()
    health_data = HealthCollector().sample(force=True)
    thermal_info = thermal_read()

    width, height = 640, 520
    image = Image.new("RGB", (width, height), (30, 30, 30))
    draw = ImageDraw.Draw(image)
    font_large, font_medium, font_small = _load_fonts()

    cpu_sev = cpu_severity(sys_info.cpu_percent)
    draw.rounded_rectangle([20, 20, 310, 150], radius=8, fill=(45, 45, 45))
    draw.text((35, 30), "CPU Usage", fill=(200, 200, 200), font=font_medium)
    draw.text((35, 55), f"{sys_info.cpu_percent:.1f}%", fill=_color(cpu_sev), font=font_large)
    draw.text(
        (35, 110),
        f"Load: {sys_info.load_1:.2f}  {sys_info.load_5:.2f}  {sys_info.load_15:.2f}",
        fill=(150, 150, 150),
        font=font_small,
    )

    ram_sev = ram_severity(sys_info.ram_percent)
    draw.rounded_rectangle([330, 20, 620, 150], radius=8, fill=(45, 45, 45))
    draw.text((345, 30), "Memory Usage", fill=(200, 200, 200), font=font_medium)
    draw.text((345, 55), f"{sys_info.ram_percent:.1f}%", fill=_color(ram_sev), font=font_large)
    draw.text(
        (345, 110),
        f"Used: {sys_info.ram_used_gb:.1f} / {sys_info.ram_total_gb:.1f} GB",
        fill=(150, 150, 150),
        font=font_small,
    )

    storage_boxes = [(20, 170, 310, 300), (330, 170, 620, 300)]
    for name, box in zip(_DRIVE_ORDER, storage_boxes):
        x0, y0, x1, y1 = box
        draw.rounded_rectangle(box, radius=8, fill=(45, 45, 45))
        drv = storage_data.get(name)
        draw.text((x0 + 15, y0 + 10), name, fill=(200, 200, 200), font=font_medium)
        if drv is None or not drv.available:
            draw.text((x0 + 15, y0 + 35), "Offline", fill=(231, 76, 60), font=font_large)
            continue
        drv_sev = storage_severity(drv.used_gb, drv.total_gb)
        draw.text(
            (x0 + 15, y0 + 35),
            f"{drv.used_gb:.1f} / {drv.total_gb:.1f} GB",
            fill=_color(drv_sev),
            font=font_large,
        )

    temp_boxes = [(20, 320, 310, 450), (330, 320, 620, 450)]
    for name, box in zip(_DRIVE_ORDER, temp_boxes):
        x0, y0, x1, y1 = box
        draw.rounded_rectangle(box, radius=8, fill=(45, 45, 45))
        h = health_data.get(name)
        draw.text((x0 + 15, y0 + 10), f"{name} temp", fill=(200, 200, 200), font=font_medium)
        if h is None:
            draw.text((x0 + 15, y0 + 35), "Not available", fill=(150, 150, 150), font=font_medium)
            continue
        color = _color(h.status)
        if h.temp_c is not None:
            draw.text((x0 + 15, y0 + 35), f"{h.temp_c}°C", fill=color, font=font_large)
        else:
            draw.text((x0 + 15, y0 + 35), "not available", fill=color, font=font_medium)
        reason = f"Wear: {h.wear_pct}%" if h.wear_pct is not None else h.reason
        draw.text((x0 + 15, y0 + 90), reason, fill=(150, 150, 150), font=font_small)

    thermal_sev = THERMAL_SEVERITY.get(thermal_info.state, "unknown")
    draw.text(
        (20, 475),
        f"Thermal state: {thermal_info.state} ({thermal_info.reason})",
        fill=_color(thermal_sev),
        font=font_medium,
    )

    out_dir = os.path.join(os.path.expanduser("~"), ".macssd")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dashboard_snapshot.png")
    tmp_path = out_path + ".tmp"
    image.save(tmp_path, "PNG")
    os.replace(tmp_path, out_path)  # atomic swap — a reader never sees a partial file
    return out_path

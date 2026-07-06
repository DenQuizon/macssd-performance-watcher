"""Overall system thermal pressure, via macOS's public ProcessInfo API.

True fan RPM is not available on Apple Silicon without either root privileges
(powermetrics) or Apple's undocumented private SMC interface, so this uses the
officially supported alternative instead: NSProcessInfo.thermalState(), the
same signal macOS itself uses to decide when to throttle. It answers "is this
Mac thermally stressed" reliably, even though it can't report a raw RPM number.

Apple's documented enum (ProcessInfoThermalState):
  0 = nominal   -- no thermal pressure
  1 = fair      -- slightly elevated, no action needed
  2 = serious   -- fans at or near maximum, performance may be reduced
  3 = critical  -- system is actively cooling itself, expect slowdown
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from Foundation import NSProcessInfo
    _AVAILABLE = True
except ImportError:  # pyobjc not installed, or not on macOS
    _AVAILABLE = False

_STATES = {
    0: ("nominal", "Running cool, no thermal pressure."),
    1: ("fair", "Slightly warm, but nothing to worry about."),
    2: ("serious", "Working hard to stay cool — fans are likely near maximum."),
    3: ("critical", "Overheating — macOS is actively slowing things down to cool off."),
}


@dataclass
class ThermalStatus:
    available: bool
    state: str = "unknown"
    reason: str = "Thermal state is not available on this machine."


def available() -> bool:
    return _AVAILABLE


def read() -> ThermalStatus:
    """Return the current system-wide thermal pressure state."""
    if not _AVAILABLE:
        return ThermalStatus(False)
    raw = NSProcessInfo.processInfo().thermalState()
    state, reason = _STATES.get(raw, ("unknown", f"Unrecognised thermal state ({raw})."))
    return ThermalStatus(True, state, reason)

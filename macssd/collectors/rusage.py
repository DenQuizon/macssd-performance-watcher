"""Per-process disk bytes via Apple's proc_pid_rusage (libSystem, ctypes).

psutil cannot report per-process disk I/O on macOS. Apple exposes cumulative
bytes read/written per process through proc_pid_rusage() with the
RUSAGE_INFO_V2 flavor, whose struct ends with the two disk-I/O counters we want.

Works without root for the current user's own processes; returns None when the
process is not accessible (another user, or already gone).
"""

from __future__ import annotations

import ctypes

RUSAGE_INFO_V2 = 2


class _RUsageInfoV2(ctypes.Structure):
    # Field order mirrors <sys/resource.h> struct rusage_info_v2. The last two
    # fields are the cumulative disk-I/O byte counters.
    _fields_ = [
        ("ri_uuid", ctypes.c_uint8 * 16),
        ("ri_user_time", ctypes.c_uint64),
        ("ri_system_time", ctypes.c_uint64),
        ("ri_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_interrupt_wkups", ctypes.c_uint64),
        ("ri_pageins", ctypes.c_uint64),
        ("ri_wired_size", ctypes.c_uint64),
        ("ri_resident_size", ctypes.c_uint64),
        ("ri_phys_footprint", ctypes.c_uint64),
        ("ri_proc_start_abstime", ctypes.c_uint64),
        ("ri_proc_exit_abstime", ctypes.c_uint64),
        ("ri_child_user_time", ctypes.c_uint64),
        ("ri_child_system_time", ctypes.c_uint64),
        ("ri_child_pkg_idle_wkups", ctypes.c_uint64),
        ("ri_child_interrupt_wkups", ctypes.c_uint64),
        ("ri_child_pageins", ctypes.c_uint64),
        ("ri_child_elapsed_abstime", ctypes.c_uint64),
        ("ri_diskio_bytesread", ctypes.c_uint64),
        ("ri_diskio_byteswritten", ctypes.c_uint64),
    ]


try:
    _libc = ctypes.CDLL(None, use_errno=True)
    _proc_pid_rusage = _libc.proc_pid_rusage
    _proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    _proc_pid_rusage.restype = ctypes.c_int
except (OSError, AttributeError):  # not macOS / symbol missing
    _proc_pid_rusage = None


def available() -> bool:
    """True if proc_pid_rusage could be loaded (i.e. we are on macOS)."""
    return _proc_pid_rusage is not None


def disk_io(pid: int) -> tuple[int, int] | None:
    """Return (bytes_read, bytes_written) cumulative for pid, or None if denied/gone."""
    if _proc_pid_rusage is None:
        return None
    info = _RUsageInfoV2()
    if _proc_pid_rusage(pid, RUSAGE_INFO_V2, ctypes.byref(info)) != 0:
        return None
    return info.ri_diskio_bytesread, info.ri_diskio_byteswritten

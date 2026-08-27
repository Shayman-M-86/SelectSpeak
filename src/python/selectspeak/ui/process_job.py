"""Tie a child process's lifetime to this one with a Windows job object.

The player is a separate process, so nothing in Windows stops it outliving the
backend that launched it. Terminating it during shutdown covers the ordinary
exit, but not a crash, a kill from Task Manager, or anything else that skips
cleanup - and an orphaned player has no backend left to talk to.

A job object closes that gap without any cooperation from the child: with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, Windows terminates everything in the job
when the last handle to it goes away, which happens when this process exits by
any means.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.POINTER(wintypes.ULONG)),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class ChildProcessJob:
    """A job object that kills its members when this process goes away.

    The handle is deliberately held for the lifetime of the instance: the kill
    happens when the last handle closes, so releasing it early would defeat the
    purpose. Every failure is logged and swallowed, because losing the job only
    costs the guarantee, and the ordinary shutdown path still terminates the
    player itself.
    """

    def __init__(self) -> None:
        self._handle: int | None = None
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._create()

    def _create(self) -> None:
        kernel32 = self._kernel32
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            logger.warning("process_job.create_failed error=%s", ctypes.get_last_error())
            return

        limits = _JobObjectExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        if not kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            logger.warning("process_job.configure_failed error=%s", ctypes.get_last_error())
            kernel32.CloseHandle(handle)
            return

        self._handle = handle
        logger.debug("process_job.created")

    @property
    def available(self) -> bool:
        return self._handle is not None

    def assign(self, pid: int) -> bool:
        """Put a process into the job, returning whether it joined."""
        if self._handle is None:
            return False

        kernel32 = self._kernel32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        process = kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not process:
            logger.warning("process_job.open_failed pid=%s error=%s", pid, ctypes.get_last_error())
            return False
        try:
            kernel32.AssignProcessToJobObject.argtypes = [
                wintypes.HANDLE,
                wintypes.HANDLE,
            ]
            if not kernel32.AssignProcessToJobObject(self._handle, process):
                logger.warning(
                    "process_job.assign_failed pid=%s error=%s",
                    pid,
                    ctypes.get_last_error(),
                )
                return False
        finally:
            kernel32.CloseHandle(process)

        logger.info("process_job.assigned pid=%s", pid)
        return True

"""Owned process-group handling for bounded adapter invocations."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any


class ProcessGroupOwner:
    """Own and verify one direct child plus its platform process group."""

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        self.process = process
        self.pid = int(process.pid)
        self.group_id = self.pid if os.name == "posix" else None
        self.mode = "posix-session" if os.name == "posix" else "windows-job"
        self.attestation = "ATTESTED" if os.name == "posix" else "UNAVAILABLE"
        self._job_handle: int | None = None
        if os.name == "nt":
            self._job_handle = _create_windows_job(process)
            if self._job_handle is not None:
                self.attestation = "ATTESTED"

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "attestation": self.attestation,
            "groupKnown": self.group_id is not None or self._job_handle is not None,
        }

    def terminate(self, *, grace_seconds: float) -> dict[str, Any]:
        """Terminate the owned group and return bounded cleanup evidence."""

        escalation = "none"
        if self.process.poll() is None:
            if os.name == "posix":
                try:
                    os.killpg(self.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                if not _wait_process(self.process, grace_seconds):
                    escalation = "SIGKILL"
                    try:
                        os.killpg(self.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    _wait_process(self.process, grace_seconds)
            elif self._job_handle is not None:
                _terminate_windows_job(self._job_handle)
                _wait_process(self.process, grace_seconds)
                escalation = "job-terminate"
            else:
                self.process.terminate()
                if not _wait_process(self.process, grace_seconds):
                    escalation = "terminate"
                    self.process.kill()
                    _wait_process(self.process, grace_seconds)
        cleanup = self.verify()
        cleanup["escalation"] = escalation
        cleanup["graceSeconds"] = grace_seconds
        return cleanup

    def verify(self) -> dict[str, Any]:
        if os.name == "posix":
            alive = _posix_group_has_live_processes(self.pid)
            if alive is None:
                try:
                    os.killpg(self.pid, 0)
                    alive = True
                except ProcessLookupError:
                    alive = False
                except PermissionError:
                    alive = True
            return {
                "status": "BLOCKED" if alive else "PASS",
                "attestation": self.attestation,
                "mode": self.mode,
                "knownDescendantsGone": not alive,
                "directChildExited": self.process.poll() is not None,
            }
        if self._job_handle is None:
            return {
                "status": "BLOCKED",
                "attestation": "UNAVAILABLE",
                "mode": self.mode,
                "knownDescendantsGone": False,
                "directChildExited": self.process.poll() is not None,
                "reason": "windows-job-attestation-unavailable",
            }
        active = _windows_job_active_processes(self._job_handle)
        return {
            "status": "PASS" if active == 0 else "BLOCKED",
            "attestation": self.attestation,
            "mode": self.mode,
            "knownDescendantsGone": active == 0,
            "activeProcessCount": active,
            "directChildExited": self.process.poll() is not None,
        }

    def close(self) -> None:
        if self._job_handle is not None:
            _close_windows_handle(self._job_handle)
            self._job_handle = None


def popen_group_kwargs() -> dict[str, Any]:
    """Return shell-free group ownership flags for ``subprocess.Popen``."""

    if os.name == "posix":
        return {"start_new_session": True}
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return {"creationflags": creation_flags}


def _wait_process(process: subprocess.Popen[Any], timeout: float) -> bool:
    try:
        process.wait(timeout=max(0.01, timeout))
        return True
    except subprocess.TimeoutExpired:
        return False


def _create_windows_job(process: subprocess.Popen[Any]) -> int | None:
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.INT, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_uint64), ("WriteOperationCount", ctypes.c_uint64), ("OtherOperationCount", ctypes.c_uint64), ("ReadTransferCount", ctypes.c_uint64), ("WriteTransferCount", ctypes.c_uint64), ("OtherTransferCount", ctypes.c_uint64)]

        class BASIC_LIMITS(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED_LIMITS(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC_LIMITS), ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        limits = EXTENDED_LIMITS()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            kernel32.CloseHandle(handle)
            return None
        process_handle_value = getattr(process._handle, "value", process._handle)
        if not process_handle_value:
            kernel32.CloseHandle(handle)
            return None
        if not kernel32.AssignProcessToJobObject(handle, wintypes.HANDLE(process_handle_value)):
            kernel32.CloseHandle(handle)
            return None
        handle_value = getattr(handle, "value", handle)
        return int(handle_value) if handle_value else None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _terminate_windows_job(handle: int) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject(handle, 1)
    except (AttributeError, OSError, TypeError, ValueError):
        return


def _windows_job_active_processes(handle: int) -> int | None:
    # Querying the accounting structure keeps descendant verification inside
    # the process; no taskkill/tasklist helper is spawned.
    try:
        import ctypes
        from ctypes import wintypes

        class ACCOUNTING(ctypes.Structure):
            _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64), ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64), ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD), ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

        info = ACCOUNTING()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.INT, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        if not kernel32.QueryInformationJobObject(handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
            return None
        return int(info.ActiveProcesses)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _close_windows_handle(handle: int) -> None:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return


def _posix_group_has_live_processes(group_id: int) -> bool | None:
    """Return live-member state when Linux ``/proc`` permits exact checking.

    ``killpg(..., 0)`` also reports a group containing only zombies as present.
    Linux exposes the process state and process-group id in ``/proc/<pid>/stat``;
    ignoring ``Z`` members prevents a false cleanup blocker while retaining a
    fail-closed fallback when the process table cannot be inspected.
    """

    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return None
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="ascii")
        except FileNotFoundError:
            continue
        except OSError:
            return None
        try:
            _, remainder = stat.rsplit(")", 1)
            fields = remainder.strip().split()
            state = fields[0]
            process_group = int(fields[2])
        except (IndexError, ValueError):
            return None
        if process_group == group_id and state != "Z":
            return True
    return False

"""Bounded, dependency-free process resource measurements."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


class ProcessTelemetry:
    """Capture monotonic wall time and best-effort local process facts."""

    def __init__(self, *, pid: int | None, group_id: int | None = None) -> None:
        self.pid = pid
        self.group_id = group_id
        self.started_ns = time.monotonic_ns()
        self._peak_memory_mb: float | None = None
        self._peak_process_count: int | None = None
        self._start_cpu_ms: float | None = None
        self._last_cpu_ms: float | None = None
        self._cpu_source = "none"
        self._memory_source = "none"
        self._process_source = "none"
        self._sample_count = 0
        self.sample()

    def sample(self) -> dict[str, Any]:
        snapshot = capture_process_snapshot(self.pid, self.group_id)
        self._sample_count += 1
        cpu = snapshot.get("cpuMs")
        if isinstance(cpu, (int, float)):
            if self._start_cpu_ms is None:
                self._start_cpu_ms = float(cpu)
            self._last_cpu_ms = float(cpu)
            self._cpu_source = str(snapshot.get("cpuSource") or "local")
        memory = snapshot.get("memoryMb")
        if isinstance(memory, (int, float)):
            self._peak_memory_mb = max(self._peak_memory_mb or 0.0, float(memory))
            self._memory_source = str(snapshot.get("memorySource") or "local")
        process_count = snapshot.get("processCount")
        if isinstance(process_count, int):
            self._peak_process_count = max(self._peak_process_count or 0, process_count)
            self._process_source = str(snapshot.get("processSource") or "local")
        return snapshot

    def finish(self) -> dict[str, Any]:
        self.sample()
        elapsed_ms = max(0, int((time.monotonic_ns() - self.started_ns) / 1_000_000))
        cpu_ms = None
        if self._last_cpu_ms is not None and self._start_cpu_ms is not None:
            cpu_ms = max(0.0, self._last_cpu_ms - self._start_cpu_ms)
        return {
            "elapsedMs": elapsed_ms,
            "cpuMs": _metric(cpu_ms, "ATTESTED" if cpu_ms is not None else "UNAVAILABLE", self._cpu_source, "ms"),
            "peakMemoryMb": _metric(self._peak_memory_mb, "ATTESTED" if self._peak_memory_mb is not None else "UNAVAILABLE", self._memory_source, "MB"),
            "processCount": _metric(self._peak_process_count, "ATTESTED" if self._peak_process_count is not None else "UNAVAILABLE", self._process_source, "processes"),
            "sampleCount": self._sample_count,
        }


def capture_process_snapshot(pid: int | None, group_id: int | None = None) -> dict[str, Any]:
    """Read only local OS data; unavailable platforms return explicit gaps."""

    if pid is None:
        return {}
    if os.name == "posix":
        proc = Path("/proc") / str(pid)
        if proc.exists():
            snapshot = _linux_snapshot(proc, group_id)
            if snapshot:
                return snapshot
        # resource is portable across Unix, but RUSAGE_CHILDREN is aggregate;
        # expose it as an estimate rather than claiming process precision.
        try:
            import resource

            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            return {
                "cpuMs": (usage.ru_utime + usage.ru_stime) * 1000.0,
                "cpuSource": "resource.rusage_children",
                "memoryMb": _rusage_memory_mb(usage.ru_maxrss),
                "memorySource": "resource.rusage_children",
                "processCount": 1,
                "processSource": "direct-child",
            }
        except (ImportError, OSError, AttributeError):
            return {}
    return {"processCount": 1, "processSource": "direct-child"}


def _linux_snapshot(proc: Path, group_id: int | None) -> dict[str, Any]:
    try:
        stat = (proc / "stat").read_text(encoding="utf-8")
        right = stat.rsplit(")", 1)[1].split()
        # Fields 14 and 15 in procfs become indexes 11 and 12 after state.
        ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        cpu_ms = (int(right[11]) + int(right[12])) * 1000.0 / ticks
        memory_mb = None
        for line in (proc / "status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmHWM:") or line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    memory_mb = max(memory_mb or 0.0, int(parts[1]) / 1024.0)
        count = _linux_group_count(group_id) if group_id is not None else 1
        return {
            "cpuMs": cpu_ms,
            "cpuSource": "procfs",
            "memoryMb": memory_mb,
            "memorySource": "procfs",
            "processCount": count,
            "processSource": "procfs-group" if group_id is not None else "procfs-direct",
        }
    except (OSError, ValueError, IndexError, KeyError):
        return {}


def _linux_group_count(group_id: int | None) -> int:
    if group_id is None:
        return 1
    count = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            right = stat.rsplit(")", 1)[1].split()
            if int(right[2]) == group_id:
                count += 1
        except (OSError, ValueError, IndexError):
            continue
    return count


def _rusage_memory_mb(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    # macOS reports bytes; Linux reports KiB. This value is explicitly an
    # aggregate fallback and is never labelled as an exact process peak.
    return float(value) / (1024.0 * 1024.0 if value > 1024 * 1024 else 1024.0)


def _metric(value: Any, availability: str, source: str, unit: str) -> dict[str, Any]:
    return {
        "value": round(float(value), 3) if isinstance(value, (int, float)) else None,
        "availability": availability,
        "source": source if isinstance(source, str) and source else "none",
        "unit": unit,
    }

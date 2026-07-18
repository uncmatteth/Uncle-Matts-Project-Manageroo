from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _total_memory_bytes() -> int | None:
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
    if os.name == "nt":

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        except (AttributeError, OSError):
            return None
    return None


def _nvidia_gpus() -> list[dict[str, Any]]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    gpus: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",", 1)]
        if len(parts) != 2:
            continue
        try:
            memory_mib = int(parts[1])
        except ValueError:
            memory_mib = 0
        gpus.append(
            {
                "name": parts[0],
                "vram_mib": memory_mib,
                "vram_gib": round(memory_mib / 1024, 1) if memory_mib else None,
            }
        )
    return gpus


def _capacity_class(*, ram_gib: float | None, max_vram_gib: float | None) -> str:
    if ram_gib is not None and ram_gib >= 64 and (max_vram_gib or 0) >= 16:
        return "high-capacity-local"
    if ram_gib is not None and ram_gib >= 32:
        return "strong-general-purpose"
    if ram_gib is not None and ram_gib >= 16:
        return "standard-development"
    return "constrained-or-unknown"


def host_capacity(repo: Path | None = None) -> dict[str, Any]:
    target = (repo or Path.cwd()).expanduser().resolve()
    disk_target = target if target.exists() else Path.cwd()
    disk = shutil.disk_usage(disk_target)
    memory_bytes = _total_memory_bytes()
    ram_gib = round(memory_bytes / (1024**3), 1) if memory_bytes else None
    gpus = _nvidia_gpus()
    max_vram_gib = max(
        (
            float(item["vram_gib"])
            for item in gpus
            if item.get("vram_gib") is not None
        ),
        default=None,
    )
    cpu_count = os.cpu_count() or 1
    ram_parallel = max(1, int(ram_gib // 8)) if ram_gib is not None else 4
    recommended_parallel = max(
        1,
        min(8, max(1, cpu_count // 2), ram_parallel),
    )
    warnings: list[str] = []
    free_disk_gib = round(disk.free / (1024**3), 1)
    if free_disk_gib < 10:
        warnings.append(
            "Less than 10 GiB of free disk space is available for isolated workspaces and builds."
        )
    if ram_gib is not None and ram_gib < 8:
        warnings.append(
            "Less than 8 GiB of system RAM was detected; large builds or parallel workers "
            "may be unreliable."
        )

    return {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "cpu": {
            "logical_cores": cpu_count,
            "processor": platform.processor() or "unknown",
        },
        "memory": {
            "total_bytes": memory_bytes,
            "total_gib": ram_gib,
        },
        "gpu": {
            "nvidia_detected": bool(gpus),
            "devices": gpus,
            "max_vram_gib": max_vram_gib,
            "note": (
                "GPU detection is best-effort. NVIDIA devices are read through nvidia-smi; "
                "other accelerators may not be reported automatically."
            ),
        },
        "disk": {
            "path": str(disk_target),
            "total_gib": round(disk.total / (1024**3), 1),
            "free_gib": free_disk_gib,
        },
        "recommendations": {
            "capacity_class": _capacity_class(
                ram_gib=ram_gib,
                max_vram_gib=max_vram_gib,
            ),
            "max_parallel_agent_calls": recommended_parallel,
            "reason": (
                "Conservative recommendation based on logical CPU count and roughly one "
                "8 GiB RAM slice per concurrent worker when RAM is detectable. "
                "Repository-specific build processes may require less concurrency."
            ),
        },
        "warnings": warnings,
    }


def format_capacity(profile: dict[str, Any]) -> str:
    memory = profile["memory"].get("total_gib")
    gpu = profile["gpu"]
    platform_text = (
        f"{profile['platform']['system']} {profile['platform']['release']} "
        f"({profile['platform']['machine']})"
    )
    lines = [
        "SYSTEM CAPACITY",
        f"Platform: {platform_text}",
        f"CPU: {profile['cpu']['logical_cores']} logical cores",
        f"RAM: {memory if memory is not None else 'unknown'} GiB",
        f"Disk free: {profile['disk']['free_gib']} GiB",
    ]
    if gpu.get("devices"):
        for device in gpu["devices"]:
            vram = device.get("vram_gib") or "unknown"
            lines.append(f"GPU: {device['name']} ({vram} GiB VRAM)")
    else:
        lines.append("GPU: no NVIDIA GPU detected automatically")
    lines.append(f"Capacity class: {profile['recommendations']['capacity_class']}")
    lines.append(
        "Recommended max parallel agent calls: "
        + str(profile["recommendations"]["max_parallel_agent_calls"])
    )
    for warning in profile.get("warnings", []):
        lines.append("WARNING: " + warning)
    return "\n".join(lines) + "\n"


def profile_json(profile: dict[str, Any]) -> str:
    return json.dumps(profile, indent=2, sort_keys=True)

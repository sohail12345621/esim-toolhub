"""Operating system, architecture, Python and PATH detection.

All inputs (platform module, environment, ``which``, os-release location) are
injectable so tests can simulate Windows, Linux and macOS on any host.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import platform as _platform
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from esim_toolhub.core.models import OSFamily, PathIssue, SystemInfo

Which = Callable[[str], "str | None"]

_ARCH_ALIASES = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "x64": "x86_64",
    "em64t": "x86_64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv8l": "arm64",
    "i386": "x86",
    "i486": "x86",
    "i586": "x86",
    "i686": "x86",
    "x86": "x86",
    "armv7l": "armv7",
    "armv7": "armv7",
    "riscv64": "riscv64",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
}

PACKAGE_MANAGERS: dict[OSFamily, tuple[str, ...]] = {
    OSFamily.WINDOWS: ("winget", "choco"),
    OSFamily.LINUX: ("apt-get", "dnf", "pacman"),
    OSFamily.MACOS: ("brew",),
}
# Executable name -> logical package-manager name used in tools.yaml.
_PM_LOGICAL = {"apt-get": "apt"}


def normalize_arch(machine: str) -> str:
    return _ARCH_ALIASES.get(machine.strip().lower(), machine.strip().lower() or "unknown")


def detect_os_family(system_name: str) -> OSFamily:
    name = system_name.strip().lower()
    if name == "windows" or name.startswith(("cygwin", "msys", "mingw")):
        return OSFamily.WINDOWS
    if name == "linux":
        return OSFamily.LINUX
    if name == "darwin":
        return OSFamily.MACOS
    return OSFamily.UNKNOWN


def parse_os_release(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def windows_marketing_name(version: str, release: str) -> str:
    """platform.release() reports '10' on Windows 11 for older Pythons; use the build number."""
    try:
        build = int(version.split(".")[2])
    except (IndexError, ValueError):
        return f"Windows {release}".strip()
    if build >= 22000:
        return "Windows 11"
    return f"Windows {release or '10'}"


def _is_admin(os_family: OSFamily) -> bool:
    try:
        if os_family is OSFamily.WINDOWS:
            windll = getattr(ctypes, "windll", None)
            return bool(windll.shell32.IsUserAnAdmin()) if windll is not None else False
        return hasattr(os, "geteuid") and os.geteuid() == 0
    except (AttributeError, OSError):
        return False


def split_path(value: str, os_family: OSFamily) -> tuple[str, ...]:
    sep = ";" if os_family is OSFamily.WINDOWS else ":"
    return tuple(p for p in value.split(sep) if p.strip())


def inspect_path(
    entries: Iterable[str],
    os_family: OSFamily,
    exists: Callable[[str], bool] = os.path.isdir,
) -> list[PathIssue]:
    """Report PATH entries that are missing, duplicated or relative."""
    issues: list[PathIssue] = []
    seen: set[str] = set()
    for entry in entries:
        key = (
            os.path.normcase(entry.rstrip("\\/"))
            if os_family is OSFamily.WINDOWS
            else entry.rstrip("/")
        )
        if os_family is OSFamily.WINDOWS:
            key = key.lower()
        if key in seen:
            issues.append(PathIssue(entry, "duplicate entry"))
            continue
        seen.add(key)
        expanded = os.path.expandvars(entry)
        if os_family is OSFamily.WINDOWS:
            is_abs = (len(expanded) > 1 and expanded[1] == ":") or expanded.startswith("\\\\")
        else:
            is_abs = expanded.startswith("/")
        if not is_abs:
            issues.append(PathIssue(entry, "relative entry (security risk: resolves against CWD)"))
        elif not exists(expanded):
            issues.append(PathIssue(entry, "directory does not exist"))
    return issues


def detect_system(
    platform_module: ModuleType | Any = _platform,
    env: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    os_release_path: Path = Path("/etc/os-release"),
    is_admin: Callable[[OSFamily], bool] = _is_admin,
    python_version: str | None = None,
    python_executable: str | None = None,
) -> SystemInfo:
    env = os.environ if env is None else env
    os_family = detect_os_family(platform_module.system())
    machine = platform_module.machine() or ""
    release = platform_module.release() or ""
    version = platform_module.version() or ""

    distro_id = ""
    distro_like: tuple[str, ...] = ()
    is_wsl = False
    if os_family is OSFamily.WINDOWS:
        os_name = windows_marketing_name(version, release)
        os_version = version
        # Windows on ARM running x64 Python reports AMD64; trust the native env var.
        machine = env.get("PROCESSOR_ARCHITEW6432") or machine
    elif os_family is OSFamily.LINUX:
        info: dict[str, str] = {}
        with contextlib.suppress(OSError):
            info = parse_os_release(os_release_path.read_text("utf-8"))
        os_name = info.get("PRETTY_NAME") or f"Linux {release}"
        os_version = info.get("VERSION_ID", release)
        distro_id = info.get("ID", "").lower()
        distro_like = tuple(info.get("ID_LIKE", "").lower().split())
        is_wsl = "microsoft" in release.lower() or "WSL_DISTRO_NAME" in env
    elif os_family is OSFamily.MACOS:
        mac_ver = platform_module.mac_ver()[0] if hasattr(platform_module, "mac_ver") else ""
        os_name = f"macOS {mac_ver}".strip()
        os_version = mac_ver or release
    else:
        os_name = platform_module.system() or "Unknown"
        os_version = release

    package_managers: dict[str, str] = {}
    for exe in PACKAGE_MANAGERS.get(os_family, ()):
        found = which(exe)
        if found:
            package_managers[_PM_LOGICAL.get(exe, exe)] = found

    return SystemInfo(
        os_family=os_family,
        os_name=os_name,
        os_version=os_version,
        architecture=normalize_arch(machine),
        machine=machine,
        python_version=python_version or _platform.python_version(),
        python_executable=python_executable or sys.executable,
        distro_id=distro_id,
        distro_like=distro_like,
        is_wsl=is_wsl,
        is_admin=is_admin(os_family),
        path_entries=split_path(env.get("PATH", "") or env.get("Path", ""), os_family),
        package_managers=package_managers,
    )

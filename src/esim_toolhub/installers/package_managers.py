"""Stateless command builders for supported native package managers.

Every package name/ID is validated before being placed into an argument list.
No shell strings are ever constructed.
"""

from __future__ import annotations

import re

from esim_toolhub.core.exceptions import UnsupportedPlatformError
from esim_toolhub.core.models import InstallMethod, MethodType
from esim_toolhub.core.runner import CommandRunner
from esim_toolhub.detection.version import Version, extract_version
from esim_toolhub.security.validation import validate_package_id

_APT_CANDIDATE = re.compile(r"Candidate:\s*(?:\d+:)?(\d+(?:\.\d+)*)")
_WINGET_VERSION = re.compile(r"Version:\s*(\d+(?:\.\d+)*)")


def _sudo_prefix(use_sudo: bool) -> tuple[str, ...]:
    return ("sudo", "-n") if use_sudo else ()


def refresh_command(method: InstallMethod, *, use_sudo: bool = False) -> tuple[str, ...] | None:
    if method.type is MethodType.APT:
        return (*_sudo_prefix(use_sudo), "apt-get", "update")
    return None


def install_command(method: InstallMethod, *, use_sudo: bool = False) -> tuple[str, ...]:
    pkg = validate_package_id(method.package or "")
    prefix = _sudo_prefix(use_sudo)
    if method.type is MethodType.APT:
        return (*prefix, "apt-get", "install", "-y", "--no-install-recommends", pkg)
    if method.type is MethodType.DNF:
        return (*prefix, "dnf", "install", "-y", pkg)
    if method.type is MethodType.PACMAN:
        return (*prefix, "pacman", "-S", "--noconfirm", "--needed", pkg)
    if method.type is MethodType.WINGET:
        return (
            "winget",
            "install",
            "--id",
            pkg,
            "--exact",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
        )
    if method.type is MethodType.CHOCO:
        return ("choco", "install", pkg, "-y", "--no-progress")
    if method.type is MethodType.BREW:
        return ("brew", "install", "--cask", pkg) if method.cask else ("brew", "install", pkg)
    raise UnsupportedPlatformError(f"Not a package manager method: {method.type.value}")


def upgrade_command(method: InstallMethod, *, use_sudo: bool = False) -> tuple[str, ...]:
    pkg = validate_package_id(method.package or "")
    prefix = _sudo_prefix(use_sudo)
    if method.type is MethodType.APT:
        return (*prefix, "apt-get", "install", "-y", "--only-upgrade", pkg)
    if method.type is MethodType.DNF:
        return (*prefix, "dnf", "upgrade", "-y", pkg)
    if method.type is MethodType.PACMAN:
        return (*prefix, "pacman", "-S", "--noconfirm", pkg)
    if method.type is MethodType.WINGET:
        return (
            "winget",
            "upgrade",
            "--id",
            pkg,
            "--exact",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--disable-interactivity",
        )
    if method.type is MethodType.CHOCO:
        return ("choco", "upgrade", pkg, "-y", "--no-progress")
    if method.type is MethodType.BREW:
        return ("brew", "upgrade", "--cask", pkg) if method.cask else ("brew", "upgrade", pkg)
    raise UnsupportedPlatformError(f"Not a package manager method: {method.type.value}")


def uninstall_command(method: InstallMethod, *, use_sudo: bool = False) -> tuple[str, ...]:
    pkg = validate_package_id(method.package or "")
    prefix = _sudo_prefix(use_sudo)
    if method.type is MethodType.APT:
        return (*prefix, "apt-get", "remove", "-y", pkg)
    if method.type is MethodType.DNF:
        return (*prefix, "dnf", "remove", "-y", pkg)
    if method.type is MethodType.PACMAN:
        return (*prefix, "pacman", "-R", "--noconfirm", pkg)
    if method.type is MethodType.WINGET:
        return ("winget", "uninstall", "--id", pkg, "--exact", "--disable-interactivity")
    if method.type is MethodType.CHOCO:
        return ("choco", "uninstall", pkg, "-y")
    if method.type is MethodType.BREW:
        return ("brew", "uninstall", "--cask", pkg) if method.cask else ("brew", "uninstall", pkg)
    raise UnsupportedPlatformError(f"Not a package manager method: {method.type.value}")


def query_available_version(
    runner: CommandRunner, method: InstallMethod, timeout: float = 20.0
) -> Version | None:
    """Best-effort query of the latest package version from a local/remote package manager."""
    if not method.type.is_package_manager:
        return None
    pkg = validate_package_id(method.package or "")
    if method.type is MethodType.APT:
        res = runner.run(["apt-cache", "policy", pkg], timeout=timeout)
        return extract_version(res.stdout, _APT_CANDIDATE.pattern) if res.ok else None
    if method.type is MethodType.WINGET:
        res = runner.run(
            ["winget", "show", "--id", pkg, "--exact", "--accept-source-agreements"],
            timeout=timeout,
        )
        return extract_version(res.stdout, _WINGET_VERSION.pattern) if res.ok else None
    if method.type is MethodType.BREW:
        args = ["brew", "info", "--cask", pkg] if method.cask else ["brew", "info", pkg]
        res = runner.run(args, timeout=timeout)
        first_line = res.stdout.splitlines()[0] if res.ok and res.stdout else ""
        return extract_version(first_line)
    return None

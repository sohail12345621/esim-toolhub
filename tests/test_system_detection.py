"""Tests for OS, architecture, Python, package-manager and PATH detection."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from esim_toolhub.core.models import OSFamily
from esim_toolhub.detection.system import (
    detect_os_family,
    detect_system,
    inspect_path,
    normalize_arch,
    parse_os_release,
    windows_marketing_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Windows", OSFamily.WINDOWS),
        ("MSYS_NT-10.0", OSFamily.WINDOWS),
        ("Linux", OSFamily.LINUX),
        ("Darwin", OSFamily.MACOS),
        ("FreeBSD", OSFamily.UNKNOWN),
    ],
)
def test_detect_os_family(raw: str, expected: OSFamily) -> None:
    assert detect_os_family(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AMD64", "x86_64"),
        ("x86_64", "x86_64"),
        ("aarch64", "arm64"),
        ("ARM64", "arm64"),
        ("i686", "x86"),
        ("", "unknown"),
    ],
)
def test_normalize_arch(raw: str, expected: str) -> None:
    assert normalize_arch(raw) == expected


def test_windows_marketing_name_distinguishes_win10_and_win11() -> None:
    assert windows_marketing_name("10.0.22631", "10") == "Windows 11"
    assert windows_marketing_name("10.0.19045", "10") == "Windows 10"


def test_detect_system_linux_with_os_release_and_wsl(tmp_path: Path) -> None:
    os_release = tmp_path / "os-release"
    os_release.write_text(
        'NAME="Ubuntu"\nVERSION_ID="24.04"\nID=ubuntu\nID_LIKE=debian\n'
        'PRETTY_NAME="Ubuntu 24.04.2 LTS"\n',
        encoding="utf-8",
    )
    fake_platform = SimpleNamespace(
        system=lambda: "Linux",
        machine=lambda: "x86_64",
        release=lambda: "5.15.167.4-microsoft-standard-WSL2",
        version=lambda: "#1 SMP",
    )
    info = detect_system(
        platform_module=fake_platform,
        env={"PATH": "/usr/local/bin:/usr/bin"},
        which=lambda name: "/usr/bin/apt-get" if name == "apt-get" else None,
        os_release_path=os_release,
        is_admin=lambda _: False,
        python_version="3.12.3",
        python_executable="/usr/bin/python3",
    )
    assert info.os_family is OSFamily.LINUX
    assert info.os_name == "Ubuntu 24.04.2 LTS"
    assert info.distro_id == "ubuntu"
    assert info.distro_like == ("debian",)
    assert info.is_wsl is True
    assert info.package_managers == {"apt": "/usr/bin/apt-get"}


def test_detect_system_windows_on_arm_uses_native_arch() -> None:
    fake_platform = SimpleNamespace(
        system=lambda: "Windows",
        machine=lambda: "AMD64",
        release=lambda: "10",
        version=lambda: "10.0.26100",
    )
    info = detect_system(
        platform_module=fake_platform,
        env={"PATH": "C:\\Windows\\System32", "PROCESSOR_ARCHITEW6432": "ARM64"},
        which=lambda name: "C:\\winget.exe" if name == "winget" else None,
        is_admin=lambda _: True,
        python_version="3.13.1",
    )
    assert info.os_family is OSFamily.WINDOWS
    assert info.os_name == "Windows 11"
    assert info.architecture == "arm64"
    assert info.is_admin is True
    assert info.package_managers == {"winget": "C:\\winget.exe"}


def test_detect_system_macos() -> None:
    fake_platform = SimpleNamespace(
        system=lambda: "Darwin",
        machine=lambda: "arm64",
        release=lambda: "24.1.0",
        version=lambda: "",
        mac_ver=lambda: ("15.1", ("", "", ""), "arm64"),
    )
    info = detect_system(
        platform_module=fake_platform,
        env={"PATH": "/opt/homebrew/bin:/usr/bin"},
        which=lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None,
        is_admin=lambda _: False,
        python_version="3.12.0",
    )
    assert info.os_family is OSFamily.MACOS
    assert info.os_name == "macOS 15.1"
    assert info.package_managers == {"brew": "/opt/homebrew/bin/brew"}


def test_inspect_path_flags_duplicates_missing_and_relative() -> None:
    issues = inspect_path(
        ["/usr/bin", "/usr/bin", "./relative", "/does/not/exist"],
        OSFamily.LINUX,
        exists=lambda p: p == "/usr/bin",
    )
    problems = {(i.entry, i.problem) for i in issues}
    assert ("/usr/bin", "duplicate entry") in problems
    assert ("./relative", "relative entry (security risk: resolves against CWD)") in problems
    assert ("/does/not/exist", "directory does not exist") in problems


def test_parse_os_release_ignores_comments_and_quotes() -> None:
    parsed = parse_os_release('# comment\nID="fedora"\nVERSION_ID=41\n')
    assert parsed == {"ID": "fedora", "VERSION_ID": "41"}

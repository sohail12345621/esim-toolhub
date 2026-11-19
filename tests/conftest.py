"""Shared fixtures and fakes for the eSim ToolHub test suite.

No test in this suite installs real software or makes live network requests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

import pytest

from esim_toolhub.configuration.environment import EnvironmentManager
from esim_toolhub.configuration.manager import ConfigManager, ToolHubConfig
from esim_toolhub.core.exceptions import CommandExecutionError
from esim_toolhub.core.models import OSFamily, SystemInfo
from esim_toolhub.core.registry import Registry
from esim_toolhub.core.runner import CommandResult
from esim_toolhub.paths import AppPaths


class FakeRunner:
    """Scriptable CommandRunner recording every invocation."""

    def __init__(
        self,
        handler: Callable[[tuple[str, ...]], CommandResult] | None = None,
    ) -> None:
        self.calls: list[tuple[str, ...]] = []
        self._handler = handler

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = 30.0,
        capture: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        argv = tuple(str(a) for a in args)
        self.calls.append(argv)
        if self._handler is not None:
            return self._handler(argv)
        return CommandResult(argv, 0, "", "")


class RaisingRunner(FakeRunner):
    def __init__(self, exc: Exception | None = None) -> None:
        super().__init__()
        self._exc = exc or CommandExecutionError("boom")

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = 30.0,
        capture: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        self.calls.append(tuple(str(a) for a in args))
        raise self._exc


class FakeDownloader:
    """Writes predetermined bytes to ``dest`` instead of hitting the network."""

    def __init__(self, payload: bytes = b"") -> None:
        self.payload = payload
        self.calls: list[str] = []

    def download(
        self,
        url: str,
        dest: Path,
        *,
        trusted_hosts: Iterable[str],
        max_bytes: int,
        timeout: float = 60.0,
    ) -> Path:
        self.calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.payload)
        return dest


def make_system(
    os_family: OSFamily = OSFamily.LINUX,
    *,
    arch: str = "x86_64",
    is_admin: bool = False,
    package_managers: dict[str, str] | None = None,
    distro_id: str = "",
    path_entries: tuple[str, ...] = ("/usr/bin", "/usr/local/bin"),
    python_version: str = "3.12.3",
) -> SystemInfo:
    if os_family is OSFamily.WINDOWS:
        return SystemInfo(
            os_family=OSFamily.WINDOWS,
            os_name="Windows 11",
            os_version="10.0.26100",
            architecture=arch,
            machine="AMD64",
            python_version=python_version,
            python_executable="C:/Python312/python.exe",
            is_admin=is_admin,
            path_entries=path_entries,
            package_managers=package_managers
            if package_managers is not None
            else {"winget": "C:/winget.exe", "choco": "C:/choco.exe"},
        )
    if os_family is OSFamily.MACOS:
        return SystemInfo(
            os_family=OSFamily.MACOS,
            os_name="macOS 15.1",
            os_version="15.1",
            architecture=arch,
            machine="arm64" if arch == "arm64" else "x86_64",
            python_version=python_version,
            python_executable="/usr/local/bin/python3",
            is_admin=is_admin,
            path_entries=path_entries,
            package_managers=package_managers
            if package_managers is not None
            else {"brew": "/opt/homebrew/bin/brew"},
        )
    return SystemInfo(
        os_family=OSFamily.LINUX,
        os_name="Ubuntu 24.04.2 LTS",
        os_version="24.04",
        architecture=arch,
        machine="x86_64",
        python_version=python_version,
        python_executable="/usr/bin/python3",
        distro_id=distro_id or "ubuntu",
        distro_like=("debian",),
        is_admin=is_admin,
        path_entries=path_entries,
        package_managers=package_managers
        if package_managers is not None
        else {"apt": "/usr/bin/apt-get"},
    )


@pytest.fixture()
def registry() -> Registry:
    return Registry.load()


@pytest.fixture()
def app_paths(tmp_path: Path) -> AppPaths:
    return AppPaths.under(tmp_path)


@pytest.fixture()
def config_manager(app_paths: AppPaths) -> ConfigManager:
    return ConfigManager(app_paths.config_file)


@pytest.fixture()
def default_config() -> ToolHubConfig:
    return ToolHubConfig()


@pytest.fixture()
def env_manager(app_paths: AppPaths) -> EnvironmentManager:
    return EnvironmentManager(app_paths.environment_file)

"""Factory returning the right Installer adapter for the detected OS."""

from __future__ import annotations

from esim_toolhub.configuration.environment import EnvironmentManager
from esim_toolhub.configuration.manager import ToolHubConfig
from esim_toolhub.core.exceptions import UnsupportedPlatformError
from esim_toolhub.core.models import OSFamily, SystemInfo
from esim_toolhub.core.runner import CommandRunner
from esim_toolhub.dependency.checker import DependencyChecker
from esim_toolhub.installers.base import Installer
from esim_toolhub.installers.downloader import Downloader
from esim_toolhub.installers.linux import LinuxInstaller
from esim_toolhub.installers.macos import MacOSInstaller
from esim_toolhub.installers.windows import WindowsInstaller
from esim_toolhub.paths import AppPaths


def create_installer(
    system: SystemInfo,
    checker: DependencyChecker,
    runner: CommandRunner,
    downloader: Downloader,
    environment: EnvironmentManager,
    config: ToolHubConfig,
    paths: AppPaths,
    trusted_hosts: tuple[str, ...],
) -> Installer:
    if system.os_family is OSFamily.WINDOWS:
        return WindowsInstaller(
            system, checker, runner, downloader, environment, config, paths, trusted_hosts
        )
    if system.os_family is OSFamily.LINUX:
        return LinuxInstaller(
            system, checker, runner, downloader, environment, config, paths, trusted_hosts
        )
    if system.os_family is OSFamily.MACOS:
        return MacOSInstaller(
            system, checker, runner, downloader, environment, config, paths, trusted_hosts
        )
    raise UnsupportedPlatformError(
        f"No installer adapter exists for operating system '{system.os_name}'."
    )

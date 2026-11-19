"""Linux installer adapter (apt, dnf, pacman, verified archive, manual)."""

from __future__ import annotations

import shutil
from collections.abc import Callable

from esim_toolhub.configuration.environment import EnvironmentManager
from esim_toolhub.configuration.manager import ToolHubConfig
from esim_toolhub.core.models import InstallMethod, MethodType, OSFamily, SystemInfo
from esim_toolhub.core.runner import CommandRunner
from esim_toolhub.dependency.checker import DependencyChecker
from esim_toolhub.installers.base import Installer
from esim_toolhub.installers.downloader import Downloader
from esim_toolhub.paths import AppPaths


class LinuxInstaller(Installer):
    os_family = OSFamily.LINUX

    def __init__(
        self,
        system: SystemInfo,
        checker: DependencyChecker,
        runner: CommandRunner,
        downloader: Downloader,
        environment: EnvironmentManager,
        config: ToolHubConfig,
        paths: AppPaths,
        trusted_hosts: tuple[str, ...],
        has_sudo: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(
            system, checker, runner, downloader, environment, config, paths, trusted_hosts
        )
        self._has_sudo = has_sudo or (lambda: shutil.which("sudo") is not None)

    def allowed_methods(self) -> tuple[MethodType, ...]:
        return (
            MethodType.APT,
            MethodType.DNF,
            MethodType.PACMAN,
            MethodType.ARCHIVE,
            MethodType.MANUAL,
        )

    def needs_sudo(self, method: InstallMethod) -> bool:
        return method.type.is_package_manager and not self.system.is_admin

    def privilege_blocker(self, method: InstallMethod) -> str | None:
        if self.needs_sudo(method) and not self._has_sudo():
            return (
                f"{method.type.value} requires root privileges, but neither root nor 'sudo' "
                f"is available in this environment."
            )
        return None

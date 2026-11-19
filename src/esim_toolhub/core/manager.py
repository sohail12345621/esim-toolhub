"""Core ToolHub facade orchestrating detection, checking, planning, installing and updates."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path

from esim_toolhub.configuration.environment import EnvironmentManager
from esim_toolhub.configuration.manager import ConfigManager, ToolHubConfig
from esim_toolhub.core.exceptions import UnsupportedPlatformError
from esim_toolhub.core.models import (
    DoctorReport,
    InstallPlan,
    InstallResult,
    OSFamily,
    Profile,
    SystemInfo,
    ToolReport,
    ToolSpec,
    ToolStatus,
    UpdateInfo,
    UpdateState,
)
from esim_toolhub.core.registry import Registry
from esim_toolhub.core.runner import CommandRunner, SubprocessRunner
from esim_toolhub.dependency.checker import DependencyChecker
from esim_toolhub.dependency.doctor import run_doctor
from esim_toolhub.dependency.resolver import DependencyResolver
from esim_toolhub.detection.executable import ExecutableLocator
from esim_toolhub.detection.system import detect_system, inspect_path
from esim_toolhub.detection.version import Version
from esim_toolhub.installers.base import Installer
from esim_toolhub.installers.downloader import Downloader, HttpDownloader
from esim_toolhub.installers.factory import create_installer
from esim_toolhub.logs.manager import LogEntry, read_logs, setup_logging
from esim_toolhub.paths import AppPaths
from esim_toolhub.update.checker import UpdateChecker

log = logging.getLogger(__name__)


def _is_writable_dir(path: Path) -> bool:
    try:
        target = path
        while not target.exists() and target != target.parent:
            target = target.parent
        return os.access(target, os.W_OK)
    except OSError:
        return False


class ToolHub:
    """High-level application coordinator with injectable infrastructure components."""

    def __init__(
        self,
        *,
        registry: Registry | None = None,
        paths: AppPaths | None = None,
        config_manager: ConfigManager | None = None,
        config: ToolHubConfig | None = None,
        environment: EnvironmentManager | None = None,
        system: SystemInfo | None = None,
        runner: CommandRunner | None = None,
        downloader: Downloader | None = None,
        locator: ExecutableLocator | None = None,
        checker: DependencyChecker | None = None,
        installer: Installer | None = None,
        configure_logging: bool = True,
    ) -> None:
        self.paths = paths or AppPaths.default()
        self.registry = registry or Registry.load()
        self.config_manager = config_manager or ConfigManager(self.paths.config_file)
        self.config = config or self.config_manager.load()
        if configure_logging:
            setup_logging(self.paths.log_file, self.config.log_level)

        self.environment = environment or EnvironmentManager(self.paths.environment_file)
        self.system = system or detect_system()
        self.runner: CommandRunner = runner or SubprocessRunner()
        self.downloader: Downloader = downloader or HttpDownloader()
        self.locator = locator or ExecutableLocator(
            self.system, managed_dirs=self.environment.managed_dirs
        )
        self.checker = checker or DependencyChecker(self.system, self.locator, self.runner)
        self.resolver = DependencyResolver(self.registry)

        if installer is not None:
            self.installer: Installer | None = installer
        else:
            try:
                self.installer = create_installer(
                    self.system,
                    self.checker,
                    self.runner,
                    self.downloader,
                    self.environment,
                    self.config,
                    self.paths,
                    self.registry.trusted_hosts,
                )
            except UnsupportedPlatformError:
                self.installer = None

        self.update_checker = UpdateChecker(self.runner, self.installer)
        self._report_cache: dict[str, ToolReport] = {}

    # ------------------------------------------------------------------ inspection
    def list_tools(self) -> list[ToolSpec]:
        return self.registry.tools()

    def list_profiles(self) -> list[Profile]:
        return self.registry.profiles()

    def expand_profile(self, name: str) -> list[ToolSpec]:
        names = self.resolver.resolve(self.resolver.expand_profile(name))
        return [self.registry.tool(n) for n in names]

    def status(
        self, tool_names: Iterable[str] | None = None, *, refresh: bool = False
    ) -> list[ToolReport]:
        specs = (
            [self.registry.tool(n) for n in tool_names]
            if tool_names is not None
            else self.registry.tools()
        )
        reports: list[ToolReport] = []
        for spec in specs:
            if refresh or spec.name not in self._report_cache:
                self._report_cache[spec.name] = self.checker.check(spec)
            reports.append(self._report_cache[spec.name])
        return reports

    def check(self, tool_name: str | None = None) -> list[ToolReport]:
        names = [tool_name] if tool_name else None
        return self.status(names, refresh=True)

    def doctor(self) -> DoctorReport:
        reports = self.status(refresh=True)
        path_issues = inspect_path(self.system.path_entries, self.system.os_family)
        writable = [
            ("Config", _is_writable_dir(self.paths.config_dir)),
            ("Data", _is_writable_dir(self.paths.data_dir)),
            ("Logs", _is_writable_dir(self.paths.log_dir)),
        ]
        return run_doctor(
            self.registry, self.system, reports, path_issues=path_issues, writable_dirs=writable
        )

    # ------------------------------------------------------------------ install / uninstall
    def _require_installer(self) -> Installer:
        if self.installer is None:
            raise UnsupportedPlatformError(
                f"Automated installation is not supported on '{self.system.os_name}'."
            )
        return self.installer

    def resolve_install_targets(
        self, tool_names: Iterable[str] = (), profile: str | None = None
    ) -> list[ToolSpec]:
        requested: list[str] = []
        if profile:
            requested.extend(self.resolver.expand_profile(profile))
        requested.extend(tool_names)
        ordered = self.resolver.resolve(requested)
        return [self.registry.tool(name) for name in ordered]

    def install(
        self,
        tool_names: Iterable[str] = (),
        *,
        profile: str | None = None,
        dry_run: bool = False,
        force: bool = False,
        preferred_method: str | None = None,
    ) -> list[tuple[InstallPlan, InstallResult | None]]:
        installer = self._require_installer()
        specs = self.resolve_install_targets(tool_names, profile=profile)
        outcomes: list[tuple[InstallPlan, InstallResult | None]] = []
        for spec in specs:
            plan, result = installer.install(
                spec, dry_run=dry_run, force=force, preferred_method=preferred_method
            )
            if not dry_run:
                self._report_cache.pop(spec.name, None)
                if result and result.report:
                    self._report_cache[spec.name] = result.report
            outcomes.append((plan, result))
        return outcomes

    def plan_uninstall(
        self,
        tool_name: str,
        *,
        preferred_method: str | None = None,
    ) -> InstallPlan:
        installer = self._require_installer()
        spec = self.registry.tool(tool_name)
        return installer.plan_uninstall(spec, preferred_method=preferred_method)

    def uninstall(
        self,
        tool_name: str,
        *,
        dry_run: bool = False,
        preferred_method: str | None = None,
    ) -> tuple[InstallPlan, InstallResult | None]:
        installer = self._require_installer()
        spec = self.registry.tool(tool_name)
        plan, result = installer.uninstall(spec, dry_run=dry_run, preferred_method=preferred_method)
        if not dry_run:
            self._report_cache.pop(spec.name, None)
        return plan, result

    def set_tool_path(self, tool_name: str, directory: Path, *, dry_run: bool = False) -> Path:
        spec = self.registry.tool(tool_name)
        resolved = directory.expanduser().resolve()
        if not resolved.is_dir():
            from esim_toolhub.core.exceptions import ConfigError

            raise ConfigError(f"Directory does not exist: {resolved}")
        if not dry_run:
            self.environment.register(spec.name, resolved)
            self._report_cache.pop(spec.name, None)
        return resolved

    def unset_tool_path(self, tool_name: str, *, dry_run: bool = False) -> bool:
        spec = self.registry.tool(tool_name)
        if dry_run:
            return bool(self.environment.managed_dirs(spec.name))
        removed = self.environment.unregister(spec.name)
        self._report_cache.pop(spec.name, None)
        return removed

    # ------------------------------------------------------------------ updates
    def check_updates(
        self, tool_names: Iterable[str] | None = None, *, online: bool | None = None
    ) -> list[UpdateInfo]:
        use_online = self.config.online_update_check if online is None else online
        reports = self.status(tool_names, refresh=True)
        return self.update_checker.check_many(reports, online=use_online)

    def plan_updates(
        self,
        tool_names: Iterable[str] | None = None,
        *,
        online: bool | None = None,
        include_unsupported: bool = False,
        preferred_method: str | None = None,
    ) -> tuple[list[UpdateInfo], list[InstallPlan]]:
        updates = self.check_updates(tool_names, online=online)
        installer = self._require_installer()
        plans: list[InstallPlan] = []
        eligible = {UpdateState.UPDATE_AVAILABLE}
        if include_unsupported:
            eligible.add(UpdateState.UNSUPPORTED_UPDATE)
        for info in updates:
            if info.state in eligible:
                spec = self.registry.tool(info.tool)
                report = self._report_cache.get(spec.name)
                plans.append(installer.plan_update(spec, report, preferred_method=preferred_method))
        return updates, plans

    def execute_plans(
        self, plans: Iterable[InstallPlan]
    ) -> list[tuple[InstallPlan, InstallResult]]:
        installer = self._require_installer()
        outcomes: list[tuple[InstallPlan, InstallResult]] = []
        for plan in plans:
            result = installer.execute(plan)
            self._report_cache.pop(plan.tool.name, None)
            if result.report:
                self._report_cache[plan.tool.name] = result.report
            outcomes.append((plan, result))
        return outcomes

    # ------------------------------------------------------------------ config / logs / demo
    def environment_guidance(self) -> tuple[list[Path], str]:
        reports = self.status()
        extra_dirs = [
            r.executable.parent for r in reports if r.executable is not None and r.on_path is False
        ]
        missing = self.environment.missing_from_path(self.system, extra_dirs=extra_dirs)
        snippet = self.environment.shell_snippet(missing, self.system.os_family)
        return missing, snippet

    def read_logs(self, tail: int = 50, min_level: str = "DEBUG") -> list[LogEntry]:
        return read_logs(self.paths.log_file, tail=tail, min_level=min_level)

    def demo_snapshot(self) -> tuple[SystemInfo, list[ToolReport], DoctorReport]:
        """Deterministic, clearly labelled showcase snapshot; never touches the host."""
        demo_system = SystemInfo(
            os_family=OSFamily.LINUX,
            os_name="Ubuntu 24.04.2 LTS (DEMO)",
            os_version="24.04",
            architecture="x86_64",
            machine="x86_64",
            python_version="3.12.3",
            python_executable="/usr/bin/python3",
            distro_id="ubuntu",
            distro_like=("debian",),
            package_managers={"apt": "/usr/bin/apt-get"},
            path_entries=("/usr/local/bin", "/usr/bin", "/bin"),
        )
        kicad = self.registry.tool("kicad")
        ngspice = self.registry.tool("ngspice")
        ghdl = self.registry.tool("ghdl")
        verilator = self.registry.tool("verilator")
        reports = [
            ToolReport(
                spec=ngspice,
                status=ToolStatus.INSTALLED,
                version=Version((44, 0, 0), raw="44"),
                executable=Path("/usr/bin/ngspice"),
                on_path=True,
                message="Compatible",
            ),
            ToolReport(
                spec=kicad,
                status=ToolStatus.INSTALLED,
                version=Version((9, 0, 1), raw="9.0.1"),
                executable=Path("/usr/bin/kicad-cli"),
                on_path=True,
                message="Compatible",
            ),
            ToolReport(
                spec=ghdl,
                status=ToolStatus.MISSING,
                message="Executable not found",
                recommendation="Install using ToolHub: esim-toolhub install ghdl",
            ),
            ToolReport(
                spec=verilator,
                status=ToolStatus.OUTDATED,
                version=Version((4, 228, 0), raw="4.228"),
                executable=Path("/usr/bin/verilator"),
                on_path=True,
                message="4.228 is older than required >= 5.0",
                recommendation="Upgrade: esim-toolhub update verilator",
            ),
        ]
        doctor = run_doctor(self.registry, demo_system, reports)
        return demo_system, reports, doctor

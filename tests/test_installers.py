"""Tests for cross-platform installer adapters, dry-run plans, privilege boundaries and archives."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from esim_toolhub.configuration.environment import EnvironmentManager
from esim_toolhub.configuration.manager import ToolHubConfig
from esim_toolhub.core.exceptions import UnsupportedPlatformError
from esim_toolhub.core.models import (
    InstallMethod,
    MethodType,
    OSFamily,
    StepKind,
    ToolSpec,
    ToolStatus,
)
from esim_toolhub.core.registry import Registry
from esim_toolhub.core.runner import CommandResult
from esim_toolhub.dependency.checker import DependencyChecker
from esim_toolhub.detection.executable import ExecutableLocator
from esim_toolhub.installers.factory import create_installer
from esim_toolhub.installers.linux import LinuxInstaller
from esim_toolhub.installers.macos import MacOSInstaller
from esim_toolhub.installers.windows import WindowsInstaller
from esim_toolhub.paths import AppPaths
from tests.conftest import FakeDownloader, FakeRunner, make_system


def test_installer_factory_selects_platform_adapter(
    registry: Registry,
    app_paths: AppPaths,
    default_config: ToolHubConfig,
    env_manager: EnvironmentManager,
) -> None:
    runner = FakeRunner()
    dl = FakeDownloader()
    for os_fam, cls in [
        (OSFamily.WINDOWS, WindowsInstaller),
        (OSFamily.LINUX, LinuxInstaller),
        (OSFamily.MACOS, MacOSInstaller),
    ]:
        sys_info = make_system(os_fam)
        checker = DependencyChecker(
            sys_info, ExecutableLocator(sys_info, which=lambda _: None), runner
        )
        inst = create_installer(
            sys_info,
            checker,
            runner,
            dl,
            env_manager,
            default_config,
            app_paths,
            registry.trusted_hosts,
        )
        assert isinstance(inst, cls)

    unknown_sys = make_system(OSFamily.LINUX)
    unknown_sys = unknown_sys.__class__(**{**unknown_sys.__dict__, "os_family": OSFamily.UNKNOWN})
    checker = DependencyChecker(
        unknown_sys, ExecutableLocator(unknown_sys, which=lambda _: None), runner
    )
    with pytest.raises(UnsupportedPlatformError):
        create_installer(
            unknown_sys,
            checker,
            runner,
            dl,
            env_manager,
            default_config,
            app_paths,
            registry.trusted_hosts,
        )


def test_dry_run_builds_plan_without_running_commands_or_downloads(
    registry: Registry,
    app_paths: AppPaths,
    default_config: ToolHubConfig,
    env_manager: EnvironmentManager,
) -> None:
    sys_info = make_system(OSFamily.WINDOWS)
    runner = FakeRunner()
    downloader = FakeDownloader()
    locator = ExecutableLocator(sys_info, which=lambda _: None, is_executable=lambda _: False)
    checker = DependencyChecker(sys_info, locator, runner)
    installer = WindowsInstaller(
        sys_info,
        checker,
        runner,
        downloader,
        env_manager,
        default_config,
        app_paths,
        registry.trusted_hosts,
    )

    plan, result = installer.install(registry.tool("kicad"), dry_run=True)
    assert result is None
    assert plan.action == "install"
    assert plan.method is not None and plan.method.type is MethodType.WINGET
    assert plan.blocked_reason is None
    assert any(s.kind is StepKind.PACKAGE_INSTALL for s in plan.steps)
    assert any(s.kind is StepKind.VERIFY_VERSION for s in plan.steps)
    assert runner.calls == []
    assert downloader.calls == []


def test_windows_choco_blocks_without_admin_and_allows_with_admin(
    registry: Registry,
    app_paths: AppPaths,
    default_config: ToolHubConfig,
    env_manager: EnvironmentManager,
) -> None:
    runner = FakeRunner()
    dl = FakeDownloader()
    ngspice = registry.tool("ngspice")

    non_admin = make_system(OSFamily.WINDOWS, is_admin=False)
    inst_user = WindowsInstaller(
        non_admin,
        DependencyChecker(
            non_admin,
            ExecutableLocator(non_admin, which=lambda _: None, is_executable=lambda _: False),
            runner,
        ),
        runner,
        dl,
        env_manager,
        default_config,
        app_paths,
        registry.trusted_hosts,
    )
    plan_user = inst_user.plan_install(ngspice)
    assert plan_user.blocked_reason is not None
    assert "Administrator" in plan_user.blocked_reason

    admin = make_system(OSFamily.WINDOWS, is_admin=True)
    inst_admin = WindowsInstaller(
        admin,
        DependencyChecker(
            admin,
            ExecutableLocator(admin, which=lambda _: None, is_executable=lambda _: False),
            runner,
        ),
        runner,
        dl,
        env_manager,
        default_config,
        app_paths,
        registry.trusted_hosts,
    )
    plan_admin = inst_admin.plan_install(ngspice)
    assert plan_admin.blocked_reason is None


def test_linux_installer_verifies_after_install_and_fails_honestly_if_unverified(
    registry: Registry,
    app_paths: AppPaths,
    default_config: ToolHubConfig,
    env_manager: EnvironmentManager,
) -> None:
    sys_info = make_system(OSFamily.LINUX, is_admin=False)
    installed_flag = {"present": False}

    def fake_which(name: str) -> str | None:
        return "/usr/bin/ngspice" if name == "ngspice" and installed_flag["present"] else None

    def fake_run(argv: tuple[str, ...]) -> CommandResult:
        if "install" in argv:
            installed_flag["present"] = True
            return CommandResult(argv, 0, "Setting up ngspice ...")
        if Path(argv[0]).name == "ngspice":
            return CommandResult(argv, 0, "** ngspice-44 : simulator\n")
        return CommandResult(argv, 0, "")

    runner = FakeRunner(fake_run)
    locator = ExecutableLocator(sys_info, which=fake_which, is_executable=lambda _: False)
    checker = DependencyChecker(sys_info, locator, runner)
    installer = LinuxInstaller(
        sys_info,
        checker,
        runner,
        FakeDownloader(),
        env_manager,
        default_config,
        app_paths,
        registry.trusted_hosts,
        has_sudo=lambda: True,
    )

    _, result = installer.install(registry.tool("ngspice"))
    assert result is not None and result.success is True
    assert result.report is not None and result.report.status is ToolStatus.INSTALLED
    assert any(call[:2] == ("sudo", "-n") for call in runner.calls)

    # Already installed -> skipped without force
    plan_skip, result_skip = installer.install(registry.tool("ngspice"))
    assert plan_skip.action == "skip"
    assert result_skip is not None and result_skip.success is True

    # If package manager exits 0 but binary is NOT present, must report failure (never fake success)
    installed_flag["present"] = False
    broken_runner = FakeRunner(lambda argv: CommandResult(argv, 0, "done"))
    broken_installer = LinuxInstaller(
        sys_info,
        DependencyChecker(sys_info, locator, broken_runner),
        broken_runner,
        FakeDownloader(),
        env_manager,
        default_config,
        app_paths,
        registry.trusted_hosts,
        has_sudo=lambda: True,
    )
    _, fail_result = broken_installer.install(registry.tool("ngspice"))
    assert fail_result is not None and fail_result.success is False
    assert "verification failed" in fail_result.message


def test_verified_archive_install_and_uninstall_lifecycle(
    app_paths: AppPaths,
    default_config: ToolHubConfig,
    env_manager: EnvironmentManager,
) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ghdl-6.0.0/bin/ghdl.exe", b"stub-exe")
    payload = buf.getvalue()
    sha = hashlib.sha256(payload).hexdigest()

    spec = ToolSpec(
        name="ghdl",
        display_name="GHDL",
        description="VHDL simulator",
        category="digital",
        required=False,
        executables={"windows": ("ghdl.exe",)},
        version_pattern=r"GHDL\s+v?(\d+(?:\.\d+)*)",
        minimum_version="3.0",
        install={
            "windows": (
                InstallMethod(
                    type=MethodType.ARCHIVE,
                    version="6.0.0",
                    url="https://github.com/ghdl/ghdl/releases/download/v6.0.0/ghdl.zip",
                    sha256=sha,
                    architectures=("x86_64",),
                ),
            )
        },
    )
    sys_info = make_system(OSFamily.WINDOWS, package_managers={})
    runner = FakeRunner(lambda argv: CommandResult(argv, 0, "GHDL 6.0.0 [Dunoon edition]\n"))
    locator = ExecutableLocator(
        sys_info,
        which=lambda _: None,
        managed_dirs=env_manager.managed_dirs,
    )
    checker = DependencyChecker(sys_info, locator, runner)
    installer = WindowsInstaller(
        sys_info,
        checker,
        runner,
        FakeDownloader(payload),
        env_manager,
        default_config,
        app_paths,
        ("github.com",),
    )

    _, res = installer.install(spec)
    assert res is not None and res.success is True
    assert env_manager.managed_dirs("ghdl")
    assert (app_paths.tools_dir / "ghdl" / "ghdl-6.0.0" / "bin" / "ghdl.exe").exists()

    # Uninstall removes extracted directory and environment registration
    _, un_res = installer.uninstall(spec)
    assert un_res is not None and un_res.success is True
    assert env_manager.managed_dirs("ghdl") == []
    assert not (app_paths.tools_dir / "ghdl").exists()


def test_archive_without_checksum_blocked_when_verification_enabled(
    app_paths: AppPaths,
    default_config: ToolHubConfig,
    env_manager: EnvironmentManager,
) -> None:
    spec = ToolSpec(
        name="demo",
        display_name="Demo",
        description="",
        category="general",
        required=False,
        executables={"linux": ("demo",)},
        install={
            "linux": (
                InstallMethod(
                    type=MethodType.ARCHIVE,
                    url="https://github.com/example/demo/releases/download/v1/demo.tar.gz",
                    sha256=None,
                ),
            )
        },
    )
    sys_info = make_system(OSFamily.LINUX, package_managers={})
    runner = FakeRunner()
    checker = DependencyChecker(sys_info, ExecutableLocator(sys_info, which=lambda _: None), runner)
    installer = LinuxInstaller(
        sys_info,
        checker,
        runner,
        FakeDownloader(),
        env_manager,
        default_config,
        app_paths,
        ("github.com",),
    )
    plan = installer.plan_install(spec)
    assert plan.blocked_reason is not None
    assert "no SHA256" in plan.blocked_reason


def test_manual_install_plan_reports_instructions_honestly(
    registry: Registry,
    app_paths: AppPaths,
    default_config: ToolHubConfig,
    env_manager: EnvironmentManager,
) -> None:
    sys_info = make_system(OSFamily.WINDOWS)
    runner = FakeRunner()
    checker = DependencyChecker(
        sys_info,
        ExecutableLocator(sys_info, which=lambda _: None, is_executable=lambda _: False),
        runner,
    )
    installer = WindowsInstaller(
        sys_info,
        checker,
        runner,
        FakeDownloader(),
        env_manager,
        default_config,
        app_paths,
        registry.trusted_hosts,
    )
    plan, res = installer.install(registry.tool("verilator"))
    assert plan.method is not None and plan.method.type is MethodType.MANUAL
    assert plan.blocked_reason is not None
    assert any(s.kind is StepKind.MANUAL for s in plan.steps)
    assert res is not None and res.success is False


def test_package_manager_commands_all_platforms_no_shell() -> None:
    from esim_toolhub.installers.package_managers import (
        install_command,
        uninstall_command,
        upgrade_command,
    )

    for mtype, pkg, cask in [
        (MethodType.APT, "ngspice", False),
        (MethodType.DNF, "kicad", False),
        (MethodType.PACMAN, "verilator", False),
        (MethodType.WINGET, "KiCad.KiCad", False),
        (MethodType.CHOCO, "ngspice", False),
        (MethodType.BREW, "kicad", True),
    ]:
        method = InstallMethod(type=mtype, package=pkg, cask=cask)
        for builder in (install_command, upgrade_command, uninstall_command):
            cmd = builder(
                method, use_sudo=(mtype in (MethodType.APT, MethodType.DNF, MethodType.PACMAN))
            )
            assert isinstance(cmd, tuple)
            assert pkg in cmd
            if cask:
                assert "--cask" in cmd


def test_macos_installer_includes_experimental_note(
    registry: Registry,
    app_paths: AppPaths,
    default_config: ToolHubConfig,
    env_manager: EnvironmentManager,
) -> None:
    sys_info = make_system(OSFamily.MACOS, arch="arm64")
    runner = FakeRunner()
    checker = DependencyChecker(
        sys_info,
        ExecutableLocator(sys_info, which=lambda _: None, is_executable=lambda _: False),
        runner,
    )
    installer = MacOSInstaller(
        sys_info,
        checker,
        runner,
        FakeDownloader(),
        env_manager,
        default_config,
        app_paths,
        registry.trusted_hosts,
    )
    plan = installer.plan_install(registry.tool("ngspice"))
    assert plan.method is not None and plan.method.type is MethodType.BREW
    assert any("experimental" in note.lower() for note in plan.notes)

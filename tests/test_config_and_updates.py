"""Tests for ConfigManager, EnvironmentManager and UpdateChecker."""

from __future__ import annotations

from pathlib import Path

import pytest

from esim_toolhub.configuration.environment import EnvironmentManager
from esim_toolhub.configuration.manager import ConfigManager
from esim_toolhub.core.exceptions import ConfigError
from esim_toolhub.core.models import OSFamily, ToolReport, ToolStatus, UpdateState
from esim_toolhub.core.registry import Registry
from esim_toolhub.core.runner import CommandResult
from esim_toolhub.dependency.checker import DependencyChecker
from esim_toolhub.detection.executable import ExecutableLocator
from esim_toolhub.detection.version import Version
from esim_toolhub.installers.linux import LinuxInstaller
from esim_toolhub.paths import AppPaths
from esim_toolhub.update.checker import UpdateChecker
from tests.conftest import FakeDownloader, FakeRunner, make_system


def test_config_manager_defaults_set_reload_and_validation(
    config_manager: ConfigManager,
) -> None:
    cfg = config_manager.load()
    assert cfg.verify_checksums is True
    assert cfg.auto_update is False

    updated = config_manager.set("log_level", "debug")
    assert updated.log_level == "DEBUG"
    assert config_manager.load().log_level == "DEBUG"

    updated2 = config_manager.set("preferred_install_method", "winget")
    assert updated2.preferred_install_method == "winget"

    with pytest.raises(ConfigError):
        config_manager.set("unknown_key", "1")
    with pytest.raises(ConfigError):
        config_manager.set("log_level", "LOUD")
    with pytest.raises(ConfigError):
        config_manager.set("auto_update", "maybe")

    reset = config_manager.reset()
    assert reset.log_level == "INFO"
    assert reset.preferred_install_method is None


def test_environment_manager_tracks_dirs_and_generates_snippets(
    env_manager: EnvironmentManager, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "tools" / "ghdl" / "bin"
    bin_dir.mkdir(parents=True)
    env_manager.register("ghdl", bin_dir)
    assert env_manager.managed_dirs("ghdl") == [bin_dir.resolve()]

    win_sys = make_system(OSFamily.WINDOWS, path_entries=("C:\\Windows\\System32",))
    missing = env_manager.missing_from_path(win_sys)
    assert missing == [bin_dir.resolve()]
    ps_snippet = env_manager.shell_snippet(missing, OSFamily.WINDOWS)
    assert "$env:PATH" in ps_snippet
    sh_snippet = env_manager.shell_snippet(missing, OSFamily.LINUX)
    assert "export PATH=" in sh_snippet

    assert env_manager.unregister("ghdl") is True
    assert env_manager.managed_dirs("ghdl") == []


def test_update_checker_distinguishes_all_five_states(registry: Registry) -> None:
    checker = UpdateChecker(FakeRunner())

    # NOT_INSTALLED
    r_missing = ToolReport(registry.tool("ngspice"), ToolStatus.MISSING)
    assert checker.check(r_missing).state is UpdateState.NOT_INSTALLED

    # UPDATE_AVAILABLE (ngspice 44 -> 47)
    r_old = ToolReport(registry.tool("ngspice"), ToolStatus.INSTALLED, Version((44, 0, 0)))
    u_avail = checker.check(r_old)
    assert u_avail.state is UpdateState.UPDATE_AVAILABLE
    assert u_avail.latest == "47.0"

    # UP_TO_DATE (ngspice 47 -> 47)
    r_cur = ToolReport(registry.tool("ngspice"), ToolStatus.INSTALLED, Version((47, 0, 0)))
    assert checker.check(r_cur).state is UpdateState.UP_TO_DATE

    # UNSUPPORTED_UPDATE (KiCad 9.0 -> 10.0.8 exceeds tested_up_to 9)
    r_kicad = ToolReport(registry.tool("kicad"), ToolStatus.INSTALLED, Version((9, 0, 1)))
    u_unsup = checker.check(r_kicad)
    assert u_unsup.state is UpdateState.UNSUPPORTED_UPDATE
    assert "validated" in u_unsup.message

    # UNKNOWN (verilator has no static latest_known_version in registry)
    r_ver = ToolReport(registry.tool("verilator"), ToolStatus.INSTALLED, Version((5, 28, 0)))
    assert checker.check(r_ver).state is UpdateState.UNKNOWN


def test_update_checker_online_queries_package_manager(
    registry: Registry,
    app_paths: AppPaths,
    env_manager: EnvironmentManager,
) -> None:
    sys_info = make_system(OSFamily.LINUX)
    runner = FakeRunner(
        lambda argv: CommandResult(
            argv, 0, "verilator:\n  Installed: 5.020-1\n  Candidate: 5.028-1\n"
        )
    )
    dep = DependencyChecker(sys_info, ExecutableLocator(sys_info, which=lambda _: None), runner)
    installer = LinuxInstaller(
        sys_info,
        dep,
        runner,
        FakeDownloader(),
        env_manager,
        ConfigManager(app_paths.config_file).load(),
        app_paths,
        registry.trusted_hosts,
    )
    updater = UpdateChecker(runner, installer)
    report = ToolReport(registry.tool("verilator"), ToolStatus.INSTALLED, Version((5, 20, 0)))
    info = updater.check(report, online=True)
    assert info.state is UpdateState.UPDATE_AVAILABLE
    assert info.source == "apt"
    assert info.latest == "5.28"

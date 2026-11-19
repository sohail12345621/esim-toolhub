"""End-to-end mocked CLI tests via Typer's CliRunner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from esim_toolhub.cli import commands
from esim_toolhub.core.exceptions import UnknownToolError
from esim_toolhub.core.manager import ToolHub
from esim_toolhub.core.models import OSFamily
from esim_toolhub.core.runner import CommandResult
from esim_toolhub.detection.executable import ExecutableLocator
from esim_toolhub.paths import AppPaths
from tests.conftest import FakeDownloader, FakeRunner, make_system

cli_runner = CliRunner()


@pytest.fixture()
def patched_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ToolHub:
    sys_info = make_system(OSFamily.LINUX)

    def fake_which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in ("ngspice", "kicad-cli") else None

    def fake_run(argv: tuple[str, ...]) -> CommandResult:
        if "ngspice" in argv[0]:
            return CommandResult(argv, 0, "** ngspice-44 : simulator\n")
        if "kicad-cli" in argv[0]:
            return CommandResult(argv, 0, "9.0.1\n")
        return CommandResult(argv, 0, "")

    runner = FakeRunner(fake_run)
    locator = ExecutableLocator(sys_info, which=fake_which, is_executable=lambda _: False)
    hub = ToolHub(
        paths=AppPaths.under(tmp_path),
        system=sys_info,
        runner=runner,
        downloader=FakeDownloader(),
        locator=locator,
    )
    monkeypatch.setattr(commands, "_hub_factory", lambda: hub)
    return hub


def test_cli_version_system_list_and_status(patched_hub: ToolHub) -> None:
    res_v = cli_runner.invoke(commands.app, ["--version"])
    assert res_v.exit_code == 0
    assert "esim-toolhub" in res_v.output

    res_sys = cli_runner.invoke(commands.app, ["system", "--json"])
    assert res_sys.exit_code == 0
    sys_data = json.loads(res_sys.output)
    assert sys_data["os_family"] == "linux"
    assert sys_data["architecture"] == "x86_64"

    res_list = cli_runner.invoke(commands.app, ["list"])
    assert res_list.exit_code == 0
    assert "Ngspice" in res_list.output and "analog" in res_list.output

    res_status = cli_runner.invoke(commands.app, ["status", "--json"])
    assert res_status.exit_code == 0
    status_data = json.loads(res_status.output)
    by_name = {item["tool"]: item for item in status_data["tools"]}
    assert by_name["ngspice"]["status"] == "INSTALLED"
    assert by_name["kicad"]["status"] == "INSTALLED"
    assert by_name["ghdl"]["status"] == "MISSING"


def test_cli_check_doctor_and_demo(patched_hub: ToolHub) -> None:
    res_check = cli_runner.invoke(commands.app, ["check", "ngspice"])
    assert res_check.exit_code == 0
    assert "INSTALLED" in res_check.output

    res_doc = cli_runner.invoke(commands.app, ["doctor", "--json"])
    assert res_doc.exit_code == 0
    doc_data = json.loads(res_doc.output)
    assert doc_data["failures"] == 0

    res_demo = cli_runner.invoke(commands.app, ["demo"])
    assert res_demo.exit_code == 0
    assert "SIMULATED DEMO" in res_demo.output


def test_cli_install_dry_run_and_profile_alias(patched_hub: ToolHub) -> None:
    res = cli_runner.invoke(commands.app, ["install", "--profile", "digital", "--dry-run"])
    assert res.exit_code == 0
    assert "DRY RUN" in res.output
    assert "No changes were made." in res.output

    res_alias = cli_runner.invoke(commands.app, ["install-profile", "analog", "--dry-run"])
    assert res_alias.exit_code == 0
    assert "KiCad" in res_alias.output


def test_cli_update_config_and_logs(patched_hub: ToolHub) -> None:
    res_upd = cli_runner.invoke(commands.app, ["update", "--check-only"])
    assert res_upd.exit_code == 0
    assert "update-available" in res_upd.output
    assert "unsupported-update" in res_upd.output

    res_cfg_dry = cli_runner.invoke(
        commands.app, ["config", "set", "log_level", "DEBUG", "--dry-run"]
    )
    assert res_cfg_dry.exit_code == 0
    assert "DRY RUN" in res_cfg_dry.output
    assert patched_hub.config_manager.load().log_level == "INFO"

    res_cfg_set = cli_runner.invoke(commands.app, ["config", "set", "log_level", "WARNING"])
    assert res_cfg_set.exit_code == 0
    assert patched_hub.config_manager.load().log_level == "WARNING"

    res_logs = cli_runner.invoke(commands.app, ["logs", "--tail", "10"])
    assert res_logs.exit_code == 0


def test_cli_unknown_tool_raises_toolhub_error(patched_hub: ToolHub) -> None:
    res = cli_runner.invoke(commands.app, ["check", "does-not-exist"])
    assert res.exit_code != 0
    assert isinstance(res.exception, UnknownToolError)

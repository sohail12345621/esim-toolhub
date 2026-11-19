"""Tests for DependencyChecker, compatibility evaluation and Doctor audits."""

from __future__ import annotations

from pathlib import Path

from esim_toolhub.core.models import (
    CheckLevel,
    OSFamily,
    PathIssue,
    ToolReport,
    ToolStatus,
)
from esim_toolhub.core.registry import Registry
from esim_toolhub.core.runner import CommandResult
from esim_toolhub.dependency.checker import DependencyChecker, evaluate_compatibility
from esim_toolhub.dependency.doctor import run_doctor
from esim_toolhub.detection.executable import ExecutableLocator
from esim_toolhub.detection.version import Version, require_version
from tests.conftest import FakeRunner, RaisingRunner, make_system


def test_evaluate_compatibility_covers_installed_outdated_tested_up_to(registry: Registry) -> None:
    kicad = registry.tool("kicad")
    assert evaluate_compatibility(kicad, require_version("9.0.1"))[0] is ToolStatus.INSTALLED
    assert evaluate_compatibility(kicad, require_version("6.0.9"))[0] is ToolStatus.OUTDATED
    status, _, warnings = evaluate_compatibility(kicad, require_version("10.0.8"))
    assert status is ToolStatus.INSTALLED
    assert any("validated with eSim" in w for w in warnings)


def test_checker_reports_missing_installed_outdated_broken_and_unknown(
    registry: Registry,
) -> None:
    sys_info = make_system(OSFamily.LINUX)

    # MISSING
    locator_empty = ExecutableLocator(sys_info, which=lambda _: None, is_executable=lambda _: False)
    missing = DependencyChecker(sys_info, locator_empty, FakeRunner()).check(
        registry.tool("ngspice")
    )
    assert missing.status is ToolStatus.MISSING
    assert "esim-toolhub install ngspice" in missing.recommendation

    # INSTALLED
    locator_ok = ExecutableLocator(
        sys_info, which=lambda n: f"/usr/bin/{n}" if n == "ngspice" else None
    )
    runner_ok = FakeRunner(lambda argv: CommandResult(argv, 0, "** ngspice-44 : simulator\n"))
    installed = DependencyChecker(sys_info, locator_ok, runner_ok).check(registry.tool("ngspice"))
    assert installed.status is ToolStatus.INSTALLED
    assert str(installed.version) == "44.0"
    assert installed.on_path is True

    # OUTDATED
    runner_old = FakeRunner(lambda argv: CommandResult(argv, 0, "** ngspice-30 : old\n"))
    outdated = DependencyChecker(sys_info, locator_ok, runner_old).check(registry.tool("ngspice"))
    assert outdated.status is ToolStatus.OUTDATED

    # BROKEN (timeout)
    runner_timeout = FakeRunner(lambda argv: CommandResult(argv, -1, "", "", timed_out=True))
    broken_timeout = DependencyChecker(sys_info, locator_ok, runner_timeout).check(
        registry.tool("ngspice")
    )
    assert broken_timeout.status is ToolStatus.BROKEN

    # BROKEN (execution exception)
    broken_exec = DependencyChecker(sys_info, locator_ok, RaisingRunner()).check(
        registry.tool("ngspice")
    )
    assert broken_exec.status is ToolStatus.BROKEN

    # UNKNOWN (exit 0 but unparseable banner)
    runner_gibberish = FakeRunner(lambda argv: CommandResult(argv, 0, "hello world\n"))
    unknown = DependencyChecker(sys_info, locator_ok, runner_gibberish).check(
        registry.tool("ngspice")
    )
    assert unknown.status is ToolStatus.UNKNOWN


def test_checker_detects_ghdl_mcode_variant_warning_and_host_prereqs(registry: Registry) -> None:
    sys_info = make_system(OSFamily.LINUX)
    locator = ExecutableLocator(sys_info, which=lambda n: "/usr/bin/ghdl" if n == "ghdl" else None)
    runner = FakeRunner(
        lambda argv: CommandResult(
            argv,
            0,
            "GHDL 6.0.0 (tarball) [Dunoon edition]\n mcode code generator\n",
        )
    )
    report = DependencyChecker(sys_info, locator, runner).check(registry.tool("ghdl"))
    assert report.status is ToolStatus.INSTALLED
    assert report.variant == "mcode"
    assert any("NGHDL" in w for w in report.warnings)
    # gcc/cc/clang not found -> host requirement unsatisfied
    assert any(not req.satisfied for req in report.host_requirements)


def test_doctor_computes_overall_health_and_flags_issues(registry: Registry) -> None:
    sys_info = make_system(OSFamily.LINUX)
    ngspice = registry.tool("ngspice")
    kicad = registry.tool("kicad")
    ghdl = registry.tool("ghdl")

    # All required present -> HEALTHY
    healthy = run_doctor(
        registry,
        sys_info,
        [
            ToolReport(
                ngspice, ToolStatus.INSTALLED, Version((44, 0, 0)), Path("/usr/bin/ngspice"), True
            ),
            ToolReport(
                kicad, ToolStatus.INSTALLED, Version((9, 0, 1)), Path("/usr/bin/kicad-cli"), True
            ),
        ],
    )
    assert healthy.overall == "HEALTHY"
    assert healthy.failures == 0

    # Required missing + PATH risk + optional missing -> NEEDS ATTENTION
    unhealthy = run_doctor(
        registry,
        sys_info,
        [
            ToolReport(ngspice, ToolStatus.MISSING),
            ToolReport(
                kicad, ToolStatus.INSTALLED, Version((9, 0, 1)), Path("/opt/kicad/kicad-cli"), False
            ),
            ToolReport(ghdl, ToolStatus.MISSING),
        ],
        path_issues=[PathIssue("./bin", "relative entry (security risk)")],
    )
    assert unhealthy.overall == "NEEDS ATTENTION"
    assert unhealthy.failures == 1
    assert any(
        c.level is CheckLevel.WARN and "not available on PATH" in c.title for c in unhealthy.checks
    )
    assert any(c.level is CheckLevel.WARN and "relative" in c.title for c in unhealthy.checks)

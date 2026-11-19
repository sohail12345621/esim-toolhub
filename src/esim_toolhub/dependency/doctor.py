"""Full environment audit producing PASS / WARN / FAIL checks."""

from __future__ import annotations

from collections.abc import Sequence

from esim_toolhub.core.models import (
    CheckLevel,
    DoctorCheck,
    DoctorReport,
    PathIssue,
    SystemInfo,
    ToolReport,
    ToolStatus,
)
from esim_toolhub.core.registry import Registry
from esim_toolhub.detection.version import require_version


def run_doctor(
    registry: Registry,
    system: SystemInfo,
    reports: Sequence[ToolReport],
    path_issues: Sequence[PathIssue] = (),
    writable_dirs: Sequence[tuple[str, bool]] = (),
) -> DoctorReport:
    checks: list[DoctorCheck] = []
    add = checks.append

    platform = registry.platform(system.os_family.value)
    if platform is None:
        add(DoctorCheck(CheckLevel.FAIL, "Operating system unsupported", system.os_name))
    elif platform.supported:
        add(DoctorCheck(CheckLevel.PASS, "Operating system supported", system.os_name))
    else:
        add(DoctorCheck(CheckLevel.WARN, f"Operating system {platform.status}", platform.notes))

    if platform and platform.architectures and system.architecture not in platform.architectures:
        add(DoctorCheck(CheckLevel.WARN, f"Architecture {system.architecture} is untested"))
    else:
        add(DoctorCheck(CheckLevel.PASS, "Architecture supported", system.architecture))

    py_min = require_version(registry.python_minimum)
    py = require_version(system.python_version)
    if py >= py_min:
        add(DoctorCheck(CheckLevel.PASS, "Python supported", system.python_version))
    else:
        add(
            DoctorCheck(
                CheckLevel.FAIL, f"Python {system.python_version} < {registry.python_minimum}"
            )
        )

    if system.is_wsl:
        add(DoctorCheck(CheckLevel.INFO, "Running under WSL", "GUI tools need WSLg or an X server"))
    if system.is_admin:
        add(
            DoctorCheck(
                CheckLevel.WARN,
                "Running with administrator/root privileges",
                "Not needed for checks; only package installs that require it should be elevated",
            )
        )

    if system.package_managers:
        names = ", ".join(sorted(system.package_managers))
        add(DoctorCheck(CheckLevel.PASS, "Package manager available", names))
    else:
        add(
            DoctorCheck(
                CheckLevel.WARN,
                "No supported package manager found",
                "Only verified archive or manual installs are possible",
            )
        )

    for report in reports:
        spec = report.spec
        name = spec.display_name
        missing_level = CheckLevel.FAIL if spec.required else CheckLevel.WARN
        kind = "required" if spec.required else "optional"
        if report.status is ToolStatus.MISSING:
            add(DoctorCheck(missing_level, f"{name} missing ({kind})", report.recommendation))
            continue
        if report.status is ToolStatus.INSTALLED:
            add(
                DoctorCheck(
                    CheckLevel.PASS, f"{name} detected", f"{report.version} at {report.executable}"
                )
            )
        elif report.status is ToolStatus.UNKNOWN:
            add(DoctorCheck(CheckLevel.WARN, f"{name} version unknown", report.message))
        else:
            level = missing_level if report.status is not ToolStatus.BROKEN else CheckLevel.FAIL
            add(DoctorCheck(level, f"{name} {report.status.value.lower()}", report.message))
        if report.on_path is False:
            add(
                DoctorCheck(
                    CheckLevel.WARN, f"{name} not available on PATH", str(report.executable)
                )
            )
        for warning in report.warnings:
            if "not on PATH" not in warning:
                add(DoctorCheck(CheckLevel.WARN, f"{name}: {warning}"))
        for req in report.host_requirements:
            if not req.satisfied:
                add(
                    DoctorCheck(
                        CheckLevel.WARN,
                        f"{name} prerequisite missing: {req.requirement.name}",
                        req.requirement.reason,
                    )
                )

    for issue in path_issues:
        level = CheckLevel.WARN if "relative" in issue.problem else CheckLevel.INFO
        add(DoctorCheck(level, f"PATH entry {issue.problem}", issue.entry))

    for label, ok in writable_dirs:
        if ok:
            add(DoctorCheck(CheckLevel.PASS, f"{label} directory writable"))
        else:
            add(DoctorCheck(CheckLevel.WARN, f"{label} directory not writable"))

    return DoctorReport(checks)

"""Dependency auditing: locate each tool, query its version, evaluate compatibility."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

from esim_toolhub.core.exceptions import CommandExecutionError
from esim_toolhub.core.models import (
    HostRequirementResult,
    SystemInfo,
    ToolReport,
    ToolSpec,
    ToolStatus,
)
from esim_toolhub.core.runner import CommandRunner
from esim_toolhub.detection.executable import ExecutableLocator
from esim_toolhub.detection.version import Version, require_version
from esim_toolhub.tools import GenericToolAdapter, get_adapter

log = logging.getLogger(__name__)


def evaluate_compatibility(spec: ToolSpec, version: Version) -> tuple[ToolStatus, str, list[str]]:
    """Pure version policy. Returns (status, message, warnings).

    * version >= maximum_version            -> INCOMPATIBLE
    * version <  minimum_version            -> OUTDATED
    * major   >  tested_up_to major         -> INSTALLED with a warning
    """
    warnings: list[str] = []
    if spec.maximum_version and version >= require_version(spec.maximum_version):
        return (
            ToolStatus.INCOMPATIBLE,
            f"{version} is at or above the unsupported version {spec.maximum_version}",
            warnings,
        )
    if spec.minimum_version and version < require_version(spec.minimum_version):
        return (
            ToolStatus.OUTDATED,
            f"{version} is older than required >= {spec.minimum_version}",
            warnings,
        )
    if spec.tested_up_to and version.major > require_version(spec.tested_up_to).major:
        warnings.append(
            f"{spec.display_name} {version} is newer than the latest version validated with eSim "
            f"({spec.tested_up_to}.x)"
        )
    if version.prerelease:
        warnings.append(f"{version.raw} looks like a pre-release build")
    return ToolStatus.INSTALLED, "Compatible", warnings


def recommendation_for(report: ToolReport) -> str:
    name = report.spec.name
    if report.status is ToolStatus.MISSING:
        return f"Install using ToolHub: esim-toolhub install {name}"
    if report.status is ToolStatus.OUTDATED:
        return f"Upgrade: esim-toolhub update {name}"
    if report.status is ToolStatus.BROKEN:
        return f"Reinstall: esim-toolhub install {name} --force"
    if report.status is ToolStatus.INCOMPATIBLE:
        return "Install a supported build (see 'esim-toolhub list' for supported versions)"
    if report.status is ToolStatus.UNKNOWN:
        return "Verify the installation manually; ToolHub could not determine its version"
    if report.on_path is False:
        return "Add the tool directory to PATH: esim-toolhub config env"
    return ""


class DependencyChecker:
    def __init__(
        self,
        system: SystemInfo,
        locator: ExecutableLocator,
        runner: CommandRunner,
        adapter_factory: Callable[[ToolSpec], GenericToolAdapter] = get_adapter,
    ) -> None:
        self.system = system
        self.locator = locator
        self.runner = runner
        self.adapter_factory = adapter_factory

    def check_many(self, specs: Iterable[ToolSpec]) -> list[ToolReport]:
        return [self.check(spec) for spec in specs]

    def check(self, spec: ToolSpec) -> ToolReport:
        report = self._check(spec)
        report.host_requirements = self.check_host_requirements(spec)
        if not report.recommendation:
            report.recommendation = recommendation_for(report)
        log.info(
            "tool checked",
            extra={
                "event": "tool_check",
                "tool": spec.name,
                "status": report.status.value,
                "version": str(report.version) if report.version else None,
            },
        )
        return report

    def check_host_requirements(self, spec: ToolSpec) -> list[HostRequirementResult]:
        os_name = self.system.os_family.value
        return [
            HostRequirementResult(req, self.locator.find_any(req.executables))
            for req in spec.host_requirements
            if not req.platforms or os_name in req.platforms
        ]

    def _check(self, spec: ToolSpec) -> ToolReport:
        os_family = self.system.os_family
        if not spec.executables_for(os_family):
            return ToolReport(
                spec, ToolStatus.INCOMPATIBLE, message=f"Not available for {os_family.value}"
            )
        archs = spec.architectures.get(os_family.value)
        if archs and self.system.architecture not in archs:
            return ToolReport(
                spec,
                ToolStatus.INCOMPATIBLE,
                message=(
                    f"Architecture {self.system.architecture} not supported "
                    f"(needs {', '.join(archs)})"
                ),
            )

        adapter = self.adapter_factory(spec)
        located = self.locator.locate(spec)
        if located is None:
            fallback = adapter.fallback_executables(os_family)
            located = self.locator.locate_names(fallback, spec) if fallback else None
        if located is None:
            return ToolReport(spec, ToolStatus.MISSING, message="Executable not found")

        report = ToolReport(
            spec, ToolStatus.UNKNOWN, executable=located.path, on_path=located.on_path
        )
        if not adapter.can_probe(located.path):
            version = adapter.fallback_version(located.path)
            if version is None:
                report.message = (
                    f"Found {located.path.name} but no version-reporting CLI "
                    f"({'/'.join(spec.executables_for(os_family))})"
                )
                return report
            return self._apply_version(report, version, "inferred from install path")

        try:
            result = self.runner.run(
                adapter.version_command(located.path, os_family), timeout=spec.version_timeout
            )
        except CommandExecutionError as exc:
            report.status = ToolStatus.BROKEN
            report.message = str(exc)
            return report

        report.raw_output = result.output[:2000]
        if result.timed_out:
            report.status, report.message = adapter.on_timeout(located.path, os_family)
            return report

        version = adapter.parse_version(result.output) or adapter.fallback_version(located.path)
        if version is None:
            if result.returncode != 0:
                report.status = ToolStatus.BROKEN
                report.message = f"Version query exited with code {result.returncode}"
            else:
                report.message = "Could not parse version from tool output"
            return report

        variant = adapter.detect_variant(result.output)
        if variant:
            report.variant = variant
            rule = spec.variant
            if rule and variant in rule.unsupported:
                report.warnings.append(f"{rule.label} '{variant}': {rule.reason}")
        return self._apply_version(report, version)

    @staticmethod
    def _apply_version(report: ToolReport, version: Version, note: str = "") -> ToolReport:
        status, message, warnings = evaluate_compatibility(report.spec, version)
        report.version = version
        report.status = status
        report.message = f"{message} ({note})" if note else message
        report.warnings.extend(warnings)
        if report.on_path is False and status is ToolStatus.INSTALLED:
            report.warnings.append(
                f"{report.executable.parent if report.executable else ''} is not on PATH"
            )
        return report

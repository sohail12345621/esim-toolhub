"""Safe update checker distinguishing up-to-date, available, unsupported and unknown updates."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from esim_toolhub.core.exceptions import CommandExecutionError
from esim_toolhub.core.models import (
    ToolReport,
    ToolSpec,
    ToolStatus,
    UpdateInfo,
    UpdateState,
)
from esim_toolhub.core.runner import CommandRunner
from esim_toolhub.detection.version import Version, parse_version, require_version
from esim_toolhub.installers.base import Installer
from esim_toolhub.installers.package_managers import query_available_version

log = logging.getLogger(__name__)


class UpdateChecker:
    def __init__(
        self,
        runner: CommandRunner,
        installer: Installer | None = None,
    ) -> None:
        self.runner = runner
        self.installer = installer

    def check_many(
        self, reports: Iterable[ToolReport], *, online: bool = False
    ) -> list[UpdateInfo]:
        return [self.check(report, online=online) for report in reports]

    def check(self, report: ToolReport, *, online: bool = False) -> UpdateInfo:
        spec = report.spec
        latest, source = self._resolve_latest(spec, online=online)
        latest_str = str(latest) if latest else None

        if report.status is ToolStatus.MISSING:
            return UpdateInfo(
                tool=spec.name,
                display_name=spec.display_name,
                state=UpdateState.NOT_INSTALLED,
                current=None,
                latest=latest_str,
                source=source,
                message=f"Not installed. Run 'esim-toolhub install {spec.name}'.",
            )

        if report.version is None:
            return UpdateInfo(
                tool=spec.name,
                display_name=spec.display_name,
                state=UpdateState.UNKNOWN,
                current=None,
                latest=latest_str,
                source=source,
                message="Installed version could not be determined.",
            )

        current_str = str(report.version)
        if latest is None:
            return UpdateInfo(
                tool=spec.name,
                display_name=spec.display_name,
                state=UpdateState.UNKNOWN,
                current=current_str,
                latest=None,
                source=source,
                message=(
                    "No known upstream version in registry "
                    "(try --online if a package manager is present)."
                ),
            )

        if latest <= report.version:
            return UpdateInfo(
                tool=spec.name,
                display_name=spec.display_name,
                state=UpdateState.UP_TO_DATE,
                current=current_str,
                latest=latest_str,
                source=source,
                message="Up to date.",
            )

        if spec.maximum_version and latest >= require_version(spec.maximum_version):
            return UpdateInfo(
                tool=spec.name,
                display_name=spec.display_name,
                state=UpdateState.UNSUPPORTED_UPDATE,
                current=current_str,
                latest=latest_str,
                source=source,
                message=(
                    f"{latest_str} reaches unsupported version {spec.maximum_version}; "
                    f"skipping automatic upgrade."
                ),
            )

        if spec.tested_up_to and latest.major > require_version(spec.tested_up_to).major:
            return UpdateInfo(
                tool=spec.name,
                display_name=spec.display_name,
                state=UpdateState.UNSUPPORTED_UPDATE,
                current=current_str,
                latest=latest_str,
                source=source,
                message=(
                    f"{latest_str} is a newer major release than eSim's validated "
                    f"{spec.tested_up_to}.x series; upgrade manually only if intended."
                ),
            )

        return UpdateInfo(
            tool=spec.name,
            display_name=spec.display_name,
            state=UpdateState.UPDATE_AVAILABLE,
            current=current_str,
            latest=latest_str,
            source=source,
            message=f"Update available ({current_str} -> {latest_str}).",
        )

    def _resolve_latest(self, spec: ToolSpec, *, online: bool) -> tuple[Version | None, str]:
        if online and self.installer is not None:
            method = self.installer.select_method(spec)
            if method is not None and method.type.is_package_manager:
                try:
                    queried = query_available_version(self.runner, method)
                except CommandExecutionError as exc:
                    log.debug("Online version query failed for %s: %s", spec.name, exc)
                    queried = None
                if queried is not None:
                    return queried, method.type.value
        if spec.latest_known_version:
            return parse_version(spec.latest_known_version), "registry"
        return None, "none"

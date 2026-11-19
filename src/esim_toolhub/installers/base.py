"""Abstract Installer and shared plan/execute/verify pipeline.

Every operation first produces an ``InstallPlan`` (pure data, no side effects).
``--dry-run`` displays the plan and stops; real execution runs the plan's steps
and always finishes with post-install verification.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlsplit

from esim_toolhub.configuration.environment import EnvironmentManager
from esim_toolhub.configuration.manager import ToolHubConfig
from esim_toolhub.core.exceptions import (
    CommandExecutionError,
    SecurityError,
    ToolHubError,
)
from esim_toolhub.core.models import (
    InstallMethod,
    InstallPlan,
    InstallResult,
    MethodType,
    OSFamily,
    PlanStep,
    StepKind,
    SystemInfo,
    ToolReport,
    ToolSpec,
    ToolStatus,
)
from esim_toolhub.core.runner import CommandRunner
from esim_toolhub.dependency.checker import DependencyChecker
from esim_toolhub.installers.downloader import Downloader
from esim_toolhub.installers.package_managers import (
    install_command,
    refresh_command,
    uninstall_command,
    upgrade_command,
)
from esim_toolhub.paths import AppPaths
from esim_toolhub.security.archive import safe_extract
from esim_toolhub.security.checksum import verify_sha256

log = logging.getLogger(__name__)


class Installer(ABC):
    os_family: OSFamily

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
    ) -> None:
        self.system = system
        self.checker = checker
        self.runner = runner
        self.downloader = downloader
        self.environment = environment
        self.config = config
        self.paths = paths
        self.trusted_hosts = trusted_hosts

    # ------------------------------------------------------------- platform hooks
    @abstractmethod
    def allowed_methods(self) -> tuple[MethodType, ...]:
        """Method types legal on this OS."""

    def needs_sudo(self, method: InstallMethod) -> bool:
        """Whether package-manager commands should be prefixed with sudo."""
        return False

    def privilege_blocker(self, method: InstallMethod) -> str | None:
        """Return a human-readable reason if required privileges are missing."""
        return None

    def platform_notes(self) -> list[str]:
        return []

    def _method_compatible(self, method: InstallMethod) -> bool:
        if method.type not in self.allowed_methods():
            return False
        if method.architectures and self.system.architecture not in method.architectures:
            return False
        if method.distros:
            system_distros = {self.system.distro_id, *self.system.distro_like} - {""}
            if not system_distros.intersection(method.distros):
                return False
        return not (
            method.type.is_package_manager and method.type.value not in self.system.package_managers
        )

    # ------------------------------------------------------------ public workflow
    def detect(self, spec: ToolSpec) -> ToolReport:
        return self.checker.check(spec)

    def verify(self, spec: ToolSpec) -> ToolReport:
        return self.checker.check(spec)

    def select_method(self, spec: ToolSpec, preferred: str | None = None) -> InstallMethod | None:
        candidates = [m for m in spec.methods_for(self.os_family) if self._method_compatible(m)]
        if not candidates:
            return None
        pref = preferred or self.config.preferred_install_method
        if pref:
            for method in candidates:
                if method.type.value == pref:
                    return method
        # Prefer automated methods (package managers, then archives) over manual instructions.
        for method in candidates:
            if method.type is not MethodType.MANUAL:
                return method
        return candidates[0]

    def plan_install(
        self,
        spec: ToolSpec,
        current: ToolReport | None = None,
        *,
        force: bool = False,
        preferred_method: str | None = None,
    ) -> InstallPlan:
        current = current or self.detect(spec)
        current_ver = str(current.version) if current.version else None
        notes = list(self.platform_notes())

        if current.status is ToolStatus.INSTALLED and not force:
            return InstallPlan(
                tool=spec,
                action="skip",
                method=None,
                current_version=current_ver,
                target_version=current_ver,
                notes=[
                    *notes,
                    f"{spec.display_name} {current_ver} is already installed and compatible "
                    f"(use --force to reinstall).",
                ],
            )

        method = self.select_method(spec, preferred=preferred_method)
        if method is None:
            return InstallPlan(
                tool=spec,
                action="install",
                method=None,
                current_version=current_ver,
                target_version=spec.latest_known_version or spec.minimum_version,
                notes=notes,
                blocked_reason=(
                    f"No compatible installation method found for {spec.display_name} "
                    f"on {self.system.os_name} ({self.system.architecture})."
                ),
            )

        return self._build_plan(spec, "install", method, current_ver, notes)

    def plan_update(
        self,
        spec: ToolSpec,
        current: ToolReport | None = None,
        *,
        preferred_method: str | None = None,
    ) -> InstallPlan:
        current = current or self.detect(spec)
        current_ver = str(current.version) if current.version else None
        notes = list(self.platform_notes())

        if current.status is ToolStatus.MISSING:
            return InstallPlan(
                tool=spec,
                action="skip",
                method=None,
                current_version=None,
                target_version=spec.latest_known_version,
                notes=[*notes, f"{spec.display_name} is not installed; run install instead."],
            )

        method = self.select_method(spec, preferred=preferred_method)
        if method is None:
            return InstallPlan(
                tool=spec,
                action="update",
                method=None,
                current_version=current_ver,
                target_version=spec.latest_known_version,
                notes=notes,
                blocked_reason=(
                    f"No update method available for {spec.display_name} on this system."
                ),
            )

        return self._build_plan(spec, "update", method, current_ver, notes)

    def plan_uninstall(
        self,
        spec: ToolSpec,
        current: ToolReport | None = None,
        *,
        preferred_method: str | None = None,
    ) -> InstallPlan:
        current = current or self.detect(spec)
        current_ver = str(current.version) if current.version else None
        notes = list(self.platform_notes())

        if current.status is ToolStatus.MISSING:
            return InstallPlan(
                tool=spec,
                action="skip",
                method=None,
                current_version=None,
                target_version=None,
                notes=[*notes, f"{spec.display_name} is not installed."],
            )

        managed = self.environment.managed_dirs(spec.name)
        if managed:
            install_root = self.paths.tools_dir / spec.name
            steps = [
                PlanStep(
                    StepKind.UNREGISTER_PATH,
                    f"Remove {spec.display_name} managed files ({install_root}) and PATH entry",
                    data={"install_root": str(install_root)},
                ),
                PlanStep(StepKind.DETECT, f"Verify {spec.display_name} is no longer detected"),
            ]
            return InstallPlan(
                tool=spec,
                action="uninstall",
                method=InstallMethod(type=MethodType.ARCHIVE),
                current_version=current_ver,
                target_version=None,
                steps=steps,
                notes=notes,
            )

        method = self.select_method(spec, preferred=preferred_method)
        if method is None or not method.type.is_package_manager:
            return InstallPlan(
                tool=spec,
                action="uninstall",
                method=method,
                current_version=current_ver,
                target_version=None,
                notes=notes,
                blocked_reason=(
                    f"{spec.display_name} was not installed via a ToolHub-managed archive or "
                    f"supported package manager; uninstall it manually."
                ),
            )

        use_sudo = self.needs_sudo(method)
        blocker = self.privilege_blocker(method)
        cmd = uninstall_command(method, use_sudo=use_sudo)
        steps = [
            PlanStep(
                StepKind.PACKAGE_REMOVE, f"Remove {method.package} via {method.type.value}", cmd
            ),
            PlanStep(StepKind.DETECT, f"Verify {spec.display_name} is removed"),
        ]
        return InstallPlan(
            tool=spec,
            action="uninstall",
            method=method,
            current_version=current_ver,
            target_version=None,
            steps=steps,
            requires_admin=use_sudo or method.requires_admin,
            notes=notes,
            blocked_reason=blocker,
        )

    def _build_plan(
        self,
        spec: ToolSpec,
        action: str,
        method: InstallMethod,
        current_ver: str | None,
        notes: list[str],
    ) -> InstallPlan:
        target = (
            method.version
            or spec.latest_known_version
            or (f">={spec.minimum_version}" if spec.minimum_version else None)
        )
        if method.notes:
            notes.append(method.notes)

        if method.type is MethodType.MANUAL:
            steps = [PlanStep(StepKind.MANUAL, line) for line in method.instructions]
            return InstallPlan(
                tool=spec,
                action=action,
                method=method,
                current_version=current_ver,
                target_version=target,
                steps=steps,
                notes=notes,
                blocked_reason=(
                    f"Automated {action} is not available for {spec.display_name} on "
                    f"{self.system.os_name}; follow the manual steps."
                ),
            )

        if method.type is MethodType.ARCHIVE:
            blocker = None
            if self.config.verify_checksums and not method.sha256:
                blocker = (
                    f"Archive for {spec.display_name} has no SHA256 checksum and "
                    f"verify_checksums is enabled."
                )
            filename = Path(urlsplit(method.url or "").path).name or f"{spec.name}.archive"
            install_root = self.paths.tools_dir / spec.name
            steps = [
                PlanStep(
                    StepKind.DOWNLOAD,
                    f"Download {filename} from {method.url}",
                    data={"url": method.url, "filename": filename},
                ),
            ]
            if method.sha256:
                steps.append(
                    PlanStep(
                        StepKind.VERIFY_CHECKSUM,
                        f"Verify SHA256 ({method.sha256[:12]}...)",
                        data={"sha256": method.sha256},
                    )
                )
            else:
                notes.append("WARNING: No SHA256 digest available for this archive.")
            steps.extend(
                [
                    PlanStep(
                        StepKind.EXTRACT,
                        f"Safely extract archive into {install_root}",
                        data={"install_root": str(install_root)},
                    ),
                    PlanStep(
                        StepKind.REGISTER_PATH,
                        f"Register {spec.display_name} bin directory in ToolHub environment",
                        data={"install_root": str(install_root)},
                    ),
                    PlanStep(StepKind.DETECT, f"Detect {spec.display_name} executable"),
                    PlanStep(
                        StepKind.VERIFY_VERSION,
                        f"Verify {spec.display_name} version & compatibility",
                    ),
                ]
            )
            return InstallPlan(
                tool=spec,
                action=action,
                method=method,
                current_version=current_ver,
                target_version=target,
                steps=steps,
                requires_admin=False,
                notes=notes,
                blocked_reason=blocker,
            )

        # Package manager install or upgrade
        use_sudo = self.needs_sudo(method)
        blocker = self.privilege_blocker(method)
        steps = []
        refresh = refresh_command(method, use_sudo=use_sudo)
        if refresh:
            steps.append(
                PlanStep(
                    StepKind.REFRESH_INDEX, f"Refresh {method.type.value} package index", refresh
                )
            )
        if action == "update":
            cmd = upgrade_command(method, use_sudo=use_sudo)
            steps.append(
                PlanStep(
                    StepKind.PACKAGE_UPGRADE,
                    f"Upgrade {method.package} via {method.type.value}",
                    cmd,
                )
            )
        else:
            cmd = install_command(method, use_sudo=use_sudo)
            steps.append(
                PlanStep(
                    StepKind.PACKAGE_INSTALL,
                    f"Install {method.package} via {method.type.value}",
                    cmd,
                )
            )
        steps.extend(
            [
                PlanStep(StepKind.DETECT, f"Detect {spec.display_name} executable"),
                PlanStep(
                    StepKind.VERIFY_VERSION, f"Verify {spec.display_name} version & compatibility"
                ),
            ]
        )
        return InstallPlan(
            tool=spec,
            action=action,
            method=method,
            current_version=current_ver,
            target_version=target,
            steps=steps,
            requires_admin=use_sudo or method.requires_admin,
            notes=notes,
            blocked_reason=blocker,
        )

    def execute(self, plan: InstallPlan) -> InstallResult:
        spec = plan.tool
        if plan.action == "skip":
            report = self.verify(spec)
            msg = plan.notes[-1] if plan.notes else f"{spec.display_name} skipped"
            return InstallResult(spec.name, True, msg, report)
        if plan.blocked_reason:
            log.warning(
                "Install plan blocked",
                extra={
                    "event": "install_blocked",
                    "tool": spec.name,
                    "reason": plan.blocked_reason,
                },
            )
            return InstallResult(spec.name, False, plan.blocked_reason)

        log.info(
            "Executing plan",
            extra={
                "event": f"{plan.action}_start",
                "tool": spec.name,
                "method": plan.method.label() if plan.method else "none",
            },
        )
        try:
            with tempfile.TemporaryDirectory(prefix=f"esim-toolhub-{spec.name}-") as tmp_dir:
                downloaded: Path | None = None
                for step in plan.steps:
                    if step.kind in (
                        StepKind.REFRESH_INDEX,
                        StepKind.PACKAGE_INSTALL,
                        StepKind.PACKAGE_UPGRADE,
                        StepKind.PACKAGE_REMOVE,
                    ):
                        if step.command is None:
                            return InstallResult(
                                spec.name, False, f"Missing command for {step.description}"
                            )
                        res = self.runner.run(
                            step.command, timeout=float(self.config.install_timeout_s)
                        )
                        if not res.ok:
                            detail = (
                                res.output.splitlines()[-1]
                                if res.output
                                else f"exit code {res.returncode}"
                            )
                            if res.timed_out:
                                detail = f"timed out after {self.config.install_timeout_s}s"
                            msg = f"{step.description} failed: {detail}"
                            log.error(msg, extra={"event": "install_fail", "tool": spec.name})
                            return InstallResult(spec.name, False, msg)

                    elif step.kind is StepKind.DOWNLOAD:
                        url = str(step.data["url"])
                        filename = str(step.data["filename"])
                        max_bytes = self.config.download_max_mb * 1024 * 1024
                        downloaded = self.downloader.download(
                            url,
                            Path(tmp_dir) / filename,
                            trusted_hosts=self.trusted_hosts,
                            max_bytes=max_bytes,
                        )

                    elif step.kind is StepKind.VERIFY_CHECKSUM:
                        if downloaded is None:
                            return InstallResult(spec.name, False, "No downloaded file to verify")
                        verify_sha256(downloaded, str(step.data["sha256"]))

                    elif step.kind is StepKind.EXTRACT:
                        if downloaded is None:
                            return InstallResult(
                                spec.name, False, "No downloaded archive to extract"
                            )
                        install_root = Path(step.data["install_root"])
                        staging = Path(tmp_dir) / "extracted"
                        safe_extract(downloaded, staging)
                        if install_root.exists():
                            shutil.rmtree(install_root)
                        install_root.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(staging), str(install_root))

                    elif step.kind is StepKind.REGISTER_PATH:
                        install_root = Path(step.data["install_root"])
                        bin_dir = self._find_bin_dir(install_root, spec)
                        if bin_dir is None:
                            return InstallResult(
                                spec.name,
                                False,
                                f"Extracted archive did not contain any expected executable "
                                f"({', '.join(spec.executables_for(self.os_family))})",
                            )
                        self.environment.register(spec.name, bin_dir)

                    elif step.kind is StepKind.UNREGISTER_PATH:
                        install_root = Path(step.data["install_root"])
                        if install_root.exists():
                            shutil.rmtree(install_root)
                        self.environment.unregister(spec.name)

                    elif step.kind in (StepKind.DETECT, StepKind.VERIFY_VERSION):
                        # Verification runs once at the end for a single consistent report.
                        continue

        except (ToolHubError, SecurityError, CommandExecutionError, OSError) as exc:
            log.error(
                "Plan execution error",
                extra={"event": "install_error", "tool": spec.name, "error": str(exc)},
            )
            return InstallResult(spec.name, False, str(exc))

        # Mandatory post-action verification: never claim success from exit code alone.
        report = self.verify(spec)
        if plan.action == "uninstall":
            ok = report.status is ToolStatus.MISSING
            msg = (
                f"{spec.display_name} removed and verified absent."
                if ok
                else (
                    f"Uninstall finished, but {spec.display_name} is still detected at "
                    f"{report.executable}."
                )
            )
            return InstallResult(spec.name, ok, msg, report)

        if report.status is ToolStatus.INSTALLED:
            msg = f"{spec.display_name} {report.version} verified at {report.executable}"
            log.info(msg, extra={"event": f"{plan.action}_ok", "tool": spec.name})
            return InstallResult(spec.name, True, msg, report)

        msg = (
            f"{spec.display_name} {plan.action} finished, but post-install verification failed "
            f"(status={report.status.value}: {report.message})"
        )
        log.error(
            msg, extra={"event": "verify_fail", "tool": spec.name, "status": report.status.value}
        )
        return InstallResult(spec.name, False, msg, report)

    def _find_bin_dir(self, root: Path, spec: ToolSpec) -> Path | None:
        names = {n.lower() for n in spec.executables_for(self.os_family)}
        for candidate in root.rglob("*"):
            if candidate.is_file() and candidate.name.lower() in names:
                return candidate.parent
        return None

    def install(
        self,
        spec: ToolSpec,
        *,
        dry_run: bool = False,
        force: bool = False,
        preferred_method: str | None = None,
    ) -> tuple[InstallPlan, InstallResult | None]:
        plan = self.plan_install(spec, force=force, preferred_method=preferred_method)
        if dry_run:
            return plan, None
        return plan, self.execute(plan)

    def update(
        self,
        spec: ToolSpec,
        *,
        dry_run: bool = False,
        preferred_method: str | None = None,
    ) -> tuple[InstallPlan, InstallResult | None]:
        plan = self.plan_update(spec, preferred_method=preferred_method)
        if dry_run:
            return plan, None
        return plan, self.execute(plan)

    def uninstall(
        self,
        spec: ToolSpec,
        *,
        dry_run: bool = False,
        preferred_method: str | None = None,
    ) -> tuple[InstallPlan, InstallResult | None]:
        plan = self.plan_uninstall(spec, preferred_method=preferred_method)
        if dry_run:
            return plan, None
        return plan, self.execute(plan)

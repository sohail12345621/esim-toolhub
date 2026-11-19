"""Domain models shared by every layer. Pure data: no I/O here."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from esim_toolhub.detection.version import Version


class OSFamily(str, Enum):
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"


class ToolStatus(str, Enum):
    MISSING = "MISSING"
    INSTALLED = "INSTALLED"
    OUTDATED = "OUTDATED"
    INCOMPATIBLE = "INCOMPATIBLE"
    BROKEN = "BROKEN"
    UNKNOWN = "UNKNOWN"

    @property
    def satisfied(self) -> bool:
        return self is ToolStatus.INSTALLED


class CheckLevel(str, Enum):
    PASS = "PASS"  # noqa: S105
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"


class UpdateState(str, Enum):
    UP_TO_DATE = "up-to-date"
    UPDATE_AVAILABLE = "update-available"
    UNSUPPORTED_UPDATE = "unsupported-update"
    NOT_INSTALLED = "not-installed"
    UNKNOWN = "unknown"


class MethodType(str, Enum):
    APT = "apt"
    DNF = "dnf"
    PACMAN = "pacman"
    WINGET = "winget"
    CHOCO = "choco"
    BREW = "brew"
    ARCHIVE = "archive"
    MANUAL = "manual"

    @property
    def is_package_manager(self) -> bool:
        return self not in (MethodType.ARCHIVE, MethodType.MANUAL)


class StepKind(str, Enum):
    REFRESH_INDEX = "refresh-index"
    PACKAGE_INSTALL = "package-install"
    PACKAGE_UPGRADE = "package-upgrade"
    PACKAGE_REMOVE = "package-remove"
    DOWNLOAD = "download"
    VERIFY_CHECKSUM = "verify-checksum"
    EXTRACT = "extract"
    REGISTER_PATH = "register-path"
    UNREGISTER_PATH = "unregister-path"
    DETECT = "detect"
    VERIFY_VERSION = "verify-version"
    MANUAL = "manual"


# --------------------------------------------------------------------------- registry


@dataclass(frozen=True)
class InstallMethod:
    type: MethodType
    package: str | None = None
    url: str | None = None
    sha256: str | None = None
    size: int | None = None
    version: str | None = None
    requires_admin: bool = False
    cask: bool = False
    architectures: tuple[str, ...] = ()
    distros: tuple[str, ...] = ()
    instructions: tuple[str, ...] = ()
    notes: str = ""

    def label(self) -> str:
        if self.package:
            return f"{self.type.value}:{self.package}"
        return self.type.value


@dataclass(frozen=True)
class VariantRule:
    """Detects a build variant (e.g. GHDL backend) from version output."""

    pattern: str
    label: str
    unsupported: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class HostRequirement:
    """A non-managed prerequisite such as a C++ compiler, checked for presence only."""

    name: str
    executables: tuple[str, ...]
    platforms: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    display_name: str
    description: str
    category: str
    required: bool
    executables: dict[str, tuple[str, ...]]
    version_args: tuple[str, ...] = ("--version",)
    version_pattern: str | None = None
    version_timeout: float = 15.0
    minimum_version: str | None = None
    tested_up_to: str | None = None
    maximum_version: str | None = None
    latest_known_version: str | None = None
    search_paths: dict[str, tuple[str, ...]] = field(default_factory=dict)
    install: dict[str, tuple[InstallMethod, ...]] = field(default_factory=dict)
    architectures: dict[str, tuple[str, ...]] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    host_requirements: tuple[HostRequirement, ...] = ()
    variant: VariantRule | None = None
    adapter: str | None = None
    homepage: str = ""
    esim_role: str = ""

    def executables_for(self, os_family: OSFamily) -> tuple[str, ...]:
        return self.executables.get(os_family.value, ())

    def methods_for(self, os_family: OSFamily) -> tuple[InstallMethod, ...]:
        return self.install.get(os_family.value, ())


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    tools: tuple[str, ...] = ()
    extends: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    display_name: str
    supported: bool
    status: str
    architectures: tuple[str, ...]
    package_managers: tuple[str, ...]
    notes: str = ""


# --------------------------------------------------------------------------- runtime


@dataclass(frozen=True)
class SystemInfo:
    os_family: OSFamily
    os_name: str
    os_version: str
    architecture: str
    machine: str
    python_version: str
    python_executable: str
    distro_id: str = ""
    distro_like: tuple[str, ...] = ()
    is_wsl: bool = False
    is_admin: bool = False
    path_entries: tuple[str, ...] = ()
    package_managers: dict[str, str] = field(default_factory=dict)

    @property
    def python_tuple(self) -> tuple[int, ...]:
        return tuple(int(p) for p in self.python_version.split(".")[:3] if p.isdigit())


@dataclass(frozen=True)
class PathIssue:
    entry: str
    problem: str


@dataclass(frozen=True)
class HostRequirementResult:
    requirement: HostRequirement
    found: str | None

    @property
    def satisfied(self) -> bool:
        return self.found is not None


@dataclass
class ToolReport:
    spec: ToolSpec
    status: ToolStatus
    version: Version | None = None
    executable: Path | None = None
    on_path: bool | None = None
    message: str = ""
    recommendation: str = ""
    warnings: list[str] = field(default_factory=list)
    variant: str | None = None
    raw_output: str = ""
    host_requirements: list[HostRequirementResult] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def compatibility(self) -> CheckLevel:
        if self.status is ToolStatus.INSTALLED:
            return CheckLevel.WARN if self.warnings else CheckLevel.PASS
        if self.status in (ToolStatus.MISSING, ToolStatus.UNKNOWN):
            return CheckLevel.INFO
        return CheckLevel.FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.spec.name,
            "display_name": self.spec.display_name,
            "required": self.spec.required,
            "status": self.status.value,
            "version": str(self.version) if self.version else None,
            "minimum_version": self.spec.minimum_version,
            "executable": str(self.executable) if self.executable else None,
            "on_path": self.on_path,
            "compatibility": self.compatibility.value,
            "variant": self.variant,
            "message": self.message,
            "recommendation": self.recommendation,
            "warnings": list(self.warnings),
            "host_requirements": {r.requirement.name: r.found for r in self.host_requirements},
        }


@dataclass(frozen=True)
class DoctorCheck:
    level: CheckLevel
    title: str
    detail: str = ""


@dataclass
class DoctorReport:
    checks: list[DoctorCheck]

    @property
    def failures(self) -> int:
        return sum(1 for c in self.checks if c.level is CheckLevel.FAIL)

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.level is CheckLevel.WARN)

    @property
    def overall(self) -> str:
        if self.failures:
            return "NEEDS ATTENTION"
        if self.warnings:
            return "OK WITH WARNINGS"
        return "HEALTHY"


@dataclass(frozen=True)
class PlanStep:
    kind: StepKind
    description: str
    command: tuple[str, ...] | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class InstallPlan:
    tool: ToolSpec
    action: str  # install | update | uninstall | skip
    method: InstallMethod | None
    current_version: str | None
    target_version: str | None
    steps: list[PlanStep] = field(default_factory=list)
    requires_admin: bool = False
    notes: list[str] = field(default_factory=list)
    blocked_reason: str | None = None

    @property
    def executable(self) -> bool:
        return self.action != "skip" and self.blocked_reason is None and bool(self.steps)


@dataclass
class InstallResult:
    tool: str
    success: bool
    message: str
    report: ToolReport | None = None


@dataclass(frozen=True)
class UpdateInfo:
    tool: str
    display_name: str
    state: UpdateState
    current: str | None
    latest: str | None
    source: str
    message: str = ""

"""Exception hierarchy. Every error raised deliberately by ToolHub derives from ToolHubError."""

from __future__ import annotations


class ToolHubError(Exception):
    """Base class for all ToolHub errors."""

    exit_code = 1


class RegistryError(ToolHubError):
    """The tool registry is malformed or inconsistent."""


class ConfigError(ToolHubError):
    """The user configuration is invalid."""


class UnknownToolError(ToolHubError):
    """A tool name is not present in the registry."""


class UnknownProfileError(ToolHubError):
    """A profile name is not present in the registry."""


class DependencyCycleError(ToolHubError):
    """Tool dependencies or profile inheritance form a cycle."""


class UnsupportedPlatformError(ToolHubError):
    """The operation is not supported on the detected platform."""


class NoInstallMethodError(ToolHubError):
    """No usable installation method exists for a tool on this system."""


class ManualInstallRequired(ToolHubError):
    """The tool can only be installed manually on this platform."""


class InstallationError(ToolHubError):
    """An installation step failed."""


class VerificationError(InstallationError):
    """Installation finished but the tool did not verify as working."""


class CommandExecutionError(ToolHubError):
    """A subprocess could not be started (not found, permission denied, ...)."""


class PrivilegeError(ToolHubError):
    """The selected method needs privileges that are not available."""


class SecurityError(ToolHubError):
    """A security policy was violated."""


class UntrustedSourceError(SecurityError):
    """A URL is not HTTPS or its host is not on the allowlist."""


class ChecksumMismatchError(SecurityError):
    """A downloaded file does not match its expected SHA256."""


class DownloadTooLargeError(SecurityError):
    """A download exceeded the configured size limit."""


class UnsafeArchiveError(SecurityError):
    """An archive contains unsafe members (traversal, links, devices, bombs)."""


class DownloadError(ToolHubError):
    """A network download failed."""

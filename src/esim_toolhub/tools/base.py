"""Per-tool behaviour hooks. Most tools need none and use GenericToolAdapter."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from esim_toolhub.core.models import OSFamily, ToolSpec, ToolStatus
from esim_toolhub.detection.version import Version, extract_version


class GenericToolAdapter:
    """Default behaviour driven entirely by tools.yaml."""

    def __init__(
        self, spec: ToolSpec, file_exists: Callable[[Path], bool] = os.path.isfile
    ) -> None:
        self.spec = spec
        self.file_exists = file_exists

    def fallback_executables(self, os_family: OSFamily) -> tuple[str, ...]:
        """Names to try only when none of the primary executables are found."""
        return ()

    def can_probe(self, executable: Path) -> bool:
        """False for GUI binaries that must not be launched with --version."""
        return True

    def version_command(self, executable: Path, os_family: OSFamily) -> list[str]:
        return [str(executable), *self.spec.version_args]

    def parse_version(self, output: str) -> Version | None:
        return extract_version(output, self.spec.version_pattern)

    def fallback_version(self, executable: Path) -> Version | None:
        return None

    def detect_variant(self, output: str) -> str | None:
        rule = self.spec.variant
        if not rule or not output:
            return None
        match = re.search(rule.pattern, output, re.IGNORECASE)
        return match.group(1).lower() if match else None

    def on_timeout(self, executable: Path, os_family: OSFamily) -> tuple[ToolStatus, str]:
        return (
            ToolStatus.BROKEN,
            f"'{executable.name} {' '.join(self.spec.version_args)}' did not exit within "
            f"{self.spec.version_timeout:.0f}s",
        )

"""macOS installer adapter (experimental Homebrew & archive strategy).

eSim does not officially support macOS, and this adapter has not been validated
on macOS hardware. It exists so macOS support can be completed without changing
the core manager.
"""

from __future__ import annotations

from esim_toolhub.core.models import MethodType, OSFamily
from esim_toolhub.installers.base import Installer


class MacOSInstaller(Installer):
    os_family = OSFamily.MACOS

    def allowed_methods(self) -> tuple[MethodType, ...]:
        return (MethodType.BREW, MethodType.ARCHIVE, MethodType.MANUAL)

    def platform_notes(self) -> list[str]:
        return [
            "macOS support is experimental and has not been validated on macOS hardware; "
            "eSim itself officially targets Ubuntu and Windows."
        ]

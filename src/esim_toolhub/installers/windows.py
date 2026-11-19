"""Windows installer adapter (winget, Chocolatey, verified archive, manual)."""

from __future__ import annotations

from esim_toolhub.core.models import InstallMethod, MethodType, OSFamily
from esim_toolhub.installers.base import Installer


class WindowsInstaller(Installer):
    os_family = OSFamily.WINDOWS

    def allowed_methods(self) -> tuple[MethodType, ...]:
        return (
            MethodType.WINGET,
            MethodType.CHOCO,
            MethodType.ARCHIVE,
            MethodType.MANUAL,
        )

    def privilege_blocker(self, method: InstallMethod) -> str | None:
        if method.requires_admin and not self.system.is_admin:
            return (
                f"'{method.label()}' requires an elevated (Administrator) terminal on Windows. "
                f"Re-run from an Administrator prompt or choose a user-level install method."
            )
        return None

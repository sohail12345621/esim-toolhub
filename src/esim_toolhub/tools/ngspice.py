"""Ngspice quirks.

On Windows the official build ships two binaries: ``ngspice.exe`` (GUI window) and
``ngspice_con.exe`` (console). Querying the GUI build with ``--version`` opens a
window and blocks, so the console sibling is preferred and a timeout of the GUI
build is reported as UNKNOWN rather than BROKEN.
"""

from __future__ import annotations

from pathlib import Path

from esim_toolhub.core.models import OSFamily, ToolStatus
from esim_toolhub.tools.base import GenericToolAdapter


class NgspiceAdapter(GenericToolAdapter):
    def version_command(self, executable: Path, os_family: OSFamily) -> list[str]:
        if os_family is OSFamily.WINDOWS and executable.name.lower() == "ngspice.exe":
            console = executable.with_name("ngspice_con.exe")
            if self.file_exists(console):
                return [str(console), *self.spec.version_args]
        return super().version_command(executable, os_family)

    def on_timeout(self, executable: Path, os_family: OSFamily) -> tuple[ToolStatus, str]:
        if os_family is OSFamily.WINDOWS and executable.name.lower() == "ngspice.exe":
            return (
                ToolStatus.UNKNOWN,
                "GUI build of ngspice does not report its version non-interactively; "
                "install the console build (ngspice_con.exe) for verification",
            )
        return super().on_timeout(executable, os_family)

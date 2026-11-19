"""KiCad quirks.

* ``kicad-cli`` only exists since KiCad 7. Older installs only have the GUI
  ``kicad`` binary, which must never be launched just to read a version.
* On Windows the install directory encodes the version (``KiCad\\9.0\\bin``),
  which is a usable fallback when ``kicad-cli --version`` misbehaves.
"""

from __future__ import annotations

import re
from pathlib import Path

from esim_toolhub.core.models import OSFamily
from esim_toolhub.detection.version import Version, parse_version
from esim_toolhub.tools.base import GenericToolAdapter

_PATH_VERSION = re.compile(r"kicad[\\/](\d+(?:\.\d+)?)[\\/]", re.IGNORECASE)
_GUI_NAMES = {"kicad", "kicad.exe"}


class KiCadAdapter(GenericToolAdapter):
    def fallback_executables(self, os_family: OSFamily) -> tuple[str, ...]:
        return ("kicad.exe",) if os_family is OSFamily.WINDOWS else ("kicad",)

    def can_probe(self, executable: Path) -> bool:
        return executable.name.lower() not in _GUI_NAMES

    def fallback_version(self, executable: Path) -> Version | None:
        match = _PATH_VERSION.search(str(executable))
        return parse_version(match.group(1)) if match else None

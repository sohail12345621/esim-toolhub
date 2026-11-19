"""Executable discovery: PATH first, then ToolHub-managed dirs, then registry search paths."""

from __future__ import annotations

import glob as _glob
import os
import re
import shutil
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from esim_toolhub.core.models import OSFamily, SystemInfo, ToolSpec

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_()]*)\}")
_NUM = re.compile(r"(\d+)")


@dataclass(frozen=True)
class LocatedExecutable:
    path: Path
    on_path: bool
    source: str  # "PATH" | "managed" | "search-path"


def natural_key(text: str) -> list[object]:
    """Sort key so 'KiCad/10.0' > 'KiCad/9.0' > 'KiCad/8.0'."""
    return [int(tok) if tok.isdigit() else tok.lower() for tok in _NUM.split(text)]


def expand_pattern(
    pattern: str,
    env: Mapping[str, str],
    home: Path,
    glob_fn: Callable[[str], list[str]] = _glob.glob,
) -> list[str]:
    """Expand ``${VAR}``, ``~`` and globs. Patterns with undefined variables yield nothing."""
    missing = False

    def sub(match: re.Match[str]) -> str:
        nonlocal missing
        value = env.get(match.group(1))
        if value is None:
            missing = True
            return ""
        return value

    expanded = _VAR.sub(sub, pattern)
    if missing:
        return []
    if expanded.startswith("~"):
        expanded = str(home) + expanded[1:]
    if any(ch in expanded for ch in "*?["):
        return sorted(glob_fn(expanded), key=natural_key, reverse=True)
    return [expanded]


class ExecutableLocator:
    def __init__(
        self,
        system: SystemInfo,
        env: Mapping[str, str] | None = None,
        which: Callable[[str], str | None] = shutil.which,
        managed_dirs: Callable[[str], Sequence[Path]] = lambda _tool: (),
        glob_fn: Callable[[str], list[str]] = _glob.glob,
        is_executable: Callable[[Path], bool] | None = None,
        home: Path | None = None,
    ) -> None:
        self.system = system
        self.env = os.environ if env is None else env
        self.which = which
        self.managed_dirs = managed_dirs
        self.glob_fn = glob_fn
        self.home = home or Path.home()
        self.is_executable = is_executable or self._default_is_executable

    def _default_is_executable(self, path: Path) -> bool:
        if not path.is_file():
            return False
        return self.system.os_family is OSFamily.WINDOWS or os.access(path, os.X_OK)

    def _norm(self, value: str) -> str:
        value = value.rstrip("\\/")
        if self.system.os_family is OSFamily.WINDOWS:
            return os.path.normcase(value.replace("/", "\\")).lower()
        return value

    def dir_on_path(self, directory: Path) -> bool:
        target = self._norm(str(directory))
        return any(self._norm(entry) == target for entry in self.system.path_entries)

    def search_dirs(self, spec: ToolSpec) -> list[str]:
        dirs: list[str] = []
        for pattern in spec.search_paths.get(self.system.os_family.value, ()):
            dirs.extend(expand_pattern(pattern, self.env, self.home, self.glob_fn))
        return dirs

    def locate_names(self, names: Iterable[str], spec: ToolSpec) -> LocatedExecutable | None:
        names = list(names)
        for name in names:
            found = self.which(name)
            if found:
                return LocatedExecutable(Path(found), True, "PATH")
        for directory in self.managed_dirs(spec.name):
            for name in names:
                candidate = Path(directory) / name
                if self.is_executable(candidate):
                    return LocatedExecutable(
                        candidate, self.dir_on_path(candidate.parent), "managed"
                    )
        for search_dir in self.search_dirs(spec):
            for name in names:
                candidate = Path(search_dir) / name
                if self.is_executable(candidate):
                    return LocatedExecutable(
                        candidate, self.dir_on_path(candidate.parent), "search-path"
                    )
        return None

    def locate(self, spec: ToolSpec) -> LocatedExecutable | None:
        return self.locate_names(spec.executables_for(self.system.os_family), spec)

    def find_any(self, names: Iterable[str]) -> str | None:
        """PATH-only lookup used for host prerequisites (compilers, make)."""
        for name in names:
            found = self.which(name)
            if found:
                return found
        return None

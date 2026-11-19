"""Managed tool directory tracking and PATH configuration guidance.

ToolHub never silently edits Windows registry keys or user shell startup files.
Instead it tracks archive-installed tool bin directories in ``environment.json``
(searched automatically by ExecutableLocator) and generates exact shell snippets
so users can add missing directories to PATH deliberately.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from esim_toolhub.core.models import OSFamily, SystemInfo

log = logging.getLogger(__name__)


class EnvironmentManager:
    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file

    def load(self) -> dict[str, str]:
        if not self.state_file.exists():
            return {}
        try:
            data = json.loads(self.state_file.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Ignoring unreadable environment state: %s", exc)
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}

    def _save(self, mapping: dict[str, str]) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(mapping, indent=2, sort_keys=True) + "\n"
        fd, tmp = tempfile.mkstemp(dir=self.state_file.parent, prefix=".env-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.state_file)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def register(self, tool: str, bin_dir: Path) -> None:
        mapping = self.load()
        mapping[tool] = str(bin_dir.resolve())
        self._save(mapping)
        log.info(
            "Registered managed tool path",
            extra={"event": "env_register", "tool": tool, "path": mapping[tool]},
        )

    def unregister(self, tool: str) -> bool:
        mapping = self.load()
        if tool not in mapping:
            return False
        removed = mapping.pop(tool)
        self._save(mapping)
        log.info(
            "Unregistered managed tool path",
            extra={"event": "env_unregister", "tool": tool, "path": removed},
        )
        return True

    def managed_dirs(self, tool: str) -> list[Path]:
        entry = self.load().get(tool)
        return [Path(entry)] if entry else []

    def all_dirs(self) -> dict[str, Path]:
        return {k: Path(v) for k, v in self.load().items()}

    def missing_from_path(
        self, system: SystemInfo, extra_dirs: list[Path] | None = None
    ) -> list[Path]:
        """Return managed (and optional extra) directories not currently present on PATH."""
        candidates = list(self.all_dirs().values())
        if extra_dirs:
            candidates.extend(extra_dirs)

        def norm(p: str) -> str:
            p = p.rstrip("\\/")
            if system.os_family is OSFamily.WINDOWS:
                return os.path.normcase(p.replace("/", "\\")).lower()
            return p

        on_path = {norm(e) for e in system.path_entries}
        missing: list[Path] = []
        seen: set[str] = set()
        for directory in candidates:
            key = norm(str(directory))
            if key not in on_path and key not in seen:
                seen.add(key)
                missing.append(directory)
        return missing

    @staticmethod
    def shell_snippet(dirs: list[Path], os_family: OSFamily) -> str:
        """Produce copy-pasteable commands to add ``dirs`` to PATH without mutating host config."""
        if not dirs:
            return ""
        if os_family is OSFamily.WINDOWS:
            joined = ";".join(str(d) for d in dirs)
            return (
                "# Current PowerShell session:\n"
                f'$env:PATH = "{joined};$env:PATH"\n'
                "# Persist for current user (PowerShell):\n"
                f'[Environment]::SetEnvironmentVariable("Path", '
                f'"{joined};" + [Environment]::GetEnvironmentVariable("Path", "User"), "User")'
            )
        joined = ":".join(str(d) for d in dirs)
        return (
            "# Current shell session:\n"
            f'export PATH="{joined}:$PATH"\n'
            "# Add the line above to ~/.bashrc or ~/.zshrc to persist."
        )

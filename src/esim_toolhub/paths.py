"""OS-appropriate locations for config, data, logs and cache (via platformdirs)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs

APP_NAME = "esim-toolhub"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    log_dir: Path
    cache_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.yaml"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "toolhub.log"

    @property
    def tools_dir(self) -> Path:
        """Where archive-installed tools are extracted (user-writable, no admin)."""
        return self.data_dir / "tools"

    @property
    def environment_file(self) -> Path:
        return self.data_dir / "environment.json"

    @classmethod
    def default(cls) -> AppPaths:
        override = os.environ.get("ESIM_TOOLHUB_HOME")
        if override:
            root = Path(override)
            return cls(root / "config", root / "data", root / "logs", root / "cache")
        return cls(
            config_dir=platformdirs.user_config_path(APP_NAME, appauthor=False),
            data_dir=platformdirs.user_data_path(APP_NAME, appauthor=False),
            log_dir=platformdirs.user_log_path(APP_NAME, appauthor=False),
            cache_dir=platformdirs.user_cache_path(APP_NAME, appauthor=False),
        )

    @classmethod
    def under(cls, root: Path) -> AppPaths:
        return cls(root / "config", root / "data", root / "logs", root / "cache")

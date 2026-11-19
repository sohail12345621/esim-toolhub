"""User configuration stored as YAML in the OS-appropriate config directory."""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from esim_toolhub.core.exceptions import ConfigError
from esim_toolhub.core.models import MethodType

log = logging.getLogger(__name__)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


@dataclass
class ToolHubConfig:
    preferred_install_method: str | None = None
    auto_update: bool = False
    verify_checksums: bool = True
    install_optional_tools: bool = False
    log_level: str = "INFO"
    download_max_mb: int = 1024
    install_timeout_s: int = 3600
    online_update_check: bool = False

    def validate(self) -> None:
        if self.preferred_install_method is not None:
            valid = {m.value for m in MethodType}
            if self.preferred_install_method not in valid:
                raise ConfigError(
                    f"preferred_install_method must be one of {sorted(valid)} or null"
                )
        if self.log_level.upper() not in LOG_LEVELS:
            raise ConfigError(f"log_level must be one of {LOG_LEVELS}")
        self.log_level = self.log_level.upper()
        if not 1 <= self.download_max_mb <= 16384:
            raise ConfigError("download_max_mb must be between 1 and 16384")
        if not 60 <= self.install_timeout_s <= 6 * 3600:
            raise ConfigError("install_timeout_s must be between 60 and 21600")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FIELD_TYPES = {f.name: f.type for f in fields(ToolHubConfig)}


def _coerce(key: str, raw: Any) -> Any:
    kind = str(_FIELD_TYPES[key])
    if raw is None or (isinstance(raw, str) and raw.strip().lower() in ("null", "none", "")):
        if "None" in kind:
            return None
        raise ConfigError(f"{key} cannot be null")
    if "bool" in kind:
        if isinstance(raw, bool):
            return raw
        value = str(raw).strip().lower()
        if value in ("1", "true", "yes", "on"):
            return True
        if value in ("0", "false", "no", "off"):
            return False
        raise ConfigError(f"{key} expects true/false, got {raw!r}")
    if "int" in kind:
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{key} expects an integer, got {raw!r}") from exc
    return str(raw)


class ConfigManager:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> ToolHubConfig:
        if not self.path.exists():
            return ToolHubConfig()
        try:
            data = yaml.safe_load(self.path.read_text("utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigError(f"Cannot read config {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"Config {self.path} must be a mapping")
        values: dict[str, Any] = {}
        for key, raw in data.items():
            if key not in _FIELD_TYPES:
                log.warning("Ignoring unknown config key", extra={"key": str(key)})
                continue
            values[key] = _coerce(key, raw)
        config = ToolHubConfig(**values)
        config.validate()
        return config

    def save(self, config: ToolHubConfig) -> None:
        config.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        text = "# eSim ToolHub configuration\n" + yaml.safe_dump(config.to_dict(), sort_keys=False)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".config-", suffix=".yaml")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def validate_change(self, key: str, raw: str) -> Any:
        """Validate a proposed key/value change without persisting it."""
        if key not in _FIELD_TYPES:
            raise ConfigError(f"Unknown config key '{key}'. Valid keys: {', '.join(_FIELD_TYPES)}")
        coerced = _coerce(key, raw)
        candidate = self.load()
        setattr(candidate, key, coerced)
        candidate.validate()
        return coerced

    def set(self, key: str, raw: str) -> ToolHubConfig:
        coerced = self.validate_change(key, raw)
        config = self.load()
        setattr(config, key, coerced)
        self.save(config)
        log.info("Config updated", extra={"event": "config_set", "key": key})
        return config

    def reset(self) -> ToolHubConfig:
        config = ToolHubConfig()
        self.save(config)
        return config

    @staticmethod
    def keys() -> list[str]:
        return list(_FIELD_TYPES)

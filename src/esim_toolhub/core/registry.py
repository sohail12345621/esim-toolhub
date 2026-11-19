"""Declarative tool registry loaded from tools.yaml and platforms.yaml."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from esim_toolhub.core.exceptions import (
    RegistryError,
    SecurityError,
    UnknownProfileError,
    UnknownToolError,
)
from esim_toolhub.core.models import (
    HostRequirement,
    InstallMethod,
    MethodType,
    PlatformSpec,
    Profile,
    ToolSpec,
    VariantRule,
)
from esim_toolhub.detection.version import parse_version
from esim_toolhub.security.checksum import is_valid_sha256
from esim_toolhub.security.validation import validate_package_id, validate_tool_name, validate_url

KNOWN_OS = ("windows", "linux", "macos")


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _per_os(value: Any, where: str) -> dict[str, tuple[str, ...]]:
    if not value:
        return {}
    if not isinstance(value, Mapping):
        raise RegistryError(f"{where}: expected a mapping of OS -> list")
    out: dict[str, tuple[str, ...]] = {}
    for os_name, items in value.items():
        if os_name not in KNOWN_OS:
            raise RegistryError(f"{where}: unknown OS '{os_name}'")
        out[os_name] = _tuple(items)
    return out


class Registry:
    """Immutable view over tools, profiles, platforms and the download allowlist."""

    def __init__(
        self,
        tools: Mapping[str, ToolSpec],
        profiles: Mapping[str, Profile],
        platforms: Mapping[str, PlatformSpec],
        trusted_hosts: Iterable[str],
        python_minimum: str = "3.10",
        updated: str = "",
    ) -> None:
        self._tools = dict(tools)
        self._profiles = dict(profiles)
        self.platforms = dict(platforms)
        self.trusted_hosts = tuple(trusted_hosts)
        self.python_minimum = python_minimum
        self.updated = updated
        self._validate_references()

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, tools_path: Path | None = None, platforms_path: Path | None = None) -> Registry:
        tools_doc = _read_yaml(tools_path, "tools.yaml")
        platforms_doc = _read_yaml(platforms_path, "platforms.yaml")
        return cls.from_documents(tools_doc, platforms_doc)

    @classmethod
    def from_documents(
        cls, tools_doc: Mapping[str, Any], platforms_doc: Mapping[str, Any]
    ) -> Registry:
        trusted = _tuple(platforms_doc.get("trusted_hosts"))
        tools_section = tools_doc.get("tools") or {}
        if not isinstance(tools_section, Mapping) or not tools_section:
            raise RegistryError("tools.yaml must define at least one tool under 'tools'")
        tools = {name: _parse_tool(name, data, trusted) for name, data in tools_section.items()}
        profiles = {
            name: Profile(
                name=name,
                description=str((data or {}).get("description", "")),
                tools=_tuple((data or {}).get("tools")),
                extends=_tuple((data or {}).get("extends")),
            )
            for name, data in (tools_doc.get("profiles") or {}).items()
        }
        platforms = {
            name: PlatformSpec(
                name=name,
                display_name=str(data.get("display_name", name)),
                supported=bool(data.get("supported", False)),
                status=str(data.get("status", "unsupported")),
                architectures=_tuple(data.get("architectures")),
                package_managers=_tuple(data.get("package_managers")),
                notes=str(data.get("notes", "")),
            )
            for name, data in (platforms_doc.get("platforms") or {}).items()
        }
        python_min = str((platforms_doc.get("python") or {}).get("minimum", "3.10"))
        return cls(
            tools, profiles, platforms, trusted, python_min, str(tools_doc.get("updated", ""))
        )

    def _validate_references(self) -> None:
        for spec in self._tools.values():
            for dep in spec.depends_on:
                if dep not in self._tools:
                    raise RegistryError(f"Tool '{spec.name}' depends on unknown tool '{dep}'")
        for profile in self._profiles.values():
            for tool in profile.tools:
                if tool not in self._tools:
                    raise RegistryError(
                        f"Profile '{profile.name}' references unknown tool '{tool}'"
                    )
            for parent in profile.extends:
                if parent not in self._profiles:
                    raise RegistryError(
                        f"Profile '{profile.name}' extends unknown profile '{parent}'"
                    )

    # ------------------------------------------------------------------ queries
    def tool(self, name: str) -> ToolSpec:
        key = name.strip().lower()
        if key not in self._tools:
            known = ", ".join(sorted(self._tools))
            raise UnknownToolError(f"Unknown tool '{name}'. Known tools: {known}")
        return self._tools[key]

    def tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def tool_names(self) -> list[str]:
        return list(self._tools)

    def profile(self, name: str) -> Profile:
        key = name.strip().lower()
        if key not in self._profiles:
            known = ", ".join(self._profiles)
            raise UnknownProfileError(f"Unknown profile '{name}'. Known profiles: {known}")
        return self._profiles[key]

    def profiles(self) -> list[Profile]:
        return list(self._profiles.values())

    def platform(self, os_name: str) -> PlatformSpec | None:
        return self.platforms.get(os_name)


def _read_yaml(path: Path | None, default_name: str) -> Mapping[str, Any]:
    try:
        if path is None:
            text = (
                resources.files("esim_toolhub.resources").joinpath(default_name).read_text("utf-8")
            )
        else:
            text = Path(path).read_text("utf-8")
        data = yaml.safe_load(text) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"Cannot read {path or default_name}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise RegistryError(f"{path or default_name} must contain a mapping")
    return data


def _check_version(value: Any, where: str) -> str | None:
    if value is None:
        return None
    text = str(value)
    if parse_version(text) is None:
        raise RegistryError(f"{where}: '{text}' is not a version")
    return text


def _parse_method(raw: Mapping[str, Any], where: str, trusted: tuple[str, ...]) -> InstallMethod:
    try:
        mtype = MethodType(str(raw.get("type")))
    except ValueError as exc:
        raise RegistryError(f"{where}: unknown install method type {raw.get('type')!r}") from exc
    package = raw.get("package")
    url = raw.get("url")
    sha = raw.get("sha256")
    try:
        if mtype.is_package_manager:
            if not package:
                raise RegistryError(f"{where}: '{mtype.value}' method requires 'package'")
            validate_package_id(str(package))
        if mtype is MethodType.ARCHIVE:
            if not url:
                raise RegistryError(f"{where}: archive method requires 'url'")
            validate_url(str(url), trusted)
            if sha is not None and not is_valid_sha256(str(sha)):
                raise RegistryError(f"{where}: invalid sha256")
    except SecurityError as exc:
        raise RegistryError(f"{where}: {exc}") from exc
    if mtype is MethodType.MANUAL and not raw.get("instructions"):
        raise RegistryError(f"{where}: manual method requires 'instructions'")
    return InstallMethod(
        type=mtype,
        package=str(package) if package else None,
        url=str(url) if url else None,
        sha256=str(sha).lower() if sha else None,
        size=int(raw["size"]) if raw.get("size") else None,
        version=_check_version(raw.get("version"), where),
        requires_admin=bool(raw.get("requires_admin", False)),
        cask=bool(raw.get("cask", False)),
        architectures=_tuple(raw.get("architectures")),
        distros=_tuple(raw.get("distros")),
        instructions=_tuple(raw.get("instructions")),
        notes=" ".join(str(raw.get("notes", "")).split()),
    )


def _parse_tool(name: str, data: Mapping[str, Any], trusted: tuple[str, ...]) -> ToolSpec:
    try:
        validate_tool_name(name)
    except SecurityError as exc:
        raise RegistryError(str(exc)) from exc
    if not isinstance(data, Mapping):
        raise RegistryError(f"Tool '{name}' must be a mapping")
    where = f"tools.{name}"
    for key in ("display_name", "executables"):
        if key not in data:
            raise RegistryError(f"{where}: missing required key '{key}'")

    pattern = data.get("version_pattern")
    if pattern:
        try:
            if re.compile(pattern).groups != 1:
                raise RegistryError(f"{where}: version_pattern must have exactly one group")
        except re.error as exc:
            raise RegistryError(f"{where}: invalid version_pattern: {exc}") from exc

    install: dict[str, tuple[InstallMethod, ...]] = {}
    for os_name, methods in (data.get("install") or {}).items():
        if os_name not in KNOWN_OS:
            raise RegistryError(f"{where}.install: unknown OS '{os_name}'")
        install[os_name] = tuple(
            _parse_method(m, f"{where}.install.{os_name}[{i}]", trusted)
            for i, m in enumerate(methods or [])
        )

    variant = None
    if data.get("variant"):
        v = data["variant"]
        variant = VariantRule(
            pattern=str(v["pattern"]),
            label=str(v.get("label", "variant")),
            unsupported=tuple(s.lower() for s in _tuple(v.get("unsupported"))),
            reason=" ".join(str(v.get("reason", "")).split()),
        )

    host_reqs = tuple(
        HostRequirement(
            name=str(r["name"]),
            executables=_tuple(r.get("executables")),
            platforms=_tuple(r.get("platforms")),
            reason=str(r.get("reason", "")),
        )
        for r in data.get("host_requirements") or []
    )

    return ToolSpec(
        name=name,
        display_name=str(data["display_name"]),
        description=str(data.get("description", "")),
        category=str(data.get("category", "general")),
        required=bool(data.get("required", False)),
        executables=_per_os(data.get("executables"), f"{where}.executables"),
        version_args=_tuple(data.get("version_args")) or ("--version",),
        version_pattern=pattern,
        version_timeout=float(data.get("version_timeout", 15)),
        minimum_version=_check_version(data.get("minimum_version"), f"{where}.minimum_version"),
        tested_up_to=_check_version(data.get("tested_up_to"), f"{where}.tested_up_to"),
        maximum_version=_check_version(data.get("maximum_version"), f"{where}.maximum_version"),
        latest_known_version=_check_version(
            data.get("latest_known_version"), f"{where}.latest_known_version"
        ),
        search_paths=_per_os(data.get("search_paths"), f"{where}.search_paths"),
        install=install,
        architectures=_per_os(data.get("architectures"), f"{where}.architectures"),
        depends_on=_tuple(data.get("depends_on")),
        host_requirements=host_reqs,
        variant=variant,
        adapter=data.get("adapter"),
        homepage=str(data.get("homepage", "")),
        esim_role=str(data.get("esim_role", "")),
    )

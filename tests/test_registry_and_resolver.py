"""Tests for the declarative registry, validation rules and dependency resolver."""

from __future__ import annotations

import pytest

from esim_toolhub.core.exceptions import (
    DependencyCycleError,
    RegistryError,
    UnknownProfileError,
    UnknownToolError,
)
from esim_toolhub.core.registry import Registry
from esim_toolhub.dependency.resolver import DependencyResolver


def test_bundled_registry_loads_core_tools_and_profiles(registry: Registry) -> None:
    names = set(registry.tool_names())
    assert {"ngspice", "kicad", "ghdl", "verilator", "openmodelica"}.issubset(names)
    assert registry.tool("ngspice").required is True
    assert registry.tool("kicad").required is True
    assert registry.tool("ghdl").required is False
    assert {p.name for p in registry.profiles()} == {"minimal", "analog", "digital", "full"}


def test_unknown_tool_and_profile_raise_clean_errors(registry: Registry) -> None:
    with pytest.raises(UnknownToolError):
        registry.tool("nonexistent")
    with pytest.raises(UnknownProfileError):
        registry.profile("nonexistent")


def test_malformed_registry_rejects_unsafe_package_and_untrusted_url() -> None:
    platforms = {"trusted_hosts": ["github.com"], "platforms": {}}
    bad_pkg = {
        "tools": {
            "ngspice": {
                "display_name": "Ngspice",
                "executables": {"linux": ["ngspice"]},
                "install": {"linux": [{"type": "apt", "package": "--evil-flag"}]},
            }
        }
    }
    with pytest.raises(RegistryError, match="unsafe package identifier"):
        Registry.from_documents(bad_pkg, platforms)

    bad_url = {
        "tools": {
            "ngspice": {
                "display_name": "Ngspice",
                "executables": {"linux": ["ngspice"]},
                "install": {
                    "linux": [{"type": "archive", "url": "https://evil.example.com/ngspice.tar.gz"}]
                },
            }
        }
    }
    with pytest.raises(RegistryError, match="trusted download allowlist"):
        Registry.from_documents(bad_url, platforms)

    bad_sha = {
        "tools": {
            "ngspice": {
                "display_name": "Ngspice",
                "executables": {"linux": ["ngspice"]},
                "install": {
                    "linux": [
                        {
                            "type": "archive",
                            "url": "https://github.com/org/repo/releases/download/v1/a.tar.gz",
                            "sha256": "not-a-sha256",
                        }
                    ]
                },
            }
        }
    }
    with pytest.raises(RegistryError, match="invalid sha256"):
        Registry.from_documents(bad_sha, platforms)


def test_resolver_expands_profiles_and_orders_dependencies(registry: Registry) -> None:
    resolver = DependencyResolver(registry)
    assert resolver.expand_profile("minimal") == ["ngspice"]
    assert resolver.expand_profile("analog") == ["ngspice", "kicad"]
    assert resolver.expand_profile("digital") == ["ngspice", "kicad", "ghdl", "verilator"]
    assert resolver.expand_profile("full") == [
        "ngspice",
        "kicad",
        "ghdl",
        "verilator",
        "openmodelica",
    ]
    # Requesting ghdl alone automatically pulls ngspice first.
    assert resolver.resolve(["ghdl"]) == ["ngspice", "ghdl"]


def test_resolver_detects_tool_and_profile_cycles() -> None:
    platforms = {"trusted_hosts": [], "platforms": {}}
    doc = {
        "tools": {
            "a": {"display_name": "A", "executables": {"linux": ["a"]}, "depends_on": ["b"]},
            "b": {"display_name": "B", "executables": {"linux": ["b"]}, "depends_on": ["a"]},
        },
        "profiles": {
            "p1": {"extends": ["p2"], "tools": ["a"]},
            "p2": {"extends": ["p1"], "tools": ["b"]},
        },
    }
    reg = Registry.from_documents(doc, platforms)
    resolver = DependencyResolver(reg)
    with pytest.raises(DependencyCycleError, match="Dependency cycle"):
        resolver.resolve(["a"])
    with pytest.raises(DependencyCycleError, match="Profile inheritance cycle"):
        resolver.expand_profile("p1")


def test_extensibility_adding_new_tool_requires_only_registry_metadata(tmp_path) -> None:
    """Adding a brand-new tool purely in YAML works across detection, install plan & updates."""
    from esim_toolhub.core.manager import ToolHub
    from esim_toolhub.core.models import OSFamily, ToolStatus, UpdateState
    from esim_toolhub.core.runner import CommandResult
    from esim_toolhub.detection.executable import ExecutableLocator
    from esim_toolhub.paths import AppPaths
    from tests.conftest import FakeDownloader, FakeRunner, make_system

    custom_tools = {
        "tools": {
            "iverilog": {
                "display_name": "Icarus Verilog",
                "description": "Verilog simulator used alongside NGHDL",
                "category": "digital",
                "required": False,
                "executables": {"linux": ["iverilog"]},
                "version_args": ["-V"],
                "version_pattern": r"Icarus Verilog version (\d+\.\d+)",
                "minimum_version": "11.0",
                "latest_known_version": "12.0",
                "install": {"linux": [{"type": "apt", "package": "iverilog"}]},
            }
        },
        "profiles": {"verilog": {"description": "Verilog only", "tools": ["iverilog"]}},
    }
    platforms = {
        "python": {"minimum": "3.10"},
        "trusted_hosts": [],
        "platforms": {
            "linux": {
                "display_name": "Linux",
                "supported": True,
                "status": "supported",
                "architectures": ["x86_64"],
                "package_managers": ["apt"],
            }
        },
    }
    reg = Registry.from_documents(custom_tools, platforms)
    sys_info = make_system(OSFamily.LINUX)
    runner = FakeRunner(
        lambda argv: CommandResult(argv, 0, "Icarus Verilog version 11.0 (stable)\n")
    )
    locator = ExecutableLocator(
        sys_info, which=lambda n: "/usr/bin/iverilog" if n == "iverilog" else None
    )
    hub = ToolHub(
        registry=reg,
        paths=AppPaths.under(tmp_path),
        system=sys_info,
        runner=runner,
        downloader=FakeDownloader(),
        locator=locator,
    )

    reports = hub.check("iverilog")
    assert reports[0].status is ToolStatus.INSTALLED
    assert str(reports[0].version) == "11.0"

    updates = hub.check_updates(["iverilog"])
    assert updates[0].state is UpdateState.UPDATE_AVAILABLE

    plans = hub.install(profile="verilog", dry_run=True, force=True)
    assert plans[0][0].method is not None
    assert plans[0][0].method.package == "iverilog"

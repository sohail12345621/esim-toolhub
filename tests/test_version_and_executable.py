"""Tests for version parsing, comparison, executable discovery and tool adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from esim_toolhub.core.models import OSFamily, ToolStatus
from esim_toolhub.core.registry import Registry
from esim_toolhub.detection.executable import ExecutableLocator, expand_pattern
from esim_toolhub.detection.version import extract_version, parse_version, require_version
from esim_toolhub.tools.kicad import KiCadAdapter
from esim_toolhub.tools.ngspice import NgspiceAdapter
from tests.conftest import make_system


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9.0", (9, 0, 0)),
        ("9.0.1", (9, 0, 1)),
        ("v9.0.1", (9, 0, 1)),
        ("ngspice-44", (44, 0, 0)),
        ("ngspice-44.2", (44, 2, 0)),
        ("5.028", (5, 28, 0)),
        ("4.1.0-rc1", (4, 1, 0)),
    ],
)
def test_parse_version_variants(raw: str, expected: tuple[int, ...]) -> None:
    parsed = parse_version(raw)
    assert parsed is not None
    assert parsed.parts == expected


def test_version_numeric_comparison_not_lexicographic() -> None:
    assert require_version("10.0.8") > require_version("9.0.1")
    assert require_version("44") > require_version("36")
    assert require_version("5.028") > require_version("5.004")
    assert require_version("9.0") == require_version("9.0.0")
    assert parse_version("4.1.0-rc1") is not None and parse_version("4.1.0-rc1").prerelease is True


def test_extract_version_from_real_tool_banners(registry: Registry) -> None:
    ng_out = "******\n** ngspice-44 : Circuit level simulation program\n******"
    ghdl_out = "GHDL 4.1.0 (4.0.0.r39.g7188e92cf) [Dunoon edition]\n llvm 18.1.3 code generator"
    ver_out = "Verilator 5.028 2024-08-21 rev (Debian 5.028-1)"
    kicad_out = "9.0.1"

    assert str(extract_version(ng_out, registry.tool("ngspice").version_pattern)) == "44.0"
    assert str(extract_version(ghdl_out, registry.tool("ghdl").version_pattern)) == "4.1"
    assert str(extract_version(ver_out, registry.tool("verilator").version_pattern)) == "5.28"
    assert str(extract_version(kicad_out, registry.tool("kicad").version_pattern)) == "9.0.1"


def test_expand_pattern_orders_glob_newest_first_and_skips_missing_vars() -> None:
    assert expand_pattern("${UNDEFINED_VAR}/bin", {}, Path("/home/u")) == []
    results = expand_pattern(
        "${ProgramFiles}/KiCad/*/bin",
        {"ProgramFiles": "C:/Program Files"},
        Path("C:/Users/u"),
        glob_fn=lambda _: [
            "C:/Program Files/KiCad/8.0/bin",
            "C:/Program Files/KiCad/10.0/bin",
            "C:/Program Files/KiCad/9.0/bin",
        ],
    )
    assert results == [
        "C:/Program Files/KiCad/10.0/bin",
        "C:/Program Files/KiCad/9.0/bin",
        "C:/Program Files/KiCad/8.0/bin",
    ]


def test_executable_locator_prefers_path_then_managed_then_search(
    registry: Registry, tmp_path: Path
) -> None:
    sys_info = make_system(OSFamily.LINUX, path_entries=("/usr/bin",))
    spec = registry.tool("ngspice")

    # 1. PATH wins over managed
    managed_bin = tmp_path / "managed" / "ngspice"
    managed_bin.parent.mkdir(parents=True)
    managed_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    locator = ExecutableLocator(
        sys_info,
        which=lambda n: "/usr/bin/ngspice" if n == "ngspice" else None,
        managed_dirs=lambda _: [managed_bin.parent],
        is_executable=lambda p: p == managed_bin,
    )
    found = locator.locate(spec)
    assert found is not None
    assert found.source == "PATH"
    assert found.on_path is True

    # 2. Managed wins when not on PATH
    locator_no_path = ExecutableLocator(
        sys_info,
        which=lambda _: None,
        managed_dirs=lambda _: [managed_bin.parent],
        is_executable=lambda p: p == managed_bin,
    )
    found_managed = locator_no_path.locate(spec)
    assert found_managed is not None
    assert found_managed.source == "managed"
    assert found_managed.on_path is False


def test_kicad_adapter_skips_gui_probe_and_parses_path_version(registry: Registry) -> None:
    adapter = KiCadAdapter(registry.tool("kicad"))
    gui_exe = Path("C:/Program Files/KiCad/6.0/bin/kicad.exe")
    cli_exe = Path("C:/Program Files/KiCad/9.0/bin/kicad-cli.exe")
    assert adapter.can_probe(gui_exe) is False
    assert adapter.can_probe(cli_exe) is True
    assert str(adapter.fallback_version(gui_exe)) == "6.0"


def test_ngspice_adapter_prefers_console_sibling_and_handles_gui_timeout(
    registry: Registry,
) -> None:
    console_path = Path("C:/Spice64/bin/ngspice_con.exe")
    gui_path = Path("C:/Spice64/bin/ngspice.exe")
    adapter = NgspiceAdapter(registry.tool("ngspice"), file_exists=lambda p: p == console_path)
    assert adapter.version_command(gui_path, OSFamily.WINDOWS)[0] == str(console_path)
    status, msg = adapter.on_timeout(gui_path, OSFamily.WINDOWS)
    assert status is ToolStatus.UNKNOWN
    assert "ngspice_con.exe" in msg

"""Tool adapters. GHDL, Verilator and OpenModelica are fully described by tools.yaml
and use the generic adapter; only tools with real quirks get a class here."""

from __future__ import annotations

from esim_toolhub.core.models import ToolSpec
from esim_toolhub.tools.base import GenericToolAdapter
from esim_toolhub.tools.kicad import KiCadAdapter
from esim_toolhub.tools.ngspice import NgspiceAdapter

ADAPTERS: dict[str, type[GenericToolAdapter]] = {
    "kicad": KiCadAdapter,
    "ngspice": NgspiceAdapter,
}


def get_adapter(spec: ToolSpec) -> GenericToolAdapter:
    return ADAPTERS.get(spec.adapter or "", GenericToolAdapter)(spec)


__all__ = ["ADAPTERS", "GenericToolAdapter", "get_adapter"]

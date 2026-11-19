"""Profile expansion and dependency ordering (topological sort with cycle detection)."""

from __future__ import annotations

from collections.abc import Iterable

from esim_toolhub.core.exceptions import DependencyCycleError
from esim_toolhub.core.registry import Registry


class DependencyResolver:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def expand_profile(self, name: str) -> list[str]:
        """Tools of a profile including inherited profiles, parents first, de-duplicated."""
        ordered: list[str] = []
        visiting: list[str] = []

        def visit(profile_name: str) -> None:
            if profile_name in visiting:
                cycle = " -> ".join([*visiting, profile_name])
                raise DependencyCycleError(f"Profile inheritance cycle: {cycle}")
            visiting.append(profile_name)
            profile = self.registry.profile(profile_name)
            for parent in profile.extends:
                visit(parent)
            for tool in profile.tools:
                if tool not in ordered:
                    ordered.append(tool)
            visiting.pop()

        visit(name)
        return ordered

    def resolve(self, tools: Iterable[str]) -> list[str]:
        """Return ``tools`` plus their transitive dependencies, dependencies first."""
        ordered: list[str] = []
        done: set[str] = set()
        stack: list[str] = []

        def visit(name: str) -> None:
            if name in done:
                return
            if name in stack:
                cycle = " -> ".join([*stack[stack.index(name) :], name])
                raise DependencyCycleError(f"Dependency cycle: {cycle}")
            stack.append(name)
            for dep in self.registry.tool(name).depends_on:
                visit(dep)
            stack.pop()
            done.add(name)
            ordered.append(name)

        for tool in tools:
            visit(self.registry.tool(tool).name)
        return ordered

    def dependents_of(self, name: str) -> list[str]:
        return [s.name for s in self.registry.tools() if name in s.depends_on]

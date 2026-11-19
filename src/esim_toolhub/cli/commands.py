"""Typer CLI command definitions for eSim ToolHub."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import typer
from rich.console import Console

from esim_toolhub import __version__
from esim_toolhub.cli import formatter
from esim_toolhub.core.exceptions import ToolHubError
from esim_toolhub.core.manager import ToolHub

app = typer.Typer(
    name="esim-toolhub",
    help="eSim ToolHub - automated tool & dependency manager prototype for eSim.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(
    help="Inspect or modify ToolHub configuration and PATH guidance.",
    invoke_without_command=True,
)
app.add_typer(config_app, name="config")

# Injectable hooks for CLI tests.
_hub_factory: Callable[[], ToolHub] = ToolHub
_console = Console()
_debug_mode = False


def get_hub() -> ToolHub:
    return _hub_factory()


def _version_callback(value: bool) -> None:
    if value:
        _console.print(f"esim-toolhub {__version__}")
        raise typer.Exit(0)


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version", "-V", callback=_version_callback, is_eager=True, help="Show version."
        ),
    ] = False,
    debug: Annotated[
        bool, typer.Option("--debug", help="Show full tracebacks on unexpected errors.")
    ] = False,
) -> None:
    global _debug_mode
    _debug_mode = debug


@app.command()
def version() -> None:
    """Display eSim ToolHub version."""
    _console.print(f"esim-toolhub {__version__}")


@app.command()
def system(
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """Show detected OS, architecture, Python and package managers."""
    hub = get_hub()
    info = hub.system
    if as_json:
        formatter.print_json(
            _console,
            {
                "os_family": info.os_family.value,
                "os_name": info.os_name,
                "os_version": info.os_version,
                "architecture": info.architecture,
                "machine": info.machine,
                "python_version": info.python_version,
                "python_executable": info.python_executable,
                "distro_id": info.distro_id,
                "is_wsl": info.is_wsl,
                "is_admin": info.is_admin,
                "package_managers": info.package_managers,
                "path_entries_count": len(info.path_entries),
            },
        )
        return
    formatter.print_system(_console, info)


@app.command("list")
def list_tools(
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """List registered eSim ecosystem tools and profiles."""
    hub = get_hub()
    specs = hub.list_tools()
    profiles = hub.list_profiles()
    if as_json:
        formatter.print_json(
            _console,
            {
                "tools": [
                    {
                        "name": s.name,
                        "display_name": s.display_name,
                        "category": s.category,
                        "required": s.required,
                        "minimum_version": s.minimum_version,
                        "depends_on": list(s.depends_on),
                    }
                    for s in specs
                ],
                "profiles": [
                    {
                        "name": p.name,
                        "extends": list(p.extends),
                        "tools": list(p.tools),
                        "description": p.description,
                    }
                    for p in profiles
                ],
            },
        )
        return
    formatter.print_list(_console, specs, profiles, hub.system.os_family.value)


@app.command()
def status(
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """Show a concise overview of system info and tool health."""
    hub = get_hub()
    reports = hub.status(refresh=True)
    if as_json:
        formatter.print_json(
            _console,
            {
                "system": {
                    "os": hub.system.os_name,
                    "os_family": hub.system.os_family.value,
                    "architecture": hub.system.architecture,
                    "python": hub.system.python_version,
                },
                "tools": [r.to_dict() for r in reports],
            },
        )
        return
    formatter.print_status(_console, hub.system, reports)


@app.command()
def check(
    tool: Annotated[
        str | None, typer.Argument(help="Specific tool to inspect (default: all).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """Run a detailed dependency audit for one or all tools."""
    hub = get_hub()
    reports = hub.check(tool)
    if as_json:
        formatter.print_json(_console, [r.to_dict() for r in reports])
        return
    formatter.print_check(_console, reports)


@app.command()
def doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """Audit OS, Python, PATH, package managers, permissions and tools."""
    hub = get_hub()
    report = hub.doctor()
    if as_json:
        formatter.print_json(
            _console,
            {
                "overall": report.overall,
                "failures": report.failures,
                "warnings": report.warnings,
                "checks": [
                    {"level": c.level.value, "title": c.title, "detail": c.detail}
                    for c in report.checks
                ],
            },
        )
        return
    formatter.print_doctor(_console, report)
    if report.failures:
        raise typer.Exit(1)


@app.command()
def install(
    tools: Annotated[
        list[str] | None, typer.Argument(help="One or more tool IDs to install.")
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option("--profile", "-p", help="Install a profile (minimal, analog, digital, full)."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show the execution plan without modifying the system."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Reinstall even if a compatible version is already present."),
    ] = False,
    method: Annotated[
        str | None,
        typer.Option(
            "--method", help="Prefer a specific method (winget, choco, apt, archive, ...)."
        ),
    ] = None,
) -> None:
    """Install one or more eSim tools or a named profile."""
    if not tools and not profile:
        raise typer.BadParameter("Specify at least one tool name or --profile <name>.")
    hub = get_hub()
    outcomes = hub.install(
        tools or (), profile=profile, dry_run=dry_run, force=force, preferred_method=method
    )
    any_failed = False
    for plan, result in outcomes:
        formatter.print_plan(_console, plan, hub.system, dry_run=dry_run)
        if result is not None:
            formatter.print_install_result(_console, result)
            if not result.success:
                any_failed = True
    if any_failed:
        raise typer.Exit(1)


@app.command("install-profile")
def install_profile(
    profile: Annotated[str, typer.Argument(help="Profile name (minimal, analog, digital, full).")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview without making changes.")
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="Reinstall compatible tools.")] = False,
    method: Annotated[
        str | None, typer.Option("--method", help="Preferred install method.")
    ] = None,
) -> None:
    """Install all tools belonging to a profile (alias for 'install --profile')."""
    install(tools=None, profile=profile, dry_run=dry_run, force=force, method=method)


@app.command()
def uninstall(
    tool: Annotated[str, typer.Argument(help="Tool ID to uninstall.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Preview removal without changes.")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Uninstall a ToolHub-managed or package-manager tool."""
    hub = get_hub()
    installer = hub._require_installer()
    spec = hub.registry.tool(tool)
    plan = installer.plan_uninstall(spec)
    formatter.print_plan(_console, plan, hub.system, dry_run=dry_run)
    if dry_run or not plan.executable:
        if plan.blocked_reason and not dry_run:
            raise typer.Exit(1)
        return
    if not yes and not typer.confirm(
        f"Proceed with uninstalling {spec.display_name}?", default=False
    ):
        _console.print("Cancelled.")
        return
    result = installer.execute(plan)
    formatter.print_install_result(_console, result)
    if not result.success:
        raise typer.Exit(1)


@app.command()
def update(
    tool: Annotated[
        str | None, typer.Argument(help="Specific tool to check/update (default: all).")
    ] = None,
    check_only: Annotated[
        bool, typer.Option("--check-only", help="Only report update availability; do not upgrade.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show upgrade plans without modifying the system.")
    ] = False,
    online: Annotated[
        bool,
        typer.Option("--online", help="Query available package managers for upstream versions."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Apply available updates without confirmation prompt."),
    ] = False,
    include_unsupported: Annotated[
        bool,
        typer.Option(
            "--include-unsupported", help="Include major updates newer than eSim's tested series."
        ),
    ] = False,
) -> None:
    """Check for tool updates and optionally apply safe upgrades."""
    hub = get_hub()
    names = [tool] if tool else None
    if check_only:
        updates = hub.check_updates(names, online=online)
        formatter.print_updates(_console, updates)
        return

    updates, plans = hub.plan_updates(names, online=online, include_unsupported=include_unsupported)
    formatter.print_updates(_console, updates)
    if not plans:
        _console.print("\nNo eligible updates to apply.")
        return
    for plan in plans:
        formatter.print_plan(_console, plan, hub.system, dry_run=dry_run)
    if dry_run:
        return
    executable_plans = [p for p in plans if p.executable]
    if not executable_plans:
        raise typer.Exit(1)
    if not yes and not typer.confirm(f"Apply {len(executable_plans)} update(s)?", default=False):
        _console.print("Cancelled. No installations were modified.")
        return
    any_failed = False
    for _, result in hub.execute_plans(executable_plans):
        formatter.print_install_result(_console, result)
        if not result.success:
            any_failed = True
    if any_failed:
        raise typer.Exit(1)


@config_app.callback()
def config_default(ctx: typer.Context) -> None:
    """Show current configuration when called without a subcommand."""
    if ctx.invoked_subcommand is None:
        config_show()


@config_app.command("show")
def config_show() -> None:
    """Display active ToolHub configuration."""
    hub = get_hub()
    formatter.print_config(_console, hub.config, hub.paths.config_file)


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Configuration key.")],
    value: Annotated[str, typer.Argument(help="New value.")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Validate without saving.")] = False,
) -> None:
    """Update a persistent ToolHub configuration value."""
    hub = get_hub()
    if dry_run:
        # Validate against a throwaway copy by checking via ConfigManager helper.
        from esim_toolhub.configuration.manager import ConfigManager, _coerce

        valid_keys = ConfigManager.keys()
        if key not in valid_keys:
            raise ToolHubError(f"Unknown config key '{key}'.")
        coerced = _coerce(key, value)
        candidate = hub.config_manager.load()
        setattr(candidate, key, coerced)
        candidate.validate()
        _console.print(f"DRY RUN: would set {key} = {coerced!r} in {hub.paths.config_file}")
        return
    updated = hub.config_manager.set(key, value)
    formatter.print_config(_console, updated, hub.paths.config_file)


@config_app.command("reset")
def config_reset() -> None:
    """Reset configuration to defaults."""
    hub = get_hub()
    updated = hub.config_manager.reset()
    formatter.print_config(_console, updated, hub.paths.config_file)


@config_app.command("env")
def config_env() -> None:
    """Show managed tool directories and PATH setup commands."""
    hub = get_hub()
    missing, snippet = hub.environment_guidance()
    managed = hub.environment.all_dirs()
    if managed:
        _console.print("[bold]Managed tool directories:[/bold]")
        for name, path in managed.items():
            _console.print(f"  {name}: {path}")
    if not missing:
        _console.print("[green]All detected/managed tool directories are already on PATH.[/green]")
        return
    _console.print("\n[bold]Directories missing from PATH:[/bold]")
    for d in missing:
        _console.print(f"  - {d}")
    _console.print(f"\n{snippet}")


@config_app.command("path")
def config_path() -> None:
    """Print ToolHub config, data, log and cache directory paths."""
    hub = get_hub()
    _console.print(f"config: {hub.paths.config_file}")
    _console.print(f"data:   {hub.paths.data_dir}")
    _console.print(f"logs:   {hub.paths.log_file}")
    _console.print(f"cache:  {hub.paths.cache_dir}")


@app.command()
def logs(
    tail: Annotated[
        int, typer.Option("--tail", "-n", help="Number of recent entries to show.")
    ] = 50,
    level: Annotated[
        str, typer.Option("--level", help="Minimum log level (DEBUG, INFO, WARNING, ERROR).")
    ] = "DEBUG",
    show_path: Annotated[bool, typer.Option("--path", help="Print log file path only.")] = False,
) -> None:
    """Inspect structured ToolHub logs."""
    hub = get_hub()
    if show_path:
        _console.print(str(hub.paths.log_file))
        return
    entries = hub.read_logs(tail=tail, min_level=level)
    formatter.print_logs(_console, entries, hub.paths.log_file)


@app.command()
def demo() -> None:
    """Display a deterministic, simulated environment showcase (does not touch your system)."""
    hub = get_hub()
    demo_sys, reports, doc = hub.demo_snapshot()
    formatter.print_status(
        _console,
        demo_sys,
        reports,
        banner_subtitle="SIMULATED DEMO - Not your real host environment",
    )
    _console.print()
    formatter.print_doctor(_console, doc)

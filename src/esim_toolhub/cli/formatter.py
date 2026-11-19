"""Clean, restrained Rich output formatters for the eSim ToolHub CLI."""

from __future__ import annotations

import json
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from esim_toolhub import __version__
from esim_toolhub.configuration.manager import ToolHubConfig
from esim_toolhub.core.models import (
    CheckLevel,
    DoctorReport,
    InstallPlan,
    InstallResult,
    Profile,
    SystemInfo,
    ToolReport,
    ToolSpec,
    ToolStatus,
    UpdateInfo,
    UpdateState,
)
from esim_toolhub.logs.manager import LogEntry

_STATUS_STYLE: dict[ToolStatus, tuple[str, str]] = {
    ToolStatus.INSTALLED: ("green", "Installed"),
    ToolStatus.MISSING: ("red", "Missing"),
    ToolStatus.OUTDATED: ("yellow", "Outdated"),
    ToolStatus.INCOMPATIBLE: ("red", "Incompatible"),
    ToolStatus.BROKEN: ("red", "Broken"),
    ToolStatus.UNKNOWN: ("yellow", "Unknown"),
}

_STATUS_MARK_UTF8: dict[ToolStatus, str] = {
    ToolStatus.INSTALLED: "✓",
    ToolStatus.MISSING: "✗",
    ToolStatus.OUTDATED: "!",
    ToolStatus.INCOMPATIBLE: "✗",
    ToolStatus.BROKEN: "✗",
    ToolStatus.UNKNOWN: "?",
}

_STATUS_MARK_ASCII: dict[ToolStatus, str] = {
    ToolStatus.INSTALLED: "+",
    ToolStatus.MISSING: "x",
    ToolStatus.OUTDATED: "!",
    ToolStatus.INCOMPATIBLE: "x",
    ToolStatus.BROKEN: "x",
    ToolStatus.UNKNOWN: "?",
}


def _supports_unicode(console: Console) -> bool:
    enc = (console.encoding or "").lower().replace("-", "")
    return enc.startswith("utf")


def _mark(console: Console, status: ToolStatus) -> str:
    return (_STATUS_MARK_UTF8 if _supports_unicode(console) else _STATUS_MARK_ASCII)[status]


def _dash(console: Console) -> str:
    return "—" if _supports_unicode(console) else "-"


_LEVEL_STYLE: dict[CheckLevel, str] = {
    CheckLevel.PASS: "green",
    CheckLevel.WARN: "yellow",
    CheckLevel.FAIL: "red",
    CheckLevel.INFO: "cyan",
}

_UPDATE_STYLE: dict[UpdateState, str] = {
    UpdateState.UP_TO_DATE: "green",
    UpdateState.UPDATE_AVAILABLE: "cyan",
    UpdateState.UNSUPPORTED_UPDATE: "yellow",
    UpdateState.NOT_INSTALLED: "dim",
    UpdateState.UNKNOWN: "yellow",
}


def print_json(console: Console, data: Any) -> None:
    console.print(json.dumps(data, indent=2), highlight=False, soft_wrap=True)


def print_banner(console: Console, subtitle: str = "Environment & Dependency Manager") -> None:
    body = Text(justify="center")
    body.append(f"eSim ToolHub  v{__version__}\n", style="bold")
    body.append(subtitle, style="dim")
    console.print(Panel(body, expand=False, border_style="blue", padding=(0, 6)))


def print_system(console: Console, system: SystemInfo) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold dim", no_wrap=True)
    table.add_column("Value")
    table.add_row("OS", f"{system.os_name} ({system.os_family.value})")
    table.add_row("ARCH", f"{system.architecture} ({system.machine})")
    table.add_row("Python", f"{system.python_version} ({system.python_executable})")
    if system.distro_id:
        table.add_row("Distro", system.distro_id)
    if system.is_wsl:
        table.add_row("WSL", "yes")
    pms = ", ".join(sorted(system.package_managers)) if system.package_managers else "none detected"
    table.add_row("Package managers", pms)
    table.add_row("Privileges", "administrator / root" if system.is_admin else "standard user")
    table.add_row("PATH entries", str(len(system.path_entries)))
    console.print(table)


def print_status(
    console: Console,
    system: SystemInfo,
    reports: Sequence[ToolReport],
    *,
    banner_subtitle: str = "Environment & Dependency Manager",
) -> None:
    print_banner(console, subtitle=banner_subtitle)
    console.print("\n[bold]SYSTEM[/bold]")
    info = Table(show_header=False, box=None, padding=(0, 2))
    info.add_column(style="dim", width=10)
    info.add_column()
    info.add_row("OS", system.os_name)
    info.add_row("ARCH", system.architecture)
    info.add_row("Python", system.python_version)
    console.print(info)

    console.print("\n[bold]TOOLS[/bold]")
    table = Table(show_header=True, box=None, padding=(0, 2))
    table.add_column("", width=2, no_wrap=True)
    table.add_column("Tool", style="bold", no_wrap=True)
    table.add_column("Version", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Role", style="dim")

    dash = _dash(console)
    for r in reports:
        style, label = _STATUS_STYLE[r.status]
        mark = _mark(console, r.status)
        ver = str(r.version) if r.version else dash
        role = "required" if r.spec.required else "optional"
        table.add_row(
            f"[{style}]{mark}[/{style}]",
            r.spec.display_name,
            ver,
            f"[{style}]{label}[/{style}]",
            role,
        )
    console.print(table)

    required = [r for r in reports if r.spec.required]
    req_ok = sum(1 for r in required if r.status.satisfied)
    all_ok = sum(1 for r in reports if r.status.satisfied)
    compat = "[green]PASS[/green]" if req_ok == len(required) else "[red]FAIL[/red]"
    console.print(
        f"\nCompatibility: {compat}   "
        f"Required: {req_ok}/{len(required)}   "
        f"All tools: {all_ok}/{len(reports)}"
    )

    missing = [r.spec.name for r in reports if r.status is ToolStatus.MISSING]
    if missing:
        console.print("\nNext step:")
        for name in missing[:3]:
            console.print(f"  [bold]esim-toolhub install {name}[/bold]")


def print_check(console: Console, reports: Sequence[ToolReport]) -> None:
    for r in reports:
        style, _ = _STATUS_STYLE[r.status]
        console.print(f"\n[bold]{r.spec.display_name}[/bold] ({r.spec.name})")
        console.print(f"  Status:        [{style}]{r.status.value}[/{style}]")
        console.print(f"  Required:      {'yes' if r.spec.required else 'no (optional)'}")
        if r.spec.minimum_version:
            console.print(f"  Min Version:   >= {r.spec.minimum_version}")
        console.print(f"  Detected:      {r.version if r.version else 'None'}")
        if r.executable:
            console.print(f"  Path:          {r.executable}")
            path_str = "[green]PASS[/green]" if r.on_path else "[yellow]NOT ON PATH[/yellow]"
            console.print(f"  PATH:          {path_str}")
        if r.variant:
            console.print(f"  Variant:       {r.variant}")
        comp_style = _LEVEL_STYLE[r.compatibility]
        console.print(f"  Compatibility: [{comp_style}]{r.compatibility.value}[/{comp_style}]")
        if r.message:
            console.print(f"  Detail:        {r.message}")
        for w in r.warnings:
            console.print(f"  [yellow]Warning:[/yellow]       {w}")
        dash = _dash(console)
        for req in r.host_requirements:
            state = (
                f"[green]found ({req.found})[/green]"
                if req.satisfied
                else "[yellow]missing[/yellow]"
            )
            console.print(f"  Host prereq:   {req.requirement.name} {dash} {state}")
        if r.recommendation:
            console.print(f"  Action:        {r.recommendation}")


def print_list(
    console: Console,
    specs: Sequence[ToolSpec],
    profiles: Sequence[Profile],
    os_name: str,
) -> None:
    table = Table(title="Registered eSim Ecosystem Tools", box=None, padding=(0, 2))
    table.add_column("ID", style="bold", no_wrap=True)
    table.add_column("Name", no_wrap=True)
    table.add_column("Category", style="dim")
    table.add_column("Min Ver", no_wrap=True)
    table.add_column("Required", no_wrap=True)
    table.add_column(f"Methods ({os_name})")
    dash = _dash(console)
    for s in specs:
        methods = ", ".join(m.type.value for m in s.install.get(os_name, ())) or dash
        table.add_row(
            s.name,
            s.display_name,
            s.category,
            f">={s.minimum_version}" if s.minimum_version else dash,
            "yes" if s.required else "optional",
            methods,
        )
    console.print(table)

    ptable = Table(title="\nProfiles", box=None, padding=(0, 2))
    ptable.add_column("Profile", style="bold", no_wrap=True)
    ptable.add_column("Extends", style="dim")
    ptable.add_column("Adds tools")
    ptable.add_column("Description")
    for p in profiles:
        ptable.add_row(
            p.name,
            ", ".join(p.extends) or dash,
            ", ".join(p.tools) or dash,
            p.description,
        )
    console.print(ptable)


def print_doctor(console: Console, report: DoctorReport) -> None:
    dash = _dash(console)
    console.print("[bold]eSim ToolHub Doctor[/bold]\n")
    for check in report.checks:
        style = _LEVEL_STYLE[check.level]
        tag = f"[{style}][{check.level.value:^4}][/{style}]"
        suffix = f" [dim]{dash} {check.detail}[/dim]" if check.detail else ""
        console.print(f"{tag} {check.title}{suffix}")

    overall_style = "red" if report.failures else ("yellow" if report.warnings else "green")
    console.print(
        f"\nOverall: [{overall_style} bold]{report.overall}[/{overall_style} bold] "
        f"({report.failures} failures, {report.warnings} warnings)"
    )


def print_plan(
    console: Console,
    plan: InstallPlan,
    system: SystemInfo,
    *,
    dry_run: bool = False,
) -> None:
    dash = _dash(console)
    header = "DRY RUN" if dry_run else f"PLAN ({plan.action.upper()})"
    console.print(f"\n[bold]{header} {dash} {plan.tool.display_name}[/bold]")
    console.print(f"  Platform:  {system.os_name} ({system.architecture})")
    console.print(f"  Current:   {plan.current_version or 'Not installed'}")
    console.print(f"  Target:    {plan.target_version or dash}")
    console.print(f"  Method:    {plan.method.label() if plan.method else 'none'}")
    if plan.requires_admin:
        console.print("  Elevation: [yellow]requires administrator / sudo[/yellow]")

    if plan.steps:
        console.print("  Actions:")
        for idx, step in enumerate(plan.steps, start=1):
            console.print(f"    {idx}. {step.description}")
            if step.command:
                console.print(
                    f"       [dim]$ {' '.join(shlex.quote(c) for c in step.command)}[/dim]"
                )

    for note in plan.notes:
        console.print(f"  [dim]Note: {note}[/dim]")
    if plan.blocked_reason:
        console.print(f"  [yellow]Blocked: {plan.blocked_reason}[/yellow]")
    if dry_run:
        console.print("  [dim]No changes were made.[/dim]")


def print_install_result(console: Console, result: InstallResult) -> None:
    if result.success:
        ok_mark = _mark(console, ToolStatus.INSTALLED)
        console.print(f"[green]{ok_mark}[/green] {result.message}")
    else:
        fail_mark = _mark(console, ToolStatus.MISSING)
        console.print(f"[red]{fail_mark}[/red] {result.message}")


def print_updates(console: Console, updates: Sequence[UpdateInfo]) -> None:
    dash = _dash(console)
    table = Table(title="Update Check", box=None, padding=(0, 2))
    table.add_column("Tool", style="bold", no_wrap=True)
    table.add_column("Current", no_wrap=True)
    table.add_column("Latest", no_wrap=True)
    table.add_column("Source", style="dim", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Notes")
    for u in updates:
        style = _UPDATE_STYLE[u.state]
        table.add_row(
            u.display_name,
            u.current or dash,
            u.latest or dash,
            u.source,
            f"[{style}]{u.state.value}[/{style}]",
            u.message,
        )
    console.print(table)


def print_config(console: Console, config: ToolHubConfig, config_path: Path) -> None:
    table = Table(title=f"Configuration ({config_path})", box=None, padding=(0, 2))
    table.add_column("Key", style="bold", no_wrap=True)
    table.add_column("Value")
    for k, v in config.to_dict().items():
        table.add_row(k, "null" if v is None else str(v))
    console.print(table)


def print_logs(console: Console, entries: Sequence[LogEntry], log_path: Path) -> None:
    if not entries:
        console.print(f"[dim]No log entries in {log_path}[/dim]")
        return
    for entry in entries:
        extra_str = " ".join(f"{k}={v}" for k, v in entry.extra.items())
        suffix = f" [dim]{extra_str}[/dim]" if extra_str else ""
        console.print(f"[dim]{entry.ts}[/dim] {entry.level:<7} {entry.msg}{suffix}")

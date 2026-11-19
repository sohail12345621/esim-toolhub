"""CLI entry point with user-friendly error handling."""

from __future__ import annotations

import sys

from rich.console import Console

from esim_toolhub.cli import commands
from esim_toolhub.core.exceptions import ToolHubError

_err_console = Console(stderr=True)


def run() -> None:
    try:
        commands.app()
    except ToolHubError as exc:
        if commands._debug_mode:
            raise
        _err_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(exc.exit_code)
    except KeyboardInterrupt:
        _err_console.print("\nInterrupted.")
        sys.exit(130)


if __name__ == "__main__":
    run()

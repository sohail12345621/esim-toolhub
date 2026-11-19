"""The single choke point for running external programs.

Rules enforced here:
  * arguments are always a sequence of strings (never a shell string)
  * ``shell=False`` always
  * every call has a timeout
  * stdin is closed so a prompting program cannot hang ToolHub
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from esim_toolhub.core.exceptions import CommandExecutionError
from esim_toolhub.security.validation import redact

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def output(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()


@runtime_checkable
class CommandRunner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = DEFAULT_TIMEOUT,
        capture: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult: ...


class SubprocessRunner:
    """Production CommandRunner backed by ``subprocess.run``."""

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = DEFAULT_TIMEOUT,
        capture: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        if isinstance(args, (str, bytes)) or not args:
            raise TypeError("SubprocessRunner.run requires a non-empty argument list, not a string")
        argv = tuple(str(a) for a in args)
        log.debug("exec", extra={"event": "exec", "argv": redact(" ".join(argv))})
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if capture and os.name == "nt" else 0
        start = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                capture_output=capture,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
                env=dict(env) if env is not None else None,
                creationflags=flags,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            out = (
                exc.stdout.decode(errors="replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )
            return CommandResult(
                argv, -1, out, "", timed_out=True, duration=time.monotonic() - start
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise CommandExecutionError(f"Cannot execute {argv[0]}: {exc}") from exc
        result = CommandResult(
            argv,
            proc.returncode,
            proc.stdout or "",
            proc.stderr or "",
            duration=time.monotonic() - start,
        )
        log.debug("exit", extra={"event": "exit", "argv0": argv[0], "returncode": proc.returncode})
        return result

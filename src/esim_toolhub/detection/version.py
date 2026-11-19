"""Tolerant version parsing and comparison.

Tool version strings are not semver. Examples handled here:

    9.0          -> (9, 0, 0)
    v9.0.1       -> (9, 0, 1)
    ngspice-44   -> (44, 0, 0)
    ngspice-44.2 -> (44, 2, 0)
    5.028        -> (5, 28, 0)    (Verilator zero-pads its minor number)
    GHDL 4.1.0 (4.0.0.r39.g7188e92cf) [Dunoon edition] -> (4, 1, 0)

Versions compare numerically component by component, never as strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_GENERIC = re.compile(r"(?<![\w.])v?(\d+(?:\.\d+){0,3})(?![\d])", re.IGNORECASE)
_PRERELEASE = re.compile(r"(?:-|\.)?(rc|alpha|beta|dev|pre)\d*", re.IGNORECASE)


@dataclass(frozen=True, order=True)
class Version:
    """A numeric version. ``raw`` keeps the original text for display only."""

    parts: tuple[int, ...]
    prerelease: bool = field(default=False, compare=False)
    raw: str = field(default="", compare=False)

    @property
    def major(self) -> int:
        return self.parts[0]

    @property
    def minor(self) -> int:
        return self.parts[1] if len(self.parts) > 1 else 0

    def __str__(self) -> str:
        parts = list(self.parts)
        while len(parts) > 2 and parts[-1] == 0:
            parts.pop()
        return ".".join(str(p) for p in parts)


def _make(numeric: str, raw: str) -> Version:
    nums = [int(p) for p in numeric.split(".")]
    while len(nums) < 3:
        nums.append(0)
    while len(nums) > 3 and nums[-1] == 0:
        nums.pop()
    return Version(parts=tuple(nums), prerelease=bool(_PRERELEASE.search(raw)), raw=raw.strip())


def parse_version(text: str | None) -> Version | None:
    """Parse a single version-like token (``"v9.0.1"``, ``"ngspice-44"``, ``"5.028"``)."""
    if not text:
        return None
    text = text.strip()
    match = re.search(r"(\d+(?:\.\d+){0,3})", text)
    if not match:
        return None
    return _make(match.group(1), text)


def extract_version(output: str, pattern: str | None = None) -> Version | None:
    """Extract a version from free-form command output.

    ``pattern`` is a tool-specific regex with one capture group (from tools.yaml).
    It is tried first; the generic scanner is the fallback.
    """
    if not output:
        return None
    if pattern:
        match = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
        if match:
            return parse_version(match.group(1))
    match = _GENERIC.search(output)
    return parse_version(match.group(1)) if match else None


def require_version(text: str) -> Version:
    version = parse_version(text)
    if version is None:
        raise ValueError(f"not a version: {text!r}")
    return version

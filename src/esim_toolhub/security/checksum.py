"""SHA256 helpers."""

from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path

from esim_toolhub.core.exceptions import ChecksumMismatchError

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 1024 * 1024


def is_valid_sha256(value: str | None) -> bool:
    return bool(value) and bool(_SHA256.match(value.lower()))  # type: ignore[union-attr]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> str:
    """Raise ChecksumMismatchError unless ``path`` hashes to ``expected``."""
    if not is_valid_sha256(expected):
        raise ChecksumMismatchError(f"Invalid expected SHA256 value: {expected!r}")
    actual = sha256_file(path)
    if not hmac.compare_digest(actual, expected.lower()):
        raise ChecksumMismatchError(
            f"SHA256 mismatch for {path.name}: expected {expected.lower()}, got {actual}"
        )
    return actual

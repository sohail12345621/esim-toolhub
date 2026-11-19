"""Input validation and redaction helpers used at every trust boundary."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

from esim_toolhub.core.exceptions import SecurityError, UntrustedSourceError

# Package ids/names passed to package managers. Must not start with '-' so they can
# never be interpreted as an option (argument injection).
_PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_@-]{0,127}$")
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

_SENSITIVE_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|auth|credential|cookie)", re.I
)
REDACTED = "***REDACTED***"
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?\S+"), rf"\1{REDACTED}"),
    (
        re.compile(r"(?i)((?:pass(?:word|wd)?|secret|token|api[_-]?key)\s*[:=]\s*)\S+"),
        rf"\1{REDACTED}",
    ),
    (re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@"), rf"\1{REDACTED}@"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), REDACTED),
]


def validate_package_id(value: str) -> str:
    if not _PACKAGE_ID.match(value or ""):
        raise SecurityError(f"Refusing unsafe package identifier: {value!r}")
    return value


def validate_tool_name(value: str) -> str:
    if not _TOOL_NAME.match(value or ""):
        raise SecurityError(f"Invalid tool name: {value!r}")
    return value


def validate_url(url: str, trusted_hosts: Iterable[str]) -> str:
    """Accept only ``https://`` URLs whose host is exactly on the allowlist."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise UntrustedSourceError(f"Only HTTPS downloads are allowed: {url}")
    if parts.username or parts.password:
        raise UntrustedSourceError("Credentials in URLs are not allowed")
    host = (parts.hostname or "").lower()
    allowed = {h.lower() for h in trusted_hosts}
    if host not in allowed:
        raise UntrustedSourceError(f"Host '{host}' is not on the trusted download allowlist")
    return url


def redact(text: str) -> str:
    """Mask secrets that may appear in free text (headers, URLs, key=value pairs)."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_mapping(values: Mapping[str, str]) -> dict[str, str]:
    """Copy of an environment-like mapping with sensitive values masked."""
    return {k: (REDACTED if _SENSITIVE_KEY.search(k) else v) for k, v in values.items()}

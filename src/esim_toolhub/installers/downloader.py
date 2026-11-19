"""Safe HTTPS artifact downloader with redirect allowlisting and streaming size limits."""

from __future__ import annotations

import logging
import os
import tempfile
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from esim_toolhub.core.exceptions import (
    DownloadError,
    DownloadTooLargeError,
    UntrustedSourceError,
)
from esim_toolhub.security.validation import validate_url

log = logging.getLogger(__name__)

CHUNK_SIZE = 256 * 1024
USER_AGENT = "esim-toolhub/0.1.0"


@runtime_checkable
class Downloader(Protocol):
    def download(
        self,
        url: str,
        dest: Path,
        *,
        trusted_hosts: Iterable[str],
        max_bytes: int,
        timeout: float = 60.0,
    ) -> Path: ...


class _TrustedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validates every HTTP redirect target against the HTTPS + host allowlist."""

    def __init__(self, trusted_hosts: tuple[str, ...]) -> None:
        super().__init__()
        self._trusted_hosts = trusted_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        validate_url(newurl, self._trusted_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpDownloader:
    """Production Downloader using stdlib urllib with strict security controls."""

    def download(
        self,
        url: str,
        dest: Path,
        *,
        trusted_hosts: Iterable[str],
        max_bytes: int,
        timeout: float = 60.0,
    ) -> Path:
        allowed = tuple(trusted_hosts)
        validate_url(url, allowed)

        dest.parent.mkdir(parents=True, exist_ok=True)
        opener = urllib.request.build_opener(_TrustedRedirectHandler(allowed))
        request = urllib.request.Request(  # noqa: S310 - HTTPS + allowlist enforced above
            url, headers={"User-Agent": USER_AGENT}
        )

        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".download-", suffix=".part")
        tmp_path = Path(tmp_name)
        total = 0
        try:
            with os.fdopen(fd, "wb") as out_fh, opener.open(request, timeout=timeout) as resp:
                # Re-verify final URL after redirects.
                validate_url(resp.geturl(), allowed)
                content_length = resp.headers.get("Content-Length")
                if content_length and content_length.isdigit() and int(content_length) > max_bytes:
                    raise DownloadTooLargeError(
                        f"Remote file ({int(content_length)} bytes) exceeds limit "
                        f"({max_bytes} bytes)"
                    )
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise DownloadTooLargeError(
                            f"Download exceeded maximum allowed size ({max_bytes} bytes)"
                        )
                    out_fh.write(chunk)
            os.replace(tmp_path, dest)
            log.info(
                "Downloaded artifact",
                extra={"event": "download", "url": url, "bytes": total, "dest": dest.name},
            )
            return dest
        except (UntrustedSourceError, DownloadTooLargeError):
            if tmp_path.exists():
                tmp_path.unlink()
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if tmp_path.exists():
                tmp_path.unlink()
            raise DownloadError(f"Download failed for {url}: {exc}") from exc

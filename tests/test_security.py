"""Tests for URL allowlisting, checksum verification, safe extraction and log redaction."""

from __future__ import annotations

import hashlib
import io
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from esim_toolhub.core.exceptions import (
    ChecksumMismatchError,
    SecurityError,
    UnsafeArchiveError,
    UntrustedSourceError,
)
from esim_toolhub.logs.manager import read_logs, setup_logging
from esim_toolhub.security.archive import safe_extract
from esim_toolhub.security.checksum import sha256_file, verify_sha256
from esim_toolhub.security.validation import (
    REDACTED,
    redact,
    redact_mapping,
    validate_package_id,
    validate_url,
)


def test_url_validation_requires_https_and_exact_host_allowlist() -> None:
    trusted = ("github.com", "downloads.kicad.org")
    assert validate_url("https://github.com/ghdl/ghdl/releases/download/v6.0.0/a.zip", trusted)

    with pytest.raises(UntrustedSourceError):
        validate_url("http://github.com/ghdl/ghdl/a.zip", trusted)
    with pytest.raises(UntrustedSourceError):
        validate_url("https://github.com.evil.example/a.zip", trusted)
    with pytest.raises(UntrustedSourceError):
        validate_url("https://user:secret@github.com/a.zip", trusted)


@pytest.mark.parametrize("bad", ["", "-y", "--option", "pkg;rm -rf /", "pkg$(id)", "a b"])
def test_validate_package_id_blocks_injection(bad: str) -> None:
    with pytest.raises(SecurityError):
        validate_package_id(bad)


def test_verify_sha256_passes_and_rejects_mismatch(tmp_path: Path) -> None:
    payload = b"esim-toolhub-artifact"
    artifact = tmp_path / "tool.zip"
    artifact.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    assert sha256_file(artifact) == digest
    assert verify_sha256(artifact, digest) == digest

    with pytest.raises(ChecksumMismatchError):
        verify_sha256(artifact, "0" * 64)
    with pytest.raises(ChecksumMismatchError):
        verify_sha256(artifact, "not-a-hash")


def test_safe_extract_zip_valid_and_rejects_traversal_and_symlinks(tmp_path: Path) -> None:
    good_zip = tmp_path / "good.zip"
    with zipfile.ZipFile(good_zip, "w") as zf:
        zf.writestr("bin/tool.exe", b"binary")
    out = safe_extract(good_zip, tmp_path / "out_good")
    assert (out / "bin" / "tool.exe").read_bytes() == b"binary"

    evil_zip = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil_zip, "w") as zf:
        zf.writestr("../escape.txt", b"pwn")
    with pytest.raises(UnsafeArchiveError, match="traversal"):
        safe_extract(evil_zip, tmp_path / "out_evil")

    symlink_zip = tmp_path / "symlink.zip"
    with zipfile.ZipFile(symlink_zip, "w") as zf:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/etc/passwd")
    with pytest.raises(UnsafeArchiveError, match="Symlink"):
        safe_extract(symlink_zip, tmp_path / "out_sym")

    bomb_zip = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb_zip, "w") as zf:
        zf.writestr("big.bin", b"x" * 1024)
    with pytest.raises(UnsafeArchiveError, match="size limit"):
        safe_extract(bomb_zip, tmp_path / "out_bomb", max_total_bytes=100)


def test_safe_extract_tar_rejects_escaping_symlink_and_absolute_path(tmp_path: Path) -> None:
    evil_tar = tmp_path / "evil.tar.gz"
    with tarfile.open(evil_tar, "w:gz") as tf:
        info = tarfile.TarInfo("sub/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../../etc/passwd"
        tf.addfile(info)
    with pytest.raises(UnsafeArchiveError, match="escapes"):
        safe_extract(evil_tar, tmp_path / "out_tar")

    abs_tar = tmp_path / "abs.tar.gz"
    with tarfile.open(abs_tar, "w:gz") as tf:
        data = b"hello"
        info = tarfile.TarInfo("/etc/evil")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    with pytest.raises(UnsafeArchiveError, match="Absolute"):
        safe_extract(abs_tar, tmp_path / "out_abs")


def test_redaction_and_structured_logging_strip_secrets(tmp_path: Path) -> None:
    assert REDACTED in redact("Authorization: Bearer supersecretvalue")
    assert "supersecretvalue" not in redact("token=supersecretvalue")
    assert "ghp_" not in redact("ghp_1234567890abcdefghij123456")
    masked = redact_mapping({"PATH": "/usr/bin", "GITHUB_TOKEN": "topsecret"})
    assert masked["PATH"] == "/usr/bin"
    assert masked["GITHUB_TOKEN"] == REDACTED

    log_file = tmp_path / "toolhub.log"
    logger = setup_logging(log_file, level="DEBUG")
    logger.info("Connecting with api_key=my_secret_123", extra={"token": "password=abc"})
    entries = read_logs(log_file, tail=10)
    assert len(entries) == 1
    assert "my_secret_123" not in entries[0].msg
    assert REDACTED in entries[0].msg
    assert entries[0].extra["token"] == f"password={REDACTED}"


def test_subprocess_runner_rejects_shell_strings_and_runs_safe_argv() -> None:
    import sys

    from esim_toolhub.core.runner import SubprocessRunner

    runner = SubprocessRunner()
    with pytest.raises(TypeError):
        runner.run("echo hi")  # type: ignore[arg-type]

    res = runner.run([sys.executable, "-c", "print('ok')"], timeout=10)
    assert res.ok is True
    assert res.stdout.strip() == "ok"


def test_http_downloader_blocks_untrusted_and_oversized_responses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from esim_toolhub.core.exceptions import DownloadTooLargeError
    from esim_toolhub.installers.downloader import HttpDownloader

    dl = HttpDownloader()
    with pytest.raises(UntrustedSourceError):
        dl.download(
            "http://github.com/file.zip",
            tmp_path / "f.zip",
            trusted_hosts=("github.com",),
            max_bytes=1024,
        )

    class _FakeResp:
        headers = {"Content-Length": "999999"}

        def geturl(self) -> str:
            return "https://github.com/file.zip"

        def read(self, n: int = -1) -> bytes:
            return b""

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class _FakeOpener:
        def open(self, req: object, timeout: float = 60.0) -> _FakeResp:
            return _FakeResp()

    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **kw: _FakeOpener())
    with pytest.raises(DownloadTooLargeError):
        dl.download(
            "https://github.com/file.zip",
            tmp_path / "f.zip",
            trusted_hosts=("github.com",),
            max_bytes=100,
        )

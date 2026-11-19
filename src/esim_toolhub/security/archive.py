"""Safe archive extraction (zip, tar.gz, tar.xz, tar.bz2).

Rejects: absolute paths, '..' traversal, drive letters, links escaping the target,
device/FIFO members, too many members, and total uncompressed size over a limit.
"""

from __future__ import annotations

import os
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from esim_toolhub.core.exceptions import UnsafeArchiveError

DEFAULT_MAX_TOTAL = 4 * 1024**3
DEFAULT_MAX_MEMBERS = 200_000


def _check_name(name: str, dest: Path) -> Path:
    if not name or "\x00" in name:
        raise UnsafeArchiveError(f"Invalid member name {name!r}")
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or (len(normalized) > 1 and normalized[1] == ":"):
        raise UnsafeArchiveError(f"Absolute path in archive: {name}")
    if ".." in pure.parts:
        raise UnsafeArchiveError(f"Path traversal in archive: {name}")
    target = (dest / Path(*pure.parts)).resolve() if pure.parts else dest
    if not _within(target, dest):
        raise UnsafeArchiveError(f"Member escapes destination: {name}")
    return target


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def archive_kind(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".zip"):
        return "zip"
    if name.endswith((".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tar")):
        return "tar"
    raise UnsafeArchiveError(f"Unsupported archive format: {path.name}")


def safe_extract(
    archive: Path,
    dest: Path,
    *,
    max_total_bytes: int = DEFAULT_MAX_TOTAL,
    max_members: int = DEFAULT_MAX_MEMBERS,
) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    dest = dest.resolve()
    if archive_kind(archive) == "zip":
        _extract_zip(archive, dest, max_total_bytes, max_members)
    else:
        _extract_tar(archive, dest, max_total_bytes, max_members)
    return dest


def _extract_zip(archive: Path, dest: Path, max_total: int, max_members: int) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if len(infos) > max_members:
            raise UnsafeArchiveError("Archive has too many members")
        total = 0
        for info in infos:
            _check_name(info.filename, dest)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UnsafeArchiveError(f"Symlink in zip archive: {info.filename}")
            total += info.file_size
            if total > max_total:
                raise UnsafeArchiveError("Archive exceeds uncompressed size limit")
        for info in infos:
            zf.extract(info, dest)
            mode = (info.external_attr >> 16) & 0o777
            if mode and os.name != "nt":
                (dest / info.filename).chmod(mode & 0o755)


def _extract_tar(archive: Path, dest: Path, max_total: int, max_members: int) -> None:
    with tarfile.open(archive, "r:*") as tf:
        members = tf.getmembers()
        if len(members) > max_members:
            raise UnsafeArchiveError("Archive has too many members")
        total = 0
        for m in members:
            target = _check_name(m.name, dest)
            if m.isdev() or m.isfifo():
                raise UnsafeArchiveError(f"Device or FIFO in archive: {m.name}")
            if m.issym() or m.islnk():
                link = m.linkname.replace("\\", "/")
                if PurePosixPath(link).is_absolute():
                    raise UnsafeArchiveError(f"Absolute link target: {m.name} -> {m.linkname}")
                base = target.parent if m.issym() else dest
                if not _within((base / link).resolve(), dest):
                    raise UnsafeArchiveError(f"Link escapes destination: {m.name} -> {m.linkname}")
            total += max(m.size, 0)
            if total > max_total:
                raise UnsafeArchiveError("Archive exceeds uncompressed size limit")
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, members=members, filter="data")
        else:  # pragma: no cover - Python < 3.10.12 without extraction filters
            tf.extractall(dest, members=members)  # noqa: S202 - members validated above

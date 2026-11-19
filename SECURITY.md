# Security Policy & Model

eSim ToolHub manages external EDA binaries and invokes system package managers.
Because installation touches the host environment, every trust boundary is enforced
explicitly in code.

## Implemented Controls

1. **No shell execution**: All external commands pass through
   `esim_toolhub.core.runner.SubprocessRunner` using argument sequences with
   `shell=False`, `stdin=DEVNULL`, and mandatory timeouts. Passing a shell string
   raises `TypeError`.
2. **Package identifier validation**: Every package name/ID read from `tools.yaml`
   is validated against `^[A-Za-z0-9][A-Za-z0-9.+_@-]{0,127}$` before reaching any
   package manager, preventing argument injection (such as leading `-` flags).
3. **HTTPS & exact-host allowlisting**: Direct archive downloads are restricted to
   `https://` URLs whose hostname matches the exact allowlist in `platforms.yaml`.
   A custom `HTTPRedirectHandler` re-validates every redirect hop. Embedded URL
   credentials (`https://user:pass@...`) are rejected.
4. **Checksum verification**: Archive installs require a valid 64-hex SHA256 digest
   and verify it via constant-time comparison (`hmac.compare_digest`). When
   `verify_checksums: true` (the default), archives lacking a SHA256 digest are
   blocked rather than silently trusted.
5. **Streaming size limits & temporary directories**: Downloads check both
   `Content-Length` and streamed byte counts against `download_max_mb`, writing
   into an isolated temporary file cleaned up on error.
6. **Safe archive extraction**: `esim_toolhub.security.archive.safe_extract` blocks
   path traversal (`..`), absolute paths, drive letters, zip symlinks, tar links
   escaping the destination, device/FIFO entries, excessive member counts, and
   uncompressed size bombs.
7. **Clear privilege boundaries**:
   - Inspection (`status`, `check`, `doctor`, `list`, `update --check-only`) never
     needs elevated privileges.
   - Windows `winget` runs per-user; Chocolatey blocks cleanly with instructions
     when not running in an elevated terminal.
   - Linux package managers prefix `sudo -n` when non-root and block cleanly if
     `sudo` is unavailable.
   - ToolHub never adds third-party apt PPAs or silently edits system PATH / shell
     startup scripts.
8. **Log redaction**: `RedactingFilter` masks bearer tokens, `password=`/`token=`/
   `api_key=` values, GitHub tokens, and URL credentials before JSON log entries
   are written to disk. ToolHub stores no credentials.

## Reporting a Vulnerability

This repository is an independent screening prototype. Please open a minimal
private report or GitHub Security Advisory rather than posting exploit payloads
in public issues.

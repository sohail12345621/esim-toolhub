# Contributing to eSim ToolHub

## Development Setup

```bash
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1

pip install -e ".[dev]"
```

## Verification Checks

Run all checks before opening a pull request:

```bash
pytest
ruff check src tests
mypy src/esim_toolhub
```

Tests must never install real software or make live network calls; mock
`CommandRunner`, `Downloader`, and filesystem state using `tests/conftest.py`.

## Adding a New Tool

1. Add a declarative entry under `tools:` in `src/esim_toolhub/resources/tools.yaml`
   (executables, `version_args`, `version_pattern`, `minimum_version`, `search_paths`,
   `install` methods, optional `depends_on` and `host_requirements`).
2. If the tool requires an archive URL on a new trusted host, add that host to
   `trusted_hosts` in `src/esim_toolhub/resources/platforms.yaml` and include the
   release SHA256 digest.
3. Only if the tool has platform/CLI quirks that YAML cannot express (e.g. GUI-only
   fallback binaries), add an adapter in `src/esim_toolhub/tools/` subclassing
   `GenericToolAdapter` and register it in `tools/__init__.py`.
4. Add unit tests covering version extraction, status evaluation, and dry-run planning.

## Coding Conventions

- Keep side effects behind injectable interfaces (`CommandRunner`, `Downloader`,
  `ExecutableLocator`, `EnvironmentManager`).
- Never use `subprocess.run(..., shell=True)`.
- Never report an installation as successful without running post-install verification.
- Keep commits small, focused, and conventional (`feat:`, `fix:`, `test:`, `docs:`, `ci:`).

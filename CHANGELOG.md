# Changelog

All notable changes to eSim ToolHub are documented in this file.

## [0.1.0] - 2026-11-19

### Added
- Declarative YAML tool & platform registry (`tools.yaml`, `platforms.yaml`) for
  Ngspice, KiCad, GHDL, Verilator, and OpenModelica with profiles
  (`minimal`, `analog`, `digital`, `full`).
- Cross-platform system detection (OS family, Windows 10/11 build detection,
  Linux `/etc/os-release` & WSL, architecture normalization, Python version,
  PATH auditing, package-manager discovery).
- Executable discovery (PATH, managed directories, natural-sorted search globs)
  and tolerant numeric version parsing (`9.0`, `v9.0.1`, `ngspice-44`, `5.028`).
- Tool-specific adapters for KiCad (avoiding GUI probes) and Ngspice (preferring
  `ngspice_con.exe` on Windows).
- Dependency checker (`MISSING`, `INSTALLED`, `OUTDATED`, `INCOMPATIBLE`,
  `BROKEN`, `UNKNOWN`), topological dependency resolver with cycle detection,
  GHDL `mcode` variant warnings, host prerequisite checks, and `doctor` diagnostics.
- Cross-platform installer adapters (`WindowsInstaller`, `LinuxInstaller`,
  experimental `MacOSInstaller`) with plan-first `--dry-run`, privilege checks,
  verified HTTPS/SHA256 archive extraction, and mandatory post-install verification.
- Persistent YAML configuration (`ConfigManager`), managed environment tracking
  with copy-paste PATH snippets (`EnvironmentManager`), safe update checker
  (`UpdateChecker`), and redacted JSON-lines logging.
- Typer + Rich CLI with `--json` output and clearly labelled deterministic `demo` mode.
- 70 mocked unit and CLI tests, Ruff + Mypy configuration, and GitHub Actions CI.

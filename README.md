# eSim ToolHub

**Cross-Platform Automated Tool & Dependency Manager for the eSim EDA Ecosystem**

> **Note:** eSim ToolHub is an independent proof-of-concept developed as a screening-task
> prototype for the **FOSSEE / IIT Bombay eSim Internship**, designed for potential future
> integration with [eSim](https://github.com/FOSSEE/eSim). It is **not** an official FOSSEE
> release.

---

## Problem & Motivation

[eSim](https://esim.fossee.in/) integrates several external open-source EDA tools—**KiCad**
(schematic capture and PCB layout), **Ngspice** (SPICE simulation), **GHDL** (mixed-signal
VHDL via NGHDL), **Verilator** (Verilog/SystemVerilog via NgVeri), and **OpenModelica**
(Modelica conversion). Setting up and maintaining these tools across Windows and Linux
frequently fails due to:

- Divergent package ecosystems (`winget`, Chocolatey, `apt`, `dnf`, `pacman`, MSYS2, archives).
- Version skew against eSim requirements (e.g., KiCad >= 7, Verilator >= 5, GHDL `llvm`/`gcc`
  backend required by NGHDL instead of `mcode`).
- Missing PATH entries or host prerequisites (`gcc`, `g++`, `make`).
- Fragile installer scripts that report success without verifying the installed binary.

**eSim ToolHub** addresses this with a declarative, eSim-aware registry, a dependency &
health diagnostics engine, plan-first cross-platform installers, and a clean CLI with
machine-readable JSON output.

---

## Features

- **Declarative Tool Registry (`tools.yaml` / `platforms.yaml`)**: Add new tools without
  rewriting core logic.
- **eSim Workflow Profiles**: `minimal` (Ngspice), `analog` (+ KiCad), `digital`
  (+ GHDL, Verilator), and `full` (+ OpenModelica) with transitive dependency resolution.
- **Cross-Platform Detection**: Detects OS (including Windows 10 vs 11 build numbers, Linux
  `/etc/os-release`, WSL), architecture, Python version, available package managers, PATH
  hygiene, and installed tool versions (handling `9.0`, `v9.0.1`, `ngspice-44`, `5.028`).
- **Dependency Health Model**: Evaluates every tool into `INSTALLED`, `MISSING`, `OUTDATED`,
  `INCOMPATIBLE`, `BROKEN`, or `UNKNOWN`, plus variant checks (such as GHDL's `mcode`
  backend warning for NGHDL).
- **Plan-First Installation & `--dry-run`**: Generates a transparent step-by-step plan
  before executing anything, respects privilege boundaries, and **always verifies** the
  executable and version after installation.
- **Diagnostics (`doctor`)**: Audits OS, architecture, Python, package managers, PATH
  issues, tool health, host prerequisites, and writable directories.
- **Safe Update Checker**: Distinguishes `up-to-date`, `update-available`,
  `unsupported-update` (e.g., newer major releases beyond eSim's tested series),
  `not-installed`, and `unknown`. Never auto-replaces working installs without confirmation.
- **Machine-Readable Output**: `--json` flag on `system`, `list`, `status`, `check`, and
  `doctor` for future GUI or CI integration.

---

## Architecture

```text
User / eSim Frontend
        │
        ▼
  cli (Typer + Rich)
        │
        ▼
  core.manager.ToolHub
   ├── core.registry          (tools.yaml, platforms.yaml)
   ├── detection              (system, executable, version)
   ├── tools                  (per-tool quirk adapters: kicad, ngspice)
   ├── dependency             (checker, resolver, doctor)
   ├── installers             (Windows / Linux / experimental macOS + archive downloader)
   ├── configuration          (ConfigManager, EnvironmentManager)
   ├── update                 (UpdateChecker)
   ├── security               (URL allowlist, SHA256, safe archive extraction, redaction)
   └── logs                   (JSON-lines rotating log with secret redaction)
```

See [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/design.md](docs/design.md) for detailed
component responsibilities and Mermaid sequence diagrams.

---

## Supported Operating Systems

| OS | Status | Package Managers / Strategies |
|---|---|---|
| **Windows 10 / 11** | Supported | `winget` (user-level), Chocolatey (when elevated), verified ZIP archive, manual guidance |
| **Linux (Ubuntu / Debian / Fedora / Arch)** | Supported | `apt`, `dnf`, `pacman` (with `sudo -n` when non-root), verified `.tar.gz` archive, manual guidance |
| **macOS** | Experimental | Detection implemented; Homebrew & archive adapter implemented but **not validated on macOS hardware** (eSim does not officially support macOS) |

## Supported Tools & Profiles

| Tool | Role in eSim | Required | Min Version | Notes |
|---|---|---|---|---|
| **Ngspice** | Core analog/mixed-signal simulator | Yes | `>= 36` | Prefers `ngspice_con.exe` on Windows |
| **KiCad** | Schematic capture & PCB layout | Yes | `>= 7.0` | Tested up to 9.x; avoids probing GUI `kicad.exe` |
| **GHDL** | VHDL co-simulation (NGHDL) | Optional | `>= 3.0` | Warns if `mcode` backend is detected |
| **Verilator** | Verilog/SystemVerilog (NgVeri) | Optional | `>= 5.0` | Checks host `g++` & `make` on POSIX; manual MSYS2/WSL guidance on Windows |
| **OpenModelica** | Ngspice-to-Modelica simulation | Optional | `>= 1.20` | Included in `full` profile |

Profiles: `minimal` -> `analog` -> `digital` -> `full`.

---

## Installation

Requires **Python 3.10+**.

```bash
git clone <repository-url>
cd esim-toolhub
pip install -e .
```

For development (pytest, ruff, mypy):

```bash
pip install -e ".[dev]"
```

---

## CLI Usage

```bash
esim-toolhub --help
esim-toolhub --version
esim-toolhub system [--json]
esim-toolhub list [--json]
esim-toolhub status [--json]
esim-toolhub check [tool] [--json]
esim-toolhub doctor [--json]
esim-toolhub install <tool> [--dry-run] [--force] [--method <name>]
esim-toolhub install --profile analog --dry-run
esim-toolhub install-profile digital --dry-run
esim-toolhub uninstall <tool> [--dry-run] [--yes]
esim-toolhub update [tool] [--check-only] [--dry-run] [--online] [--yes]
esim-toolhub config [show | set <key> <value> [--dry-run] | set-path <tool> <dir> | unset-path <tool> | reset | env | path]
esim-toolhub logs [--tail 50] [--level INFO] [--path]
esim-toolhub demo
```

### Example Output (`esim-toolhub demo`)

```text
+-----------------------------------------------------------+
|                   eSim ToolHub  v0.1.0                    |
|      SIMULATED DEMO - Not your real host environment      |
+-----------------------------------------------------------+

SYSTEM
  OS            Ubuntu 24.04.2 LTS (DEMO)
  ARCH          x86_64
  Python        3.12.3

TOOLS
        Tool         Version    Status       Role
  +     Ngspice      44.0       Installed    required
  +     KiCad        9.0.1      Installed    required
  x     GHDL         -          Missing      optional
  !     Verilator    4.228      Outdated     optional

Compatibility: PASS   Required: 2/2   All tools: 2/4

eSim ToolHub Doctor

[PASS] Operating system supported - Ubuntu 24.04.2 LTS (DEMO)
[PASS] Architecture supported - x86_64
[PASS] Python supported - 3.12.3
[PASS] Package manager available - apt
[PASS] Ngspice detected - 44.0 at /usr/bin/ngspice
[PASS] KiCad detected - 9.0.1 at /usr/bin/kicad-cli
[WARN] GHDL missing (optional) - Install using ToolHub: esim-toolhub install ghdl
[WARN] Verilator outdated - 4.228 is older than required >= 5.0

Overall: OK WITH WARNINGS (0 failures, 2 warnings)
```

### Dry-Run Example (`esim-toolhub install --profile analog --dry-run`)

```text
DRY RUN - KiCad
  Platform:  Windows 11 (x86_64)
  Current:   Not installed
  Target:    10.0.8
  Method:    winget:KiCad.KiCad
  Actions:
    1. Install KiCad.KiCad via winget
       $ winget install --id KiCad.KiCad --exact --accept-package-agreements --accept-source-agreements --disable-interactivity
    2. Detect KiCad executable
    3. Verify KiCad version & compatibility
  No changes were made.
```

---

## Security Model

- All external commands run via `SubprocessRunner` with argument arrays (`shell=False`),
  closed `stdin`, and explicit timeouts.
- Package identifiers are validated to block argument injection.
- Direct downloads enforce HTTPS, exact-host allowlisting across redirects, streaming size
  limits, SHA256 verification, and safe archive extraction (blocking path traversal,
  symlinks, devices, and size bombs).
- Structured JSON logs pass through `RedactingFilter` to strip tokens, passwords, and URL
  credentials.

Full details: [SECURITY.md](SECURITY.md).

---

## Testing & Code Quality

All tests mock subprocesses, network downloads, and host state; no test installs software.

```bash
pytest --cov=esim_toolhub
ruff check src tests
mypy src/esim_toolhub
```

---

## Limitations

- **Verilator on Windows** and **Ngspice `.7z` archives on Windows** have no native
  stdlib-extractable binary installer; ToolHub reports this honestly and provides explicit
  MSYS2 / Chocolatey / manual instructions rather than faking support.
- **Custom NGHDL/Ngspice source builds** (eSim's `nghdl-simulator` with XSPICE/IPC patches)
  are intentionally out of scope for this prototype; ToolHub manages standard upstream tools.
- **macOS** installation has not been tested on macOS hardware.
- **Ubuntu PPAs**: ToolHub intentionally does not add third-party apt PPAs automatically.

## Future Improvements & eSim Integration

- Optional PyQt6 status panel / eSim startup pre-flight hook consuming `ToolHub` or
  `esim-toolhub status --json`.
- Native `.7z` support (optional extra) for official Windows Ngspice archives.
- Integration helper for eSim's custom `nghdl-simulator` and IHP PDK scripts.
- Hardware validation on macOS (Apple Silicon & Intel).

---

## Contributing & License

See [CONTRIBUTING.md](CONTRIBUTING.md). Licensed under **GPL-3.0-or-later** ([LICENSE](LICENSE)).

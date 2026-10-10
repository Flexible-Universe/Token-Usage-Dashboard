# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning according to [SemVer](https://semver.org/).

## [Unreleased]

### Added

- The installer checks the minimum versions of Python, Node.js, `ccusage`,
  `rtk` and macOS, prints a version table and aborts with exit code 2 before
  it writes anything if a needed component is missing or too old.
- Support for Linux and Windows besides macOS: the export chain, the
  installer and the scheduled jobs run on all three systems.
- `install.py`, a cross-platform installer from the standard library. It
  sets up the jobs with launchd (macOS), systemd user timers with
  `Persistent=true` or, as a fallback, cron (Linux), and the Windows Task
  Scheduler (`StartWhenAvailable`, `pyw -3` or `pythonw.exe`). New options
  `--with-jobs`, `--no-jobs`, `--remove-jobs`, `--scheduler` and `--app-dir`.
- `install.cmd`, the starter for Windows.
- Release ZIPs per system. Installed
  from an unpacked release, `install.py` copies the application to a
  per-user directory, sets up the jobs by default, keeps an existing
  `config.toml` and writes `start-dashboard.sh` or `start-dashboard.cmd`.
  A ZIP for another system is refused.
- Options `--data-dir`, `--lookback-days`, `--ccusage-bin` and `--rtk-bin`
  for the export scripts, because `cmd.exe`, PowerShell and the Task
  Scheduler cannot put a variable in front of a command; the variable
  `CCUSAGE_SEARCH_DIRS`.
- `runtime` in `/api/data` with the interpreter of the server and whether it
  runs on Windows.
- A first export run at the end of the installation, so the dashboard has
  data before the first night (`--no-first-export` skips it).

### Changed

- The export chain is Python: `export/ccusage-export.py` (modes `daily`,
  `weekly`, `monthly`) and `export/rtk-export.py` with the shared module
  `export/exportlib.py`. Regression rules, logs, status files and
  environment variables are unchanged.
- `install.sh` is now a thin starter that finds Python 3.11+ and calls
  `install.py`. `--with-launchagents` remains as an alias of `--with-jobs`.
- The jobs carry the absolute paths of the interpreter, `ccusage` and `rtk`
  the installer found, so a job decides exactly as the installer did. `rtk`
  no longer has to be reachable through launchd's default `PATH`.
- The default data directory follows the platform: macOS
  `~/Library/Application Support/Claude-Code-Usage`, Linux
  `${XDG_DATA_HOME:-~/.local/share}/claude-code-usage`, Windows
  `%LOCALAPPDATA%\Claude-Code-Usage`. `config.toml` stores the path as an
  escaped TOML string.
- `RTK_SEARCH_DIRS` and `CCUSAGE_SEARCH_DIRS` are separated by the platform's
  path separator (colon, semicolon on Windows); the fixed search
  directories depend on the platform.
- The call that closes a weekly export gap names the interpreter and the
  options instead of environment variables, and is written for PowerShell
  on Windows.
- Copies of the old shell scripts in `<data>/bin` are reported as obsolete,
  not deleted.

### Removed

- `export/ccusage-export.sh`, `export/rtk-export.sh` and the launchd
  templates under `export/launchd/`.

## [1.0.0] - 2026-09-14

- First Release
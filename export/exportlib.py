# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Shared helpers of ccusage-export.py and rtk-export.py.

The export scripts run unattended from launchd, systemd, cron or the Windows
Task Scheduler. Each of those starts with its own, usually minimal
environment, so nothing here relies on the interactive shell: binaries are
looked up in fixed places as well, and every message also goes to a log file,
because under pythonw.exe there is no stderr at all.

This module lies next to the scripts in <data>/bin and is imported from
there; install.py copies it together with them.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"

LOG_KEEP_LINES = 2000


def default_data_dir() -> Path:
    """Platform default of the data directory.

    Must match loader.default_data_directory(); the scripts run from
    <data>/bin without the application next to them and cannot import it.
    tests/test_platform_paths.py keeps both in step.
    """
    home = Path.home()
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / "Claude-Code-Usage"
    if IS_MACOS:
        return home / "Library" / "Application Support" / "Claude-Code-Usage"
    base = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return Path(base) / "claude-code-usage"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _executable_names(name: str) -> list[str]:
    if not IS_WINDOWS:
        return [name]
    # npm installs ccusage as ccusage.cmd, cargo installs rtk as rtk.exe.
    exts = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
    return [name + ext.lower() for ext in exts if ext] + [name]


def _is_executable(path: Path) -> bool:
    return path.is_file() and (IS_WINDOWS or os.access(path, os.X_OK))


def _split_dirs(value: str) -> list[str]:
    return [part for part in value.split(os.pathsep) if part]


def ccusage_search_dirs() -> list[str]:
    """Fixed places where npm, nvm, Volta, bun or Homebrew put ccusage."""
    override = os.environ.get("CCUSAGE_SEARCH_DIRS")
    if override is not None:
        # An empty value deliberately means "no fixed directories" (tests).
        return _split_dirs(override)
    home = Path.home()
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        local = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return [str(Path(appdata) / "npm"), str(Path(local) / "pnpm"),
                str(Path(local) / "Volta" / "bin"), str(home / ".bun" / "bin")]
    dirs = sorted(glob.glob(str(home / ".nvm" / "versions" / "node" / "*" / "bin")),
                  reverse=True)
    dirs += [str(home / ".volta" / "bin"), str(home / ".bun" / "bin"),
             str(home / ".npm-global" / "bin"), str(home / ".local" / "bin")]
    if IS_MACOS:
        dirs += ["/opt/homebrew/bin", "/usr/local/bin"]
    else:
        dirs += ["/usr/local/bin", "/home/linuxbrew/.linuxbrew/bin", "/usr/bin"]
    return dirs


def rtk_search_dirs() -> list[str]:
    """Fixed places where Homebrew or cargo put rtk."""
    override = os.environ.get("RTK_SEARCH_DIRS")
    if override is not None:
        return _split_dirs(override)
    home = Path.home()
    cargo = str(home / ".cargo" / "bin")
    if IS_WINDOWS:
        return [cargo]
    if IS_MACOS:
        return ["/opt/homebrew/bin", "/usr/local/bin", cargo, str(home / ".local" / "bin")]
    return [cargo, str(home / ".local" / "bin"), "/usr/local/bin",
            "/home/linuxbrew/.linuxbrew/bin"]


def find_binary(name: str, env_var: str, search_dirs: list[str],
                explicit: str | None = None) -> str | None:
    """Option first, then the variable, then the fixed directories, then PATH.

    install.py pins the path it found as an option of every job. A pinned
    or named path that has become unusable (an nvm upgrade removes the old
    node directory) is passed over rather than trusted; the search decides.
    """
    for candidate in (explicit, os.environ.get(env_var)):
        if candidate and _is_executable(Path(candidate)):
            return candidate
    for directory in search_dirs:
        for candidate_name in _executable_names(name):
            candidate = Path(directory) / candidate_name
            if _is_executable(candidate):
                return str(candidate)
    return shutil.which(name)


def child_kwargs() -> dict:
    """Keep child processes from opening a console window under pythonw.exe."""
    if IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def helper(name: str) -> list[str]:
    """Command line of a helper script lying next to this module."""
    return [sys.executable, str(Path(__file__).resolve().parent / name)]


class RunLog:
    """Appends timestamped lines to one log file and trims it afterwards."""

    def __init__(self, path: Path):
        self.path = path

    def __call__(self, message: str) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}  {message}\n")

    def stream(self):
        return self.path.open("a", encoding="utf-8")

    def trim(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines(True)
        except OSError:
            return
        if len(lines) > LOG_KEEP_LINES:
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text("".join(lines[-LOG_KEEP_LINES:]), encoding="utf-8")
            os.replace(tmp, self.path)


def say(message: str) -> None:
    """stderr for a manual run; pythonw.exe has none."""
    if sys.stderr is not None:
        print(message, file=sys.stderr)


def write_status(log: RunLog, status_dir: Path, job: str, started: str,
                 exit_code: int, targets: list[str],
                 lookback_days: int | None = None) -> None:
    args = helper("export-status.py") + [
        "--dir", str(status_dir), "--job", job, "--started", started,
        "--finished", utc_stamp(), "--exit-code", str(exit_code)]
    if lookback_days is not None:
        args += ["--lookback-days", str(lookback_days)]
    for target in targets:
        args += ["--target", target]
    # A failing helper must not change the exit code of the run.
    try:
        with log.stream() as err:
            result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=err,
                                    **child_kwargs())
        ok = result.returncode == 0
    except OSError:
        ok = False
    if not ok:
        log("FEHLER: Status nicht geschrieben")

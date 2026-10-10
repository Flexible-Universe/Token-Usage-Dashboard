#!/usr/bin/env python3
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Exports ccusage data for the dashboard.

    ccusage-export.py daily     rewrite the current and the previous month
    ccusage-export.py weekly    archive blocks and sessions (MANDATORY, see below)
    ccusage-export.py monthly   freeze the completed previous month

Options: --data-dir PATH (default CCUSAGE_DATA_DIR, then the platform
default), --lookback-days N (default CCUSAGE_LOOKBACK_DAYS, then 14) and
--ccusage-bin PATH (before CCUSAGE_BIN and the search). The options exist
because cmd.exe, PowerShell and the Windows Task Scheduler cannot put a
variable in front of a command.

Blocks and sessions come from the JSONL files under ~/.claude, whose history
only reaches back about 31 days. If the weekly run fails for longer than a
month, that period is lost for good. Daily and project data can be
regenerated at any time.

Runs on macOS, Linux and Windows; the date arithmetic is Python's, not that
of a particular date(1).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exportlib  # noqa: E402

DEFAULT_LOOKBACK_DAYS = 14   # overlap: a missed run heals itself
REGRESSION = 3               # exit code of ccusage-check.py for a regression
MODES = ("daily", "weekly", "monthly")


def compact(day: date) -> str:
    return day.strftime("%Y%m%d")


class Exporter:
    """One run: writes targets atomically and only after they were checked.

    Two dangers are caught:
      1. An aborted or empty run must not overwrite a good file.
      2. REGRESSION: an export holding less than the existing file would
         delete data. It is rejected. CCUSAGE_ALLOW_SHRINK=1 allows it.

    How a regression is judged depends on the policy:

      strict  A regression is an error. For the current month, which can
              only grow; if it shrinks, something is wrong.
      merge   The export is layered onto the existing file instead of
              replacing it. For the rolling weekly window, whose start moves
              on with every run and would otherwise take the day that fell
              out with it. The file can only grow.
      freeze  A regression means the archive is more complete than what
              ccusage still delivers today. The file stays, the run counts
              as successful. For completed previous months.
    """

    def __init__(self, ccusage: str, data_dir: Path, log: exportlib.RunLog, env: dict):
        self.ccusage = ccusage
        self.data_dir = data_dir
        self.log = log
        self.env = env
        self.targets: list[str] = []

    def _run(self, args: list[str], stdout) -> subprocess.CompletedProcess:
        with self.log.stream() as err:
            return subprocess.run(args, stdout=stdout, stderr=err, env=self.env,
                                  **exportlib.child_kwargs())

    def _record(self, rel: str, result: str) -> None:
        self.targets.append(f"{rel}={result}")

    def export(self, policy: str, target: Path, *args: str) -> bool:
        label = f"{target.parent.name}/{target.name}"
        # The status names the path relative to the data directory, whatever
        # the directory is called.
        rel = target.relative_to(self.data_dir).as_posix()
        tmp = merged = None
        try:
            try:
                fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".")
                os.close(fd)
            except OSError:
                tmp = None
                self.log(f"FEHLER: temporaere Datei fuer {label} nicht angelegt -> {label} unveraendert")
                self._record(rel, "failed")
                return False

            try:
                with open(tmp, "wb") as out:
                    ok = self._run([self.ccusage, *args], out).returncode == 0
            except OSError:
                ok = False
            if not ok:
                self.log(f"FEHLER: 'ccusage {' '.join(args)}' schlug fehl -> {label} unveraendert")
                self._record(rel, "failed")
                return False

            if policy == "merge":
                try:
                    fd, merged = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".")
                    os.close(fd)
                except OSError:
                    merged = None
                    self.log(f"FEHLER: temporaere Datei fuer {label} nicht angelegt -> {label} unveraendert")
                    self._record(rel, "failed")
                    return False
                result = self._run(exportlib.helper("ccusage-merge.py")
                                   + [tmp, str(target), merged], subprocess.PIPE)
                if result.returncode != 0:
                    self.log(f"ABBRUCH: Zusammenfuehren fehlgeschlagen -> {label} unveraendert")
                    self._record(rel, "failed")
                    return False
                self.log(f"MERGE {label}  ({result.stdout.decode('utf-8', 'replace').strip()})")
                try:
                    os.replace(merged, tmp)
                except OSError:
                    self.log(f"ABBRUCH: Zusammengefuehrte Datei nicht uebernommen -> {label} unveraendert")
                    self._record(rel, "failed")
                    return False
                merged = None

            check = self._run(exportlib.helper("ccusage-check.py") + [tmp, str(target)],
                              subprocess.PIPE)
            if check.returncode == REGRESSION and policy == "freeze":
                self.log(f"EINGEFROREN: {label} unveraendert, das Archiv ist vollstaendiger")
                self._record(rel, "frozen")
                return True
            if check.returncode != 0:
                self.log(f"ABBRUCH: {label} unveraendert")
                self._record(rel, "aborted")
                return False
            verdict = check.stdout.decode("utf-8", "replace").strip()

            size = os.path.getsize(tmp)
            # mkstemp creates 0600; the other data files are 0644.
            if not exportlib.IS_WINDOWS:
                os.chmod(tmp, 0o644)
            try:
                os.replace(tmp, target)
            except OSError:
                self.log(f"FEHLER: {label} nicht ersetzt")
                self._record(rel, "failed")
                return False
            tmp = None
            self.log(f"OK   {label}  {size} Bytes  ({verdict})  [{' '.join(args)}]")
            self._record(rel, "ok")
            return True
        finally:
            for leftover in (tmp, merged):
                if leftover:
                    try:
                        os.unlink(leftover)
                    except OSError:
                        pass


def run_mode(mode: str, exporter: Exporter, data_dir: Path, today: date,
             lookback_days: int) -> bool:
    month_start = today.replace(day=1)
    prev_last = month_start - timedelta(days=1)
    prev_first = prev_last.replace(day=1)
    cur_month = today.strftime("%Y-%m")
    prev_month = prev_first.strftime("%Y-%m")
    iso = today.isocalendar()
    iso_week = f"{iso[0]}-W{iso[1]:02d}"
    since = today - timedelta(days=lookback_days)

    ok = True
    if mode == "daily":
        # The previous month is added during the first three days, so that
        # activity after midnight on the 1st is not missing from the frozen file.
        ok &= exporter.export("strict", data_dir / f"{cur_month}.json",
                              "daily", "--json", "--by-agent", "-s", month_start.isoformat())
        ok &= exporter.export("strict", data_dir / "projects" / f"{cur_month}.json",
                              "claude", "daily", "--json", "-i", "-s", compact(month_start))
        if today.day <= 3:
            ok &= _freeze_previous(exporter, data_dir, prev_month, prev_first, prev_last)
    elif mode == "weekly":
        # Rolling window with overlap; the reader deduplicates by blocks[].id
        # and sessionId, the later export wins.
        ok &= exporter.export("merge", data_dir / "blocks" / f"{iso_week}.json",
                              "blocks", "--json", "-s", compact(since))
        ok &= exporter.export("merge", data_dir / "sessions" / f"{iso_week}.json",
                              "claude", "session", "--json", "-s", compact(since))
    else:
        ok &= _freeze_previous(exporter, data_dir, prev_month, prev_first, prev_last)
    return bool(ok)


def _freeze_previous(exporter: Exporter, data_dir: Path, prev_month: str,
                     prev_first: date, prev_last: date) -> bool:
    ok = exporter.export("freeze", data_dir / f"{prev_month}.json",
                         "daily", "--json", "--by-agent",
                         "-s", prev_first.isoformat(), "-u", prev_last.isoformat())
    ok &= exporter.export("freeze", data_dir / "projects" / f"{prev_month}.json",
                          "claude", "daily", "--json", "-i",
                          "-s", compact(prev_first), "-u", compact(prev_last))
    return bool(ok)


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="ccusage-export.py",
                                     description="Exportiert ccusage-Daten fuer das Dashboard.")
    parser.add_argument("mode", choices=MODES)
    parser.add_argument("--data-dir")
    parser.add_argument("--lookback-days", type=int)
    parser.add_argument("--ccusage-bin")
    args = parser.parse_args(argv)
    if args.lookback_days is None:
        raw = os.environ.get("CCUSAGE_LOOKBACK_DAYS", "")
        try:
            args.lookback_days = int(raw) if raw else DEFAULT_LOOKBACK_DAYS
        except ValueError:
            parser.error(f"CCUSAGE_LOOKBACK_DAYS ist keine Zahl: {raw}")
    if args.lookback_days < 1:
        parser.error("--lookback-days muss mindestens 1 sein")
    return args


def main(argv=None, today: date | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    data_dir = Path(args.data_dir or os.environ.get("CCUSAGE_DATA_DIR")
                    or exportlib.default_data_dir()).expanduser()
    for sub in ("projects", "blocks", "sessions", "logs", "status"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    log = exportlib.RunLog(data_dir / "logs" / f"{args.mode}.log")

    # From here on every run leaves a status file, an abort without ccusage
    # included. An invalid mode never gets here: there would be no job the
    # status could belong to.
    started = exportlib.utc_stamp()
    exporter = None
    code = 1
    try:
        ccusage = exportlib.find_binary("ccusage", "CCUSAGE_BIN",
                                        exportlib.ccusage_search_dirs(), args.ccusage_bin)
        if ccusage is None:
            log("FEHLER: ccusage nicht gefunden. CCUSAGE_BIN setzen.")
            exportlib.say("ccusage nicht gefunden. Setze CCUSAGE_BIN auf den Pfad der Binary.")
            return code

        # ccusage starts with '#!/usr/bin/env node' (or calls node from its
        # .cmd wrapper). Schedulers start without the nvm path; node lies in
        # the same directory as ccusage.
        env = dict(os.environ)
        env["PATH"] = os.path.dirname(ccusage) + os.pathsep + env.get("PATH", "")
        exporter = Exporter(ccusage, data_dir, log, env)
        log(f"--- Start ({args.mode}), ccusage={ccusage}")
        ok = run_mode(args.mode, exporter, data_dir, today or date.today(),
                      args.lookback_days)
        code = 0 if ok else 1
        log.trim()
        log(f"--- Ende ({args.mode}), Status {code}")
        return code
    finally:
        exportlib.write_status(
            log, data_dir / "status", args.mode, started, code,
            exporter.targets if exporter else [],
            args.lookback_days if args.mode == "weekly" else None)


if __name__ == "__main__":
    sys.exit(main())

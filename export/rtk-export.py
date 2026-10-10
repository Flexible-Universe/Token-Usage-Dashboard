#!/usr/bin/env python3
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Exports the savings statistics of the rtk proxy for the dashboard.

    rtk-export.py [--data-dir PATH] [--rtk-bin PATH]

rtk ("Rust Token Killer") records token savings per day (command: rtk gain).
Unlike ccusage one run is enough: there is no rolling weekly window and
nothing to archive that is not in the same monthly file anyway.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exportlib  # noqa: E402


def _probe_is_json(raw: bytes) -> bool:
    try:
        json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    return True


def _has_daily(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return isinstance(data, dict) and isinstance(data.get("daily"), list)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="rtk-export.py",
                                     description="Exportiert die rtk-Ersparnis fuer das Dashboard.")
    parser.add_argument("--data-dir")
    parser.add_argument("--rtk-bin")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    data_dir = Path(args.data_dir or os.environ.get("RTK_DATA_DIR")
                    or exportlib.default_data_dir()).expanduser()
    target_dir = data_dir / "rtk"
    status_dir = data_dir / "status"
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    status_dir.mkdir(parents=True, exist_ok=True)
    log = exportlib.RunLog(data_dir / "logs" / "rtk.log")

    # Every run leaves a status file, the abort before rtk was found
    # included. The single target stays empty until rtk is found.
    started = exportlib.utc_stamp()
    result = ""
    code = 1
    gain_tmp = None
    try:
        log("--- Start")
        # The name 'rtk' collides with 'reachingforthejack/rtk' (Rust Type
        # Kit). Without the JSON probe a mix-up only shows up in the
        # dashboard as an empty tab.
        rtk = exportlib.find_binary("rtk", "RTK_BIN", exportlib.rtk_search_dirs(),
                                    args.rtk_bin)
        if rtk is None:
            log("ABBRUCH: rtk nicht gefunden. RTK_BIN setzen. rtk/ unveraendert")
            exportlib.say("rtk nicht gefunden. Setze RTK_BIN auf den Pfad der Binary.")
            return code
        result = "failed"

        with log.stream() as err:
            try:
                probe = subprocess.run([rtk, "gain", "--format", "json"],
                                       stdout=subprocess.PIPE, stderr=err,
                                       **exportlib.child_kwargs())
                probe_ok = probe.returncode == 0 and _probe_is_json(probe.stdout)
            except OSError:
                probe_ok = False
        if not probe_ok:
            log(f"ABBRUCH: rtk nicht gefunden oder liefert kein JSON ({rtk}). rtk/ unveraendert")
            exportlib.say(f"rtk liefert kein JSON: {rtk}")
            return code

        # rtk/ only comes into being after the probe: an existing directory
        # makes the dashboard expect rtk exports, and a host without rtk
        # should not.
        target_dir.mkdir(exist_ok=True)
        fd, gain_tmp = tempfile.mkstemp(dir=target_dir, prefix="gain.")
        with os.fdopen(fd, "wb") as out, log.stream() as err:
            try:
                gain_ok = subprocess.run([rtk, "gain", "--all", "--format", "json"],
                                         stdout=out, stderr=err,
                                         **exportlib.child_kwargs()).returncode == 0
            except OSError:
                gain_ok = False
        if not gain_ok:
            log("ABBRUCH: 'rtk gain --all --format json' schlug fehl. rtk/ unveraendert")
            exportlib.say("'rtk gain --all --format json' schlug fehl.")
            return code
        if not _has_daily(gain_tmp):
            log("ABBRUCH: Ausgabe ist kein gueltiges JSON oder hat keinen Schluessel 'daily'. rtk/ unveraendert")
            exportlib.say("Ausgabe von 'rtk gain --all --format json' ist kein gueltiges JSON "
                          "oder hat keinen Schluessel 'daily'.")
            return code

        with log.stream() as err:
            merge = subprocess.run(exportlib.helper("rtk-merge.py") + [gain_tmp, str(target_dir)],
                                   stdout=subprocess.PIPE, stderr=err,
                                   **exportlib.child_kwargs())
        if merge.returncode != 0:
            log(f"ABBRUCH: rtk-merge.py endete mit Exitcode {merge.returncode}. rtk/ unveraendert")
            result = "aborted"
            return code

        result = "ok"
        code = 0
        log(f"OK   {merge.stdout.decode('utf-8', 'replace').strip()}")
        log("--- Ende")
        log.trim()
        return code
    finally:
        if gain_tmp:
            try:
                os.unlink(gain_tmp)
            except OSError:
                pass
        exportlib.write_status(log, status_dir, "rtk", started, code,
                               [f"rtk/={result}"] if result else [])


if __name__ == "__main__":
    sys.exit(main())

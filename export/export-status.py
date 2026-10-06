#!/usr/bin/env python3
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Schreibt die Statusdateien eines Exportlaufs.

    export-status.py --dir <status-verzeichnis> --job daily|weekly|monthly|rtk
                     --started <iso-utc> --finished <iso-utc> --exit-code <n>
                     [--lookback-days <n>] [--target <datei>=<ergebnis>]...

Schreibt immer <job>.last.json und bei Exitcode 0 zusaetzlich <job>.ok.json mit
identischem Inhalt. Die Entscheidung ueber die ok-Datei faellt hier und nicht
in Bash, damit sie an genau einer Stelle steht. Ungueltige Eingaben enden mit
Exitcode 2, bevor irgendetwas geschrieben wird.
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime

JOBS = ("daily", "weekly", "monthly", "rtk")
RESULTS = ("ok", "frozen", "aborted", "failed")
TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def timestamp(value):
    # Die Form ist streng, weil das Dashboard keine andere akzeptiert; der
    # Parse-Versuch faengt unmoegliche Daten wie den 45. Tag ab.
    if not TIMESTAMP_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            f"Zeitstempel '{value}' nicht in der Form YYYY-MM-DDTHH:MM:SSZ")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise argparse.ArgumentTypeError(f"Zeitstempel '{value}' ist kein gueltiges Datum")
    return value


def lookback_days(value):
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError(f"'{value}' ist keine ganze Zahl ab 1")
    return number


def target(value):
    # Am letzten '=' trennen: Dateinamen duerfen '=' enthalten, Ergebnisse nie.
    file, _, result = value.rpartition("=")
    if not file:
        raise argparse.ArgumentTypeError(f"Ziel '{value}' hat nicht die Form <datei>=<ergebnis>")
    if result not in RESULTS:
        raise argparse.ArgumentTypeError(
            f"Ergebnis '{result}' ungueltig, erlaubt: {', '.join(RESULTS)}")
    return {"file": file, "result": result}


def parse(argv):
    parser = argparse.ArgumentParser(prog="export-status.py", description=__doc__.splitlines()[0])
    parser.add_argument("--dir", required=True)
    parser.add_argument("--job", required=True, choices=JOBS)
    parser.add_argument("--started", required=True, type=timestamp)
    parser.add_argument("--finished", required=True, type=timestamp)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--lookback-days", type=lookback_days)
    parser.add_argument("--target", action="append", default=[], type=target)
    args = parser.parse_args(argv)
    if args.job == "weekly" and args.lookback_days is None:
        parser.error("--lookback-days ist beim Job weekly Pflicht")
    if args.job != "weekly" and args.lookback_days is not None:
        parser.error("--lookback-days ist nur beim Job weekly erlaubt")
    return args


def write_all(directory, files):
    """Schreibt alle Dateien ueber temporaere Dateien; Reste werden immer entfernt."""
    os.makedirs(directory, exist_ok=True)
    temps = []
    try:
        for name, text in files:
            # Temporaer im selben Verzeichnis, sonst waere os.replace nicht atomar.
            fd, temp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
            temps.append((temp, name))
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
        while temps:
            temp, name = temps[0]
            os.replace(temp, os.path.join(directory, name))
            temps.pop(0)
    finally:
        for temp, _ in temps:
            try:
                os.unlink(temp)
            except OSError:
                pass


def main(argv=None):
    args = parse(sys.argv[1:] if argv is None else argv)
    content = {
        "schema": 1,
        "job": args.job,
        "startedAt": args.started,
        "finishedAt": args.finished,
        "exitCode": args.exit_code,
    }
    if args.lookback_days is not None:
        content["lookbackDays"] = args.lookback_days
    content["targets"] = args.target
    text = json.dumps(content, indent=2) + "\n"

    files = [(f"{args.job}.last.json", text)]
    if args.exit_code == 0:
        files.append((f"{args.job}.ok.json", text))
    try:
        write_all(args.dir, files)
    except OSError as error:
        sys.exit(f"Status nicht geschrieben: {error}")


if __name__ == "__main__":
    main()

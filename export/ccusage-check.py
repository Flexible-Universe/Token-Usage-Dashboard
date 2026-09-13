#!/usr/bin/env python3
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Prueft einen frischen ccusage-Export, bevor er eine bestehende Datei ersetzt.

    ccusage-check.py <neu.json> <bestehend.json>

Beendet sich mit 0, wenn der Export uebernommen werden darf, und schreibt eine
kurze Bilanz nach stdout. Andernfalls mit Begruendung auf stderr:

    1  Export unbrauchbar (kaputtes JSON, keine Datensaetze)
    3  RUECKSCHRITT -- der Export enthaelt weniger als die bestehende Datei

Die Trennung erlaubt dem Aufrufer, einen Rueckschritt je nach Lauf anders zu
bewerten: der Monatslauf betrachtet ihn als eingefrorenen Zeitraum und damit
als Erfolg, der Tageslauf weiterhin als Fehler.
"""
import json
import os
import sys

TOLERANZ = 0.999  # Rundungsdifferenzen zwischen ccusage-Laeufen zulassen
RUECKSCHRITT = 3  # eigener Exit-Code, siehe Modulkopf


def bilanz(pfad):
    """Liefert (Anzahl Datensaetze, Kostensumme) fuer jedes ccusage-Schema."""
    with open(pfad, encoding="utf-8") as fh:
        daten = json.load(fh)
    if not isinstance(daten, dict):
        raise ValueError("Wurzelelement ist kein Objekt")

    zeilen = []
    for schluessel in ("daily", "weekly", "monthly", "session", "sessions", "blocks"):
        wert = daten.get(schluessel)
        if isinstance(wert, list):
            zeilen.extend(wert)
    projekte = daten.get("projects")
    if isinstance(projekte, dict):
        for eintraege in projekte.values():
            if isinstance(eintraege, list):
                zeilen.extend(eintraege)

    if not zeilen:
        raise ValueError("keine Datensaetze enthalten")

    kosten = 0.0
    for z in zeilen:
        if not isinstance(z, dict):
            continue
        if z.get("isGap"):
            continue
        wert = z.get("totalCost", z.get("costUSD", 0)) or 0
        try:
            kosten += float(wert)
        except (TypeError, ValueError):
            pass
    return len(zeilen), kosten


def main():
    if len(sys.argv) != 3:
        sys.exit("Aufruf: ccusage-check.py <neu.json> <bestehend.json>")
    neu_pfad, alt_pfad = sys.argv[1], sys.argv[2]

    try:
        n_zeilen, n_kosten = bilanz(neu_pfad)
    except (ValueError, json.JSONDecodeError, OSError) as fehler:
        sys.exit(f"Export unbrauchbar: {fehler}")

    if not os.path.exists(alt_pfad):
        print(f"neu, {n_zeilen} Datensaetze, {n_kosten:.2f} USD")
        return

    try:
        a_zeilen, a_kosten = bilanz(alt_pfad)
    except (ValueError, json.JSONDecodeError, OSError):
        print(f"ersetzt unlesbare Datei, {n_zeilen} Datensaetze, {n_kosten:.2f} USD")
        return

    if os.environ.get("CCUSAGE_ALLOW_SHRINK") == "1":
        print(f"Schrumpfen erlaubt, {a_zeilen}->{n_zeilen} Datensaetze")
        return

    if n_zeilen < a_zeilen or n_kosten < a_kosten * TOLERANZ:
        print(
            "RUECKSCHRITT: Export hat {} Datensaetze / {:.2f} USD, bestehende "
            "Datei {} / {:.2f}. Entweder sind die JSONL-Quellen fuer diesen "
            "Zeitraum abgeschnitten, oder der Zeitraum reicht ueber das "
            "Exportfenster hinaus. Mit CCUSAGE_ALLOW_SHRINK=1 bewusst "
            "ueberschreiben.".format(n_zeilen, n_kosten, a_zeilen, a_kosten),
            file=sys.stderr,
        )
        sys.exit(RUECKSCHRITT)

    print(
        f"{a_zeilen}->{n_zeilen} Datensaetze, "
        f"{a_kosten:.2f}->{n_kosten:.2f} USD"
    )


if __name__ == "__main__":
    main()

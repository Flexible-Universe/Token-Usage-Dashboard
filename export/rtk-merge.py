#!/usr/bin/env python3
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Fuehrt einen frischen rtk-gain-Export in die monatlichen Archivdateien ein.

    rtk-merge.py <gain.json> <zielverzeichnis>

``gain.json`` ist die Ausgabe von ``rtk gain --all --format json``. Nur der
Schluessel ``daily`` wird verwendet: er wird nach Monat gruppiert und je Monat
mit einer bestehenden Datei ``<zielverzeichnis>/YYYY-MM.json`` zusammengefuehrt.
Dedupliziert wird ueber ``date``; bei gleichem Datum gewinnt der neue Export.
Ein Tag, der nur in der bestehenden Datei steht, bleibt erhalten. Damit kann
eine Monatsdatei nur wachsen, egal ob ``history.db`` irgendwann gekuerzt wird
oder ein Lauf ausfaellt.

Anders als ``ccusage-merge.py`` (Listenschluessel ``blocks``/``sessions``,
kein Aufteilen nach Monat) kennt dieser Helfer nur das rtk-Schema mit dem
Listenschluessel ``daily`` und schreibt das Ergebnis unter dem Schluessel
``days`` in je eine Datei pro Monat.

Unbekannte Struktur -- kein ``daily``, ``daily`` keine Liste, oder eine Zeile
ohne ``date`` -- ist ein Fehler mit Exitcode ungleich null. Es wird nie still
durchgelaufen und nie eine bestehende Datei veraendert, wenn ein Fehler
auftritt.

Geschrieben wird je Monat ueber ``tempfile`` im Zielverzeichnis und
``os.replace``.
"""
import json
import os
import sys
import tempfile


def lade_export(pfad):
    with open(pfad, encoding="utf-8") as fh:
        daten = json.load(fh)
    if not isinstance(daten, dict):
        raise ValueError("Wurzelelement ist kein Objekt")
    tage = daten.get("daily")
    if not isinstance(tage, list):
        raise ValueError("kein Schluessel 'daily' mit einer Liste")
    for zeile in tage:
        if not isinstance(zeile, dict) or not zeile.get("date"):
            raise ValueError("Zeile in 'daily' ohne 'date'")
    return tage


def gruppiere_nach_monat(tage):
    nach_monat = {}
    for zeile in tage:
        monat = zeile["date"][:7]
        nach_monat.setdefault(monat, []).append(zeile)
    return nach_monat


def lade_bestehend(pfad):
    if not os.path.exists(pfad):
        return []
    with open(pfad, encoding="utf-8") as fh:
        daten = json.load(fh)
    tage = daten.get("days") if isinstance(daten, dict) else None
    return tage if isinstance(tage, list) else []


def zusammenfuehren(alte_tage, neue_tage):
    """Bestehende Tage zuerst, der neue Export ueberschreibt gleiche Daten."""
    nach_datum = {}
    for zeile in list(alte_tage) + list(neue_tage):
        if isinstance(zeile, dict) and zeile.get("date"):
            nach_datum[zeile["date"]] = zeile
    return [nach_datum[datum] for datum in sorted(nach_datum)]


def schreibe_monat(zielverzeichnis, monat, tage):
    ziel = os.path.join(zielverzeichnis, f"{monat}.json")
    fd, tmp = tempfile.mkstemp(dir=zielverzeichnis, prefix=f"{monat}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"days": tage}, fh, ensure_ascii=False)
        os.chmod(tmp, 0o644)  # tempfile.mkstemp legt mit 0600 an, die anderen Datendateien sind 0644
        os.replace(tmp, ziel)
    except BaseException:
        os.unlink(tmp)
        raise


def main():
    if len(sys.argv) != 3:
        sys.exit("Aufruf: rtk-merge.py <gain.json> <zielverzeichnis>")
    gain_pfad, zielverzeichnis = sys.argv[1], sys.argv[2]

    try:
        neue_tage = lade_export(gain_pfad)
    except (ValueError, json.JSONDecodeError, OSError) as fehler:
        sys.exit(f"Export unbrauchbar: {fehler}")

    os.makedirs(zielverzeichnis, exist_ok=True)
    nach_monat = gruppiere_nach_monat(neue_tage)

    # Lese-/Mischphase: erst wenn jede bestehende Monatsdatei gelesen und
    # jeder Monat fertig gemischt ist, beginnt die Schreibphase. So bricht
    # ein kaputter spaeterer Monat den Lauf ab, bevor ein frueherer Monat
    # ueberhaupt angefasst wurde -- kein Monat wird geschrieben, waehrend ein
    # anderer noch scheitern kann.
    gemischt = {}
    bilanz = []
    for monat in sorted(nach_monat):
        ziel = os.path.join(zielverzeichnis, f"{monat}.json")
        try:
            alte_tage = lade_bestehend(ziel)
        except (ValueError, json.JSONDecodeError, OSError) as fehler:
            sys.exit(f"bestehende Datei {ziel} unlesbar: {fehler}")
        tage = zusammenfuehren(alte_tage, nach_monat[monat])
        gemischt[monat] = tage
        uebernommen = len(tage) - len(nach_monat[monat])
        bilanz.append(f"{monat}: {len(nach_monat[monat])} exportiert, "
                       f"{uebernommen} aus dem Archiv behalten, {len(tage)} gesamt")

    # Schreibphase: kein Rollback. Ein I/O-Fehler mitten in dieser Phase
    # (z. B. Plattenplatz voll) kann bereits geschriebene Monate dieses
    # Laufs nicht mehr zuruecknehmen -- das wird hier bewusst hingenommen,
    # da jede einzelne Datei weiterhin atomar per os.replace geschrieben wird
    # und daher nie in einem halb geschriebenen Zustand endet.
    for monat in sorted(gemischt):
        try:
            schreibe_monat(zielverzeichnis, monat, gemischt[monat])
        except OSError as fehler:
            sys.exit(f"Schreiben von {monat}.json fehlgeschlagen: {fehler}")

    print("; ".join(bilanz) if bilanz else "keine Tage im Export")


if __name__ == "__main__":
    main()

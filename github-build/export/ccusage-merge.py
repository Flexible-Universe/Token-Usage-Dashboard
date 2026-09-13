#!/usr/bin/env python3
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Mischt einen frischen ccusage-Export in eine bestehende Archivdatei.

    ccusage-merge.py <neu.json> <bestehend.json> <ausgabe.json>

Der Wochenlauf exportiert ein rollierendes Fenster von LOOKBACK_DAYS Tagen.
Bei jedem Lauf wandert dessen Anfang weiter, vorne faellt ein Tag heraus. Wird
das Ergebnis einfach geschrieben, verliert das Archiv genau diesen Tag. Deshalb
wird der Export ueber die bestehende Datei gelegt statt sie zu ersetzen.

Dedupliziert wird wie im Dashboard (sources.py): Blocks ueber ``id``, Sessions
ueber ``sessionId``, der spaetere Export gewinnt. Traegt die Datei ein Feld
``totals``, wird es aus den zusammengefuehrten Zeilen neu summiert -- sonst
meldet check_extras() eine Abweichung zwischen Zeilensumme und totals.
"""
import json
import sys

# Listenschluessel -> Feld, ueber das dedupliziert wird.
SCHEMATA = {
    "blocks": "id",
    "sessions": "sessionId",
    "session": "sessionId",
}

# Felder aus normalize_totals(); nur diese werden neu summiert.
TOTALS_FELDER = ("cacheCreationTokens", "cacheReadTokens", "inputTokens",
                 "outputTokens", "totalTokens", "totalCost")

# Erstes vorhandenes Feld bestimmt die Sortierung.
ZEITFELDER = ("startTime", "firstActivity", "lastActivity", "date")


def lade(pfad):
    with open(pfad, encoding="utf-8") as fh:
        daten = json.load(fh)
    if not isinstance(daten, dict):
        raise ValueError("Wurzelelement ist kein Objekt")
    return daten


def schema(daten):
    """Liefert (Listenschluessel, Dedupe-Feld) oder (None, None)."""
    for schluessel, feld in SCHEMATA.items():
        if isinstance(daten.get(schluessel), list):
            return schluessel, feld
    return None, None


def sortierschluessel(zeile):
    for feld in ZEITFELDER:
        wert = zeile.get(feld)
        if wert:
            return str(wert)
    return ""


def zusammenfuehren(alt_zeilen, neu_zeilen, feld):
    """Bestehende Zeilen zuerst, der neue Export ueberschreibt gleiche Schluessel."""
    nach_id = {}
    ohne_id = []
    for zeile in list(alt_zeilen) + list(neu_zeilen):
        if not isinstance(zeile, dict):
            continue
        schluessel = zeile.get(feld)
        if isinstance(schluessel, str) and schluessel:
            nach_id[schluessel] = zeile
        else:
            ohne_id.append(zeile)
    return sorted(nach_id.values(), key=sortierschluessel) + ohne_id


def summiere(zeilen):
    totals = {}
    for feld in TOTALS_FELDER:
        werte = []
        for zeile in zeilen:
            if not isinstance(zeile, dict) or zeile.get("isGap"):
                continue
            try:
                werte.append(float(zeile.get(feld, 0) or 0))
            except (TypeError, ValueError):
                continue
        summe = sum(werte)
        totals[feld] = summe if feld == "totalCost" else int(summe)
    return totals


def main():
    if len(sys.argv) != 4:
        sys.exit("Aufruf: ccusage-merge.py <neu.json> <bestehend.json> <ausgabe.json>")
    neu_pfad, alt_pfad, ziel_pfad = sys.argv[1:4]

    try:
        neu = lade(neu_pfad)
    except (ValueError, json.JSONDecodeError, OSError) as fehler:
        sys.exit(f"Export unbrauchbar: {fehler}")

    schluessel, feld = schema(neu)

    try:
        alt = lade(alt_pfad)
    except (ValueError, json.JSONDecodeError, OSError):
        # Kein oder kein brauchbares Archiv: der Export gilt unveraendert.
        alt = {}

    ergebnis = dict(neu)
    if schluessel:
        alt_zeilen = alt.get(schluessel) if isinstance(alt.get(schluessel), list) else []
        zeilen = zusammenfuehren(alt_zeilen, neu[schluessel], feld)
        ergebnis[schluessel] = zeilen
        if isinstance(neu.get("totals"), dict) or isinstance(alt.get("totals"), dict):
            ergebnis["totals"] = summiere(zeilen)
        uebernommen = len(zeilen) - len(neu[schluessel])
        print(f"{len(neu[schluessel])} exportiert, {uebernommen} aus dem Archiv "
              f"behalten, {len(zeilen)} gesamt")
    else:
        print("kein bekanntes Listenschema, Export unveraendert uebernommen")

    with open(ziel_pfad, "w", encoding="utf-8") as fh:
        json.dump(ergebnis, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()

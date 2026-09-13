#!/usr/bin/env python3
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Erzeugt Beispieldaten fuer die Vorfuehrung ohne eigene Nutzungsdaten.

    python3 tools/make-sample-data.py --out sample-data

Die Daten sind erfunden, aber nicht glatt: Sie tragen absichtlich die Faelle,
in denen das Dashboard etwas zu entscheiden hat - beide Monatsschemata,
fehlende Kalendertage, ungleiche Abdeckung der Zusatzquellen, Leerlaufbloecke
und eine Ueberlappung an der Wochengrenze. Ein Generator, der nur glatte
Reihen liefert, erzeugt eine falsche Sicherheit.

Alles ist relativ zu ``--today``, damit die Vorfuehrung nicht altert.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MODELLE = (
    # (Name, Gewicht, Kosten je 1 Mio. Output-Token in Dollar)
    ("claude-opus-5", 5, 75.0),
    ("claude-sonnet-5", 3, 15.0),
    ("claude-haiku-4-5", 2, 4.0),
    ("gpt-5-codex", 2, 10.0),
)

PROJEKTE = (
    "-home-devuser-projekte-alpha",
    "-home-devuser-projekte-beta-tool",
    "-home-devuser-ablage-export-daten",
)

TOKENFELDER = (
    "inputTokens",
    "outputTokens",
    "cacheCreationTokens",
    "cacheReadTokens",
)

# Zwei Monate im alten Schema, der Rest im neuen. Sonst laeuft der aeltere
# Lesepfad in der Vorfuehrung nie, obwohl das Dashboard ihn weiter traegt.
ALTE_MONATE = 2

# Die Projektdateien decken nur die juengsten Monate ab. Die ungleiche
# Abdeckung ist gewollt: der Zeitraumhinweis im Projektreiter soll erscheinen.
PROJEKTMONATE = 2


# --------------------------------------------------------------------------
# Bausteine
# --------------------------------------------------------------------------

def monatsspanne(heute: date, anzahl: int) -> list[str]:
    """Aufsteigende Liste ``YYYY-MM``, endend im Monat von ``heute``."""
    monate = []
    jahr, monat = heute.year, heute.month
    for _ in range(anzahl):
        monate.append(f"{jahr:04d}-{monat:02d}")
        monat -= 1
        if monat == 0:
            jahr, monat = jahr - 1, 12
    return list(reversed(monate))


def _vormonat(monat: str) -> str:
    jahr, nummer = int(monat[:4]), int(monat[5:7])
    nummer -= 1
    if nummer == 0:
        jahr, nummer = jahr - 1, 12
    return f"{jahr:04d}-{nummer:02d}"


def _monatsende(monat: str) -> date:
    jahr, nummer = int(monat[:4]), int(monat[5:7])
    if nummer == 12:
        return date(jahr, 12, 31)
    return date(jahr, nummer + 1, 1) - timedelta(days=1)


def tage_des_monats(monat: str, heute: date, rng: random.Random) -> list[str]:
    """ISO-Daten des Monats, mit bewusst ausgelassenen Kalendertagen.

    Die Luecken sind der Zweck: fehlende Tage sind im Dashboard keine Nullen,
    und das laesst sich nur an Daten zeigen, die welche haben.
    """
    erster = date(int(monat[:4]), int(monat[5:7]), 1)
    letzter = min(_monatsende(monat), heute)
    tage = []
    tag = erster
    while tag <= letzter:
        if rng.randrange(8) != 0:
            tage.append(tag.isoformat())
        tag += timedelta(days=1)
    return tage


def breakdown(modell: tuple[str, int, float], rng: random.Random) -> dict:
    """Ein ``modelBreakdowns``-Eintrag mit Kosten aus den Output-Token.

    Die Kosten haengen am Output, damit ``$ / 1 Mio. Output-Token`` im
    Dashboard eine Groesse zeigt, die zu den Token passt und nicht geraten
    wirkt.
    """
    name, _gewicht, satz = modell
    output = rng.randrange(20_000, 400_000)
    return {
        "modelName": name,
        "inputTokens": rng.randrange(20, 900),
        "outputTokens": output,
        "cacheCreationTokens": rng.randrange(100_000, 3_000_000),
        "cacheReadTokens": rng.randrange(1_000_000, 90_000_000),
        "cost": round(output / 1_000_000 * satz, 6),
    }


def _summen(breakdowns: list[dict]) -> dict:
    werte = {feld: sum(b[feld] for b in breakdowns) for feld in TOKENFELDER}
    werte["totalTokens"] = sum(werte[feld] for feld in TOKENFELDER)
    werte["totalCost"] = round(sum(b["cost"] for b in breakdowns), 6)
    return werte


def _agent(modellname: str) -> str:
    return "codex" if modellname.startswith("gpt-") else "claude"


def _modellwahl(rng: random.Random) -> list[tuple[str, int, float]]:
    anzahl = rng.choice((1, 2, 2, 3))
    gewichte = [m[1] for m in MODELLE]
    gewaehlt: list[tuple[str, int, float]] = []
    while len(gewaehlt) < anzahl:
        modell = rng.choices(MODELLE, weights=gewichte)[0]
        if modell not in gewaehlt:
            gewaehlt.append(modell)
    return gewaehlt


def tag_altes_schema(datum: str, breakdowns: list[dict]) -> dict:
    """Eintrag mit ``date``, wie ihn die aelteren Exportlaeufe schreiben."""
    tag = {"date": datum}
    tag.update(_summen(breakdowns))
    tag["modelsUsed"] = sorted({b["modelName"] for b in breakdowns})
    tag["modelBreakdowns"] = breakdowns
    return tag


def tag_neues_schema(datum: str, breakdowns: list[dict],
                     agentzeilen: list[dict]) -> dict:
    """Eintrag mit ``period``, ``agent``, ``metadata`` und ``agents``.

    ``agent`` ist immer ``"all"`` und taugt nicht zur Aufteilung. Dafuer ist
    die Liste ``agents`` da, deren Kosten sich zum Tageswert summieren.
    """
    tag = {
        "period": datum,
        "agent": "all",
        "metadata": {"agents": sorted({z["agent"] for z in agentzeilen})},
    }
    tag.update(_summen(breakdowns))
    tag["modelsUsed"] = sorted({b["modelName"] for b in breakdowns})
    tag["modelBreakdowns"] = breakdowns
    tag["agents"] = agentzeilen
    return tag


def _agentzeilen(breakdowns: list[dict]) -> list[dict]:
    nach_agent: dict[str, list[dict]] = {}
    for b in breakdowns:
        nach_agent.setdefault(_agent(b["modelName"]), []).append(b)
    zeilen = []
    for name in sorted(nach_agent):
        zeile = {"agent": name}
        zeile.update(_summen(nach_agent[name]))
        zeile["modelsUsed"] = sorted({b["modelName"] for b in nach_agent[name]})
        zeile["modelBreakdowns"] = nach_agent[name]
        zeilen.append(zeile)
    return zeilen


def _dateisummen(eintraege: list[dict]) -> dict:
    totals = {feld: sum(e[feld] for e in eintraege) for feld in TOKENFELDER}
    totals["totalTokens"] = sum(e["totalTokens"] for e in eintraege)
    totals["totalCost"] = round(sum(e["totalCost"] for e in eintraege), 6)
    return totals


def _schreibe(pfad: Path, payload: dict) -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return pfad


def _zeitstempel(moment: datetime) -> str:
    """ISO-8601 in UTC mit ``Z``, wie das Backend die Quelle erwartet."""
    text = moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    return text.replace("+00:00", "Z")


# --------------------------------------------------------------------------
# Schreibfunktionen
# --------------------------------------------------------------------------

def schreibe_monatsdateien(out: Path, monate: list[str], heute: date,
                           rng: random.Random) -> tuple[list[Path], dict]:
    """Je Monat eine Datei ``YYYY-MM.json``.

    Gibt zusaetzlich die Breakdowns je Tag zurueck. Die Projektdateien bauen
    darauf auf, denn die Kreuzpruefung im Dashboard stellt beide Exportlaeufe
    gegeneinander: eine frei gewuerfelte Projektdatei wuerde zu Recht als
    Abweichung gemeldet.
    """
    pfade = []
    tagesbreakdowns: dict[str, list[dict]] = {}
    for index, monat in enumerate(monate):
        alt = index < ALTE_MONATE
        eintraege = []
        for datum in tage_des_monats(monat, heute, rng):
            breakdowns = [breakdown(m, rng) for m in _modellwahl(rng)]
            tagesbreakdowns[datum] = breakdowns
            if alt:
                eintraege.append(tag_altes_schema(datum, breakdowns))
            else:
                eintraege.append(
                    tag_neues_schema(datum, breakdowns, _agentzeilen(breakdowns))
                )
        payload = {"daily": eintraege, "totals": _dateisummen(eintraege)}
        pfade.append(_schreibe(out / f"{monat}.json", payload))
    return pfade, tagesbreakdowns


def schreibe_projekte(out: Path, monate: list[str],
                      tagesbreakdowns: dict[str, list[dict]],
                      rng: random.Random) -> list[Path]:
    """Projektdateien fuer die juengsten Monate.

    Jeder Modellposten eines Tages geht an genau ein Projekt. So bleibt die
    Summe der Projekte gleich der Summe der Monatsdatei.
    """
    pfade = []
    for monat in monate[-PROJEKTMONATE:]:
        projekte: dict[str, list[dict]] = {}
        eintraege = []
        for datum in sorted(d for d in tagesbreakdowns if d.startswith(monat)):
            verteilt: dict[str, list[dict]] = {}
            for position, b in enumerate(tagesbreakdowns[datum]):
                schluessel = PROJEKTE[(rng.randrange(len(PROJEKTE)) + position)
                                      % len(PROJEKTE)]
                verteilt.setdefault(schluessel, []).append(b)
            for schluessel in sorted(verteilt):
                zeile = {"date": datum, "project": schluessel}
                zeile.update(_summen(verteilt[schluessel]))
                zeile["modelsUsed"] = sorted(
                    {b["modelName"] for b in verteilt[schluessel]})
                zeile["modelBreakdowns"] = verteilt[schluessel]
                projekte.setdefault(schluessel, []).append(zeile)
                eintraege.append(zeile)
        payload = {"projects": projekte, "totals": _dateisummen(eintraege)}
        pfade.append(_schreibe(out / "projects" / f"{monat}.json", payload))
    return pfade


def _wochen(heute: date) -> list[tuple[str, date]]:
    """Die beiden juengsten ISO-Wochen als ``(YYYY-Www, Montag)``."""
    montag = heute - timedelta(days=heute.weekday())
    wochen = []
    for versatz in (7, 0):
        start = montag - timedelta(days=versatz)
        jahr, nummer, _ = start.isocalendar()
        wochen.append((f"{jahr:04d}-W{nummer:02d}", start))
    return wochen


def _sessions_der_woche(start: date, heute: date, index: int,
                        rng: random.Random) -> list[dict]:
    sessions = []
    letzter = min(start + timedelta(days=6), heute)
    tag = start
    laufnummer = 0
    while tag <= letzter:
        for _ in range(rng.choice((0, 1, 1, 2))):
            laufnummer += 1
            beginn = datetime(tag.year, tag.month, tag.day,
                              rng.randrange(7, 21), rng.randrange(60),
                              rng.randrange(60), tzinfo=timezone.utc)
            dauer = timedelta(minutes=rng.randrange(12, 210))
            breakdowns = [breakdown(m, rng) for m in _modellwahl(rng)]
            session = {
                "sessionId": f"sess-{index}-{laufnummer:03d}-"
                             f"{rng.randrange(16**8):08x}",
                "projectPath": PROJEKTE[rng.randrange(len(PROJEKTE))],
                "firstActivity": _zeitstempel(beginn),
                "lastActivity": _zeitstempel(beginn + dauer),
            }
            session.update(_summen(breakdowns))
            session["modelsUsed"] = sorted({b["modelName"] for b in breakdowns})
            session["modelBreakdowns"] = breakdowns
            sessions.append(session)
        tag += timedelta(days=1)
    return sessions


def _block_zu_session(session: dict, gap_davor: bool) -> list[dict]:
    """Ein Arbeitsblock je Session, davor auf Wunsch ein Leerlaufblock.

    Bloecke und Sessions stammen in der echten Quelle aus demselben
    Wochenlauf. Das Dashboard stellt beide Summen gegeneinander, also muessen
    sie hier aus derselben Zahl kommen.
    """
    beginn = datetime.fromisoformat(session["firstActivity"].replace("Z", "+00:00"))
    ende = datetime.fromisoformat(session["lastActivity"].replace("Z", "+00:00"))
    bloecke = []
    if gap_davor:
        luecke_start = beginn - timedelta(hours=5)
        bloecke.append({
            "id": f"gap-{_zeitstempel(luecke_start)}",
            "startTime": _zeitstempel(luecke_start),
            "endTime": _zeitstempel(beginn),
            "actualEndTime": None,
            "isActive": False,
            "isGap": True,
            "entries": 0,
            "costUSD": 0,
            "totalTokens": 0,
            "tokenCounts": {
                "inputTokens": 0,
                "outputTokens": 0,
                "cacheCreationInputTokens": 0,
                "cacheReadInputTokens": 0,
            },
            "models": [],
            "burnRate": None,
            "projection": None,
        })
    minuten = max(1, int((ende - beginn).total_seconds() // 60))
    bloecke.append({
        "id": f"block-{session['sessionId']}",
        "startTime": session["firstActivity"],
        "endTime": _zeitstempel(beginn + timedelta(hours=5)),
        "actualEndTime": session["lastActivity"],
        "isActive": False,
        "isGap": False,
        "entries": len(session["modelBreakdowns"]) * 40,
        "costUSD": session["totalCost"],
        "totalTokens": session["totalTokens"],
        "tokenCounts": {
            "inputTokens": session["inputTokens"],
            "outputTokens": session["outputTokens"],
            "cacheCreationInputTokens": session["cacheCreationTokens"],
            "cacheReadInputTokens": session["cacheReadTokens"],
        },
        "models": session["modelsUsed"],
        "burnRate": {
            "costPerHour": round(session["totalCost"] / (minuten / 60), 4),
            "tokensPerMinute": round(session["totalTokens"] / minuten, 2),
        },
        "projection": {
            "totalCost": round(session["totalCost"] * 1.4, 4),
            "totalTokens": int(session["totalTokens"] * 1.4),
            "remainingMinutes": max(0, 300 - minuten),
        },
    })
    return bloecke


def schreibe_sessions_und_bloecke(out: Path, heute: date,
                                  rng: random.Random) -> list[Path]:
    """Je zwei Wochendateien fuer ``sessions/`` und ``blocks/``.

    Die aeltere Blockdatei enthaelt einen Block, der auch in der juengeren
    steht - dieselbe ``id``. Ohne diese Ueberlappung prueft die Vorfuehrung
    die Deduplizierung nie, obwohl der echte Wochenlauf sie erzeugt.
    """
    pfade = []
    wochen = _wochen(heute)
    wochendaten = []
    for index, (name, start) in enumerate(wochen):
        sessions = _sessions_der_woche(start, heute, index, rng)
        bloecke = []
        for position, session in enumerate(sessions):
            bloecke.extend(_block_zu_session(session, gap_davor=position % 3 == 0))
        wochendaten.append((name, sessions, bloecke))

    ueberlappung = [b for b in wochendaten[0][2] if not b["isGap"]][:1]

    for position, (name, sessions, bloecke) in enumerate(wochendaten):
        pfade.append(_schreibe(
            out / "sessions" / f"{name}.json",
            {"sessions": sessions, "totals": _dateisummen(sessions)},
        ))
        if position == 1:
            bloecke = [*ueberlappung, *bloecke]
        pfade.append(_schreibe(out / "blocks" / f"{name}.json",
                               {"blocks": bloecke}))
    return pfade


def schreibe_rtk(out: Path, monate: list[str], heute: date,
                 rng: random.Random) -> list[Path]:
    """Je Monat eine Datei ``rtk/YYYY-MM.json`` mit der Tagesausgabe.

    Reicht bewusst einen Monat weiter zurueck als die Monatsdateien, damit
    der Abdeckungshinweis im RTK-Reiter erscheint. ``saved_tokens`` ist nicht
    exakt die Differenz aus Ein- und Ausgabe, wie in der echten Quelle auch.
    """
    pfade = []
    for monat in [_vormonat(monate[0]), *monate]:
        zeilen = []
        for datum in tage_des_monats(monat, heute, rng):
            befehle = rng.randrange(80, 1400)
            eingabe = befehle * rng.randrange(3_000, 7_000)
            ausgabe = int(eingabe * rng.uniform(0.30, 0.55))
            gespart = int((eingabe - ausgabe) * rng.uniform(0.85, 0.99))
            zeit = befehle * rng.randrange(9, 40)
            zeilen.append({
                "date": datum,
                "commands": befehle,
                "input_tokens": eingabe,
                "output_tokens": ausgabe,
                "saved_tokens": gespart,
                "savings_pct": round(gespart / eingabe * 100, 6),
                "total_time_ms": zeit,
                "avg_time_ms": zeit // befehle,
            })
        pfade.append(_schreibe(out / "rtk" / f"{monat}.json", {"days": zeilen}))
    return pfade


# --------------------------------------------------------------------------
# Aufruf
# --------------------------------------------------------------------------

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Erzeugt Beispieldaten fuer das Token-Usage-Dashboard.")
    parser.add_argument("--out", default="sample-data",
                        help="Zielverzeichnis (Vorgabe: sample-data)")
    parser.add_argument("--months", type=int, default=5,
                        help="Anzahl der Monatsdateien (Vorgabe: 5)")
    parser.add_argument("--seed", type=int, default=20260901,
                        help="Startwert des Zufallsgenerators (Vorgabe: 20260901)")
    parser.add_argument("--today", default=None,
                        help="Bezugsdatum YYYY-MM-DD (Vorgabe: heute)")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    heute = date.fromisoformat(args.today) if args.today else date.today()
    if args.months < 1:
        raise SystemExit("--months muss mindestens 1 sein.")
    rng = random.Random(args.seed)
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    monate = monatsspanne(heute, args.months)
    pfade, tagesbreakdowns = schreibe_monatsdateien(out, monate, heute, rng)
    pfade += schreibe_projekte(out, monate, tagesbreakdowns, rng)
    pfade += schreibe_sessions_und_bloecke(out, heute, rng)
    pfade += schreibe_rtk(out, monate, heute, rng)

    for pfad in pfade:
        print(pfad)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Einlesen der Zusatzquellen aus dem daily- und weekly-Export.

Ergaenzt loader.py, das nur die Monatsdateien im Wurzelverzeichnis liest.
Quellen: projects/YYYY-MM.json, blocks/YYYY-Www.json, sessions/YYYY-Www.json,
rtk/YYYY-MM.json.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date
from datetime import datetime as _datetime
from pathlib import Path

import loader

PROJECT_DIR = "projects"
BLOCK_DIR = "blocks"
SESSION_DIR = "sessions"
RTK_DIR = "rtk"

MONTH_FILE_RE = loader.MONTH_FILE_RE

# Every message key this module can emit. A new message needs an entry here
# and in every catalogue under static/i18n/, otherwise the dashboard shows
# the bare key in angle brackets. tests/test_i18n.py checks both directions.
MESSAGE_CODES = frozenset({
    "source.file.unreadable",
    "source.projects.not_an_object",
    "source.projects.entry_not_an_array",
    "source.projects.bad_date",
    "source.week.field_missing",
    "source.sessions.bad_entry",
    "source.blocks.bad_entry",
    "source.rtk.days_missing",
    "source.rtk.bad_date",
    "check.projects.cost_mismatch",
    "check.projects.token_mismatch",
    "check.projects.field_mismatch",
    "check.sessions.cost_mismatch",
    "check.block.token_mismatch",
    "check.weekrun.skipped",
    "check.weekrun.cost_mismatch",
    "check.agents.cost_mismatch",
    "check.crosscheck.projects_days_missing",
    "check.crosscheck.monthly_days_missing",
    "check.crosscheck.skipped",
    "check.crosscheck.cost_mismatch",
    "check.rtk.month_mismatch",
    "check.rtk.duplicate_date",
})
WEEK_FILE_RE = re.compile(r"^(\d{4})-W(\d{2})\.json$")


def find_source_files(directory: Path, subdir: str, pattern) -> list[Path]:
    """Sortierte Liste passender Dateien. Fehlt das Verzeichnis, ist das leer."""
    target = Path(directory) / subdir
    if not target.is_dir():
        return []
    return sorted(
        (p for p in target.iterdir() if p.is_file() and pattern.match(p.name)),
        key=lambda p: p.name,
    )


def assign_labels(keys: list[str]) -> dict[str, str]:
    """Kuerzt Projektschluessel um das gemeinsame Praefix.

    Die Quelle ersetzt ``/`` durch ``-``. Ein Bindestrich im Verzeichnisnamen
    ist danach nicht mehr vom Pfadtrenner zu unterscheiden, deshalb wird nur
    gekuerzt und nichts geraten.
    """
    if not keys:
        return {}
    parts = {key: key.strip("-").split("-") for key in keys}
    shortest = min(len(p) for p in parts.values())
    common = 0
    while common < shortest - 1:
        segment = next(iter(parts.values()))[common]
        if any(p[common] != segment for p in parts.values()):
            break
        common += 1
    return {key: "-".join(p[common:]) for key, p in parts.items()}


def _read_json(path: Path, errors: list[dict]):
    """Liest eine JSON-Datei. Fehler landen in ``errors``, Rueckgabe ist None."""
    try:
        with path.open("rb") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        errors.append({"file": path.name, "code": "source.file.unreadable",
                       "params": {"file": path.name, "reason": str(exc)}})
        return None


def _normalize_common(raw: dict, target: dict) -> None:
    """Uebertraegt Token-Felder, Kosten und Modellaufteilung."""
    breakdowns = raw.get("modelBreakdowns")
    if not isinstance(breakdowns, list):
        breakdowns = []
    target["modelBreakdowns"] = [
        loader.normalize_breakdown(b) for b in breakdowns if isinstance(b, dict)
    ]
    models_used = raw.get("modelsUsed")
    if not isinstance(models_used, list):
        models_used = [b["modelName"] for b in target["modelBreakdowns"]]
    target["modelsUsed"] = sorted({str(m) for m in models_used})
    for field in loader.TOKEN_FIELDS:
        target[field] = loader._as_int(raw.get(field))
    target["totalTokens"] = loader._as_int(raw.get("totalTokens"))
    target["sumTokens"] = sum(target[f] for f in loader.TOKEN_FIELDS)
    target["totalCost"] = loader._as_float(raw.get("totalCost"))


def _iso_date(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()[:10]
    try:
        _date.fromisoformat(candidate)
    except ValueError:
        return None
    return candidate


def load_projects(directory: Path) -> dict:
    """Liest projects/YYYY-MM.json und liefert flache Tageszeilen je Projekt."""
    rows: list[dict] = []
    file_infos: list[dict] = []
    errors: list[dict] = []

    for path in find_source_files(directory, PROJECT_DIR, MONTH_FILE_RE):
        info = {"name": path.name, "accepted": False, "rows": 0,
                "hasTotals": False, "totals": loader.normalize_totals(None)}
        payload = _read_json(path, errors)
        if payload is None:
            file_infos.append(info)
            continue
        projects = payload.get("projects") if isinstance(payload, dict) else None
        if not isinstance(projects, dict):
            errors.append({
                "file": path.name,
                "code": "source.projects.not_an_object",
                "params": {"file": path.name},
            })
            file_infos.append(info)
            continue

        file_rows: list[dict] = []
        for key, entries in projects.items():
            if not isinstance(entries, list):
                errors.append({
                    "file": path.name,
                    "code": "source.projects.entry_not_an_array",
                    "params": {"file": path.name, "project": key},
                })
                continue
            for index, raw in enumerate(entries):
                day_date = _iso_date(raw.get("date")) if isinstance(raw, dict) else None
                if day_date is None:
                    errors.append({
                        "file": path.name,
                        "code": "source.projects.bad_date",
                        "params": {"file": path.name, "project": key,
                                   "index": index},
                    })
                    continue
                row = {"date": day_date, "month": day_date[:7],
                       "project": str(raw.get("project") or key),
                       "sourceFile": path.name}
                _normalize_common(raw, row)
                file_rows.append(row)

        info["accepted"] = True
        info["rows"] = len(file_rows)
        info["hasTotals"] = isinstance(payload.get("totals"), dict)
        info["totals"] = loader.normalize_totals(payload.get("totals"))
        file_infos.append(info)
        rows.extend(file_rows)

    labels = assign_labels(sorted({r["project"] for r in rows}))
    for row in rows:
        row["projectLabel"] = labels.get(row["project"], row["project"])
    rows.sort(key=lambda r: (r["date"], r["projectLabel"]))
    return {"rows": rows, "files": file_infos, "errors": errors}


def _iso_moment(value) -> str | None:
    """Prueft einen ISO-8601-Zeitstempel und gibt ihn unveraendert zurueck."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        _datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def _local_date(moment: str) -> str:
    """Kalendertag eines Zeitstempels in der lokalen Zeitzone.

    Der Zeitstempel selbst bleibt unveraendert ISO-8601-UTC. Nur das daraus
    abgeleitete Feld ``date`` wird lokal gebildet, denn danach filtert der
    Zeitraumfilter, waehrend die Tabelle die Zeit ohnehin in Ortszeit zeigt.
    Ohne die Umrechnung faellt eine Session in den UTC-Tag, obwohl das UI den
    Nachbartag anzeigt.
    """
    stamp = _datetime.fromisoformat(moment.replace("Z", "+00:00"))
    return stamp.astimezone().date().isoformat()


def _minutes_between(first: str | None, last: str | None) -> int | None:
    if first is None or last is None:
        return None
    start = _datetime.fromisoformat(first.replace("Z", "+00:00"))
    end = _datetime.fromisoformat(last.replace("Z", "+00:00"))
    return max(0, int((end - start).total_seconds() // 60))


def _load_week_files(directory: Path, subdir: str, key: str) -> tuple:
    """Gemeinsames Geruest fuer sessions/ und blocks/.

    Liefert ``(paare, file_infos, errors)``, wobei ``paare`` eine Liste von
    ``(path, file_info, eintraege)`` ist. Reihenfolge folgt dem Dateinamen,
    spaetere Dateien ueberschreiben also frueheren Inhalt.
    """
    pairs = []
    file_infos: list[dict] = []
    errors: list[dict] = []
    for path in find_source_files(directory, subdir, WEEK_FILE_RE):
        info = {"name": path.name, "accepted": False, "rows": 0,
                "hasTotals": False, "totals": loader.normalize_totals(None)}
        payload = _read_json(path, errors)
        if payload is None:
            file_infos.append(info)
            continue
        entries = payload.get(key) if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            errors.append({
                "file": path.name,
                "code": "source.week.field_missing",
                "params": {"file": path.name, "field": key},
            })
            file_infos.append(info)
            continue
        info["accepted"] = True
        info["hasTotals"] = isinstance(payload.get("totals"), dict)
        info["totals"] = loader.normalize_totals(payload.get("totals"))
        file_infos.append(info)
        pairs.append((path, info, entries))
    return pairs, file_infos, errors


def load_sessions(directory: Path) -> dict:
    """Liest sessions/YYYY-Www.json. Gleiche sessionId: letzte Datei gewinnt."""
    pairs, file_infos, errors = _load_week_files(directory, SESSION_DIR, "sessions")
    merged: dict[str, dict] = {}
    for path, info, entries in pairs:
        count = 0
        summed_cost = 0.0
        for index, raw in enumerate(entries):
            if not isinstance(raw, dict):
                continue
            first = _iso_moment(raw.get("firstActivity"))
            last = _iso_moment(raw.get("lastActivity"))
            session_id = raw.get("sessionId")
            if first is None or not isinstance(session_id, str) or not session_id:
                errors.append({
                    "file": path.name,
                    "code": "source.sessions.bad_entry",
                    "params": {"file": path.name, "index": index},
                })
                continue
            row = {
                "sessionId": session_id,
                "project": str(raw.get("projectPath") or "unbekannt"),
                "first": first,
                "last": last or first,
                "durationMinutes": _minutes_between(first, last or first),
                "date": _local_date(first),
                "sourceFile": path.name,
            }
            _normalize_common(raw, row)
            merged[session_id] = row
            count += 1
            summed_cost += row["totalCost"]
        info["rows"] = count
        info["summedCost"] = summed_cost

    rows = list(merged.values())
    labels = assign_labels(sorted({r["project"] for r in rows}))
    for row in rows:
        row["projectLabel"] = labels.get(row["project"], row["project"])
    rows.sort(key=lambda r: r["first"])
    return {"rows": rows, "files": file_infos, "errors": errors}


def load_blocks(directory: Path) -> dict:
    """Liest blocks/YYYY-Www.json. Gleiche id: letzte Datei gewinnt."""
    pairs, file_infos, errors = _load_week_files(directory, BLOCK_DIR, "blocks")
    merged: dict[str, dict] = {}
    for path, info, entries in pairs:
        count = 0
        for index, raw in enumerate(entries):
            if not isinstance(raw, dict):
                continue
            start = _iso_moment(raw.get("startTime"))
            block_id = raw.get("id")
            if start is None or not isinstance(block_id, str) or not block_id:
                errors.append({
                    "file": path.name,
                    "code": "source.blocks.bad_entry",
                    "params": {"file": path.name, "index": index},
                })
                continue
            counts = raw.get("tokenCounts")
            if not isinstance(counts, dict):
                counts = {}
            burn = raw.get("burnRate") if isinstance(raw.get("burnRate"), dict) else {}
            proj = raw.get("projection") if isinstance(raw.get("projection"), dict) else {}
            models = raw.get("models")
            row = {
                "id": block_id,
                "start": start,
                "end": _iso_moment(raw.get("endTime")),
                "actualEnd": _iso_moment(raw.get("actualEndTime")),
                "date": _local_date(start),
                "isGap": bool(raw.get("isGap")),
                "isActive": bool(raw.get("isActive")),
                "entries": loader._as_int(raw.get("entries")),
                "cost": loader._as_float(raw.get("costUSD")),
                "totalTokens": loader._as_int(raw.get("totalTokens")),
                "inputTokens": loader._as_int(counts.get("inputTokens")),
                "outputTokens": loader._as_int(counts.get("outputTokens")),
                "cacheCreationTokens":
                    loader._as_int(counts.get("cacheCreationInputTokens")),
                "cacheReadTokens":
                    loader._as_int(counts.get("cacheReadInputTokens")),
                "models": sorted({str(m) for m in models}) if isinstance(models, list) else [],
                "burnRateCostPerHour":
                    loader._as_float(burn["costPerHour"]) if "costPerHour" in burn else None,
                "burnRateTokensPerMinute":
                    loader._as_float(burn["tokensPerMinute"]) if "tokensPerMinute" in burn else None,
                "projectionCost":
                    loader._as_float(proj["totalCost"]) if "totalCost" in proj else None,
                "projectionTokens":
                    loader._as_int(proj["totalTokens"]) if "totalTokens" in proj else None,
                "projectionRemainingMinutes":
                    loader._as_int(proj["remainingMinutes"]) if "remainingMinutes" in proj else None,
                "sourceFile": path.name,
            }
            row["sumTokens"] = (row["inputTokens"] + row["outputTokens"]
                                + row["cacheCreationTokens"] + row["cacheReadTokens"])
            row["durationMinutes"] = _minutes_between(
                row["start"], row["actualEnd"] or row["end"]
            )
            merged[block_id] = row
            count += 1
        info["rows"] = count

    rows = sorted(merged.values(), key=lambda r: r["start"])
    return {"rows": rows, "files": file_infos, "errors": errors}


def load_rtk(directory: Path) -> dict:
    """Liest rtk/YYYY-MM.json, die Tagesausgabe von ``rtk gain --all``.

    Bewusst nah an der rtk-Ausgabe: die Felder ``commands``, ``input_tokens``,
    ``output_tokens``, ``saved_tokens``, ``savings_pct``, ``total_time_ms``
    und ``avg_time_ms`` bleiben unbenannt, nur ``date`` und ``month`` kommen
    dazu. Die Quelle kennt kein ``totals``, ``hasTotals`` bleibt ``False``.
    """
    rows: list[dict] = []
    file_infos: list[dict] = []
    errors: list[dict] = []

    for path in find_source_files(directory, RTK_DIR, MONTH_FILE_RE):
        info = {"name": path.name, "accepted": False, "rows": 0,
                "hasTotals": False, "totals": loader.normalize_totals(None)}
        payload = _read_json(path, errors)
        if payload is None:
            file_infos.append(info)
            continue
        days = payload.get("days") if isinstance(payload, dict) else None
        if not isinstance(days, list):
            errors.append({
                "file": path.name,
                "code": "source.rtk.days_missing",
                "params": {"file": path.name},
            })
            file_infos.append(info)
            continue

        file_rows: list[dict] = []
        for index, raw in enumerate(days):
            day_date = _iso_date(raw.get("date")) if isinstance(raw, dict) else None
            if day_date is None:
                errors.append({
                    "file": path.name,
                    "code": "source.rtk.bad_date",
                    "params": {"file": path.name, "index": index},
                })
                continue
            row = {
                "date": day_date, "month": day_date[:7],
                "commands": loader._as_int(raw.get("commands")),
                "input_tokens": loader._as_int(raw.get("input_tokens")),
                "output_tokens": loader._as_int(raw.get("output_tokens")),
                "saved_tokens": loader._as_int(raw.get("saved_tokens")),
                "savings_pct": loader._as_float(raw.get("savings_pct")),
                "total_time_ms": loader._as_int(raw.get("total_time_ms")),
                "avg_time_ms": loader._as_int(raw.get("avg_time_ms")),
                "sourceFile": path.name,
            }
            file_rows.append(row)

        info["accepted"] = True
        info["rows"] = len(file_rows)
        file_infos.append(info)
        rows.extend(file_rows)

    rows.sort(key=lambda r: r["date"])
    return {"rows": rows, "files": file_infos, "errors": errors}


def agent_split(days: list[dict], prefer_agents: bool = True) -> list[dict]:
    """Kosten und Tokens je Agent und Tag.

    Traegt ein Tag das seit 09/2026 vorhandene Feld ``agents``, wird es
    benutzt (``source`` ist dann ``"agents"``). Sonst greift die
    Modellheuristik ueber das Praefix ``gpt-`` (``source`` ist
    ``"heuristik"``). Damit bleibt die gesamte Historie darstellbar.

    ``prefer_agents=False`` erzwingt die Heuristik. Der Aufrufer benutzt das,
    wenn ein Modellfilter aktiv ist: ``metrics.filter_days`` rechnet dann nur
    ``modelBreakdowns`` neu, ``agentBreakdowns`` bliebe ungefiltert und das
    Ergebnis widerspraeche dem Rest der Seite.
    """
    result: list[dict] = []
    for day in days:
        agents: dict[str, dict] = {}
        if prefer_agents and day.get("agentBreakdowns"):
            source = "agents"
            for entry in day["agentBreakdowns"]:
                bucket = agents.setdefault(entry["agent"], {"cost": 0.0, "tokens": 0})
                bucket["cost"] += entry["totalCost"]
                bucket["tokens"] += entry["totalTokens"]
        else:
            source = "heuristik"
            for b in day["modelBreakdowns"]:
                bucket = agents.setdefault(b["agent"], {"cost": 0.0, "tokens": 0})
                bucket["cost"] += b["cost"]
                bucket["tokens"] += b["totalTokens"]
        result.append({"date": day["date"], "source": source, "agents": agents})
    result.sort(key=lambda r: r["date"])
    return result


def load_extras(directory: Path) -> dict:
    """Liest alle vier Zusatzquellen. Fehlende Verzeichnisse sind kein Fehler."""
    projects = load_projects(directory)
    sessions = load_sessions(directory)
    blocks = load_blocks(directory)
    rtk = load_rtk(directory)
    errors = []
    for name, part in (("projects", projects), ("sessions", sessions),
                       ("blocks", blocks), ("rtk", rtk)):
        for err in part["errors"]:
            errors.append({**err, "source": name})
    return {"projects": projects, "sessions": sessions, "blocks": blocks,
            "rtk": rtk, "errors": errors}


def _sum_field(rows: list[dict], field: str):
    return sum(r[field] for r in rows)


def _claude_cost(day: dict) -> float | None:
    if day.get("agentBreakdowns"):
        if abs(sum(a["totalCost"] for a in day["agentBreakdowns"])
               - day["totalCost"]) > loader.COST_TOLERANCE:
            return None
        return sum(a["totalCost"] for a in day["agentBreakdowns"]
                   if a["agent"] == "claude")
    if day.get("modelBreakdowns"):
        if abs(sum(b["cost"] for b in day["modelBreakdowns"])
               - day["totalCost"]) > loader.COST_TOLERANCE:
            return None
        return sum(b["cost"] for b in day["modelBreakdowns"]
                   if b["agent"] == "claude")
    return None


def _has_claude_breakdown(day: dict) -> bool | None:
    if day.get("agentBreakdowns"):
        return any(a["agent"] == "claude" for a in day["agentBreakdowns"])
    if day.get("modelBreakdowns"):
        return any(b["agent"] == "claude" for b in day["modelBreakdowns"])
    return None


def check_extras(extras: dict, days: list[dict]) -> dict:
    """Plausibilitaet der Zusatzquellen. Ergebnis geht in den Statusbereich."""
    issues: list[dict] = []
    tol = loader.COST_TOLERANCE

    # Projektdateien gegen ihre eigenen totals
    for info in extras["projects"]["files"]:
        if not info["accepted"] or not info["hasTotals"]:
            continue
        rows = [r for r in extras["projects"]["rows"]
                if r["sourceFile"] == info["name"]]
        summed_cost = _sum_field(rows, "totalCost")
        if abs(summed_cost - info["totals"]["totalCost"]) > tol:
            issues.append({
                "level": "warn", "scope": "projects", "key": info["name"],
                "code": "check.projects.cost_mismatch",
                "params": {"summed": summed_cost,
                           "total": info["totals"]["totalCost"]},
            })
        summed_tokens = _sum_field(rows, "totalTokens")
        if summed_tokens != info["totals"]["totalTokens"]:
            issues.append({
                "level": "warn", "scope": "projects", "key": info["name"],
                "code": "check.projects.token_mismatch",
                "params": {"summed": summed_tokens,
                           "total": info["totals"]["totalTokens"]},
            })
        for field in ("inputTokens", "outputTokens", "cacheCreationTokens",
                     "cacheReadTokens"):
            if _sum_field(rows, field) != info["totals"][field]:
                issues.append({
                    "level": "warn", "scope": "projects", "key": info["name"],
                    "code": "check.projects.field_mismatch",
                    "params": {"field": field, "summed": _sum_field(rows, field),
                               "total": info["totals"][field]},
                })

    # Sessiondateien gegen ihre eigenen totals
    for info in extras["sessions"]["files"]:
        if not info["accepted"] or not info["hasTotals"]:
            continue
        summed_cost = info["summedCost"]
        if abs(summed_cost - info["totals"]["totalCost"]) > tol:
            issues.append({
                "level": "warn", "scope": "sessions", "key": info["name"],
                "code": "check.sessions.cost_mismatch",
                "params": {"summed": summed_cost,
                           "total": info["totals"]["totalCost"]},
            })

    # Einzelblock: tokenCounts gegen totalTokens.
    # Die Summe ueber alle Bloecke ohne Gaps wird weiter unten gegen die
    # Sessions geprueft und nicht gegen eine Dateisumme: blocks/YYYY-Www.json
    # traegt als einzige der drei Quellen kein Feld totals.
    for row in extras["blocks"]["rows"]:
        if row["isGap"]:
            continue
        if row["sumTokens"] != row["totalTokens"]:
            issues.append({
                "level": "warn", "scope": "block", "key": row["id"],
                "code": "check.block.token_mismatch",
                "params": {"sum": row["sumTokens"], "total": row["totalTokens"]},
            })

    # Gegenprobe Bloecke gegen Sessions. Beide stammen aus demselben
    # weekly-Lauf und muessen auf denselben Betrag kommen. Nur pruefen, wenn
    # beide Quellen dieselben Wochendateien abdecken.
    block_weeks = {f["name"] for f in extras["blocks"]["files"] if f["accepted"]}
    session_weeks = {f["name"] for f in extras["sessions"]["files"] if f["accepted"]}
    if block_weeks and block_weeks != session_weeks:
        # Ohne diese Meldung faellt die Gegenprobe still aus, der Statusbereich
        # bleibt gruen und der Nutzer glaubt, gegengeprueft worden zu sein.
        # Der Fall tritt ein, wenn der weekly-Lauf nach den Bloecken abbricht.
        issues.append({
            "level": "info", "scope": "wochenlauf",
            "key": ", ".join(sorted(block_weeks | session_weeks)),
            "code": "check.weekrun.skipped",
            "params": {
                "missingSessions": sorted(block_weeks - session_weeks),
                "missingBlocks": sorted(session_weeks - block_weeks),
            },
        })
    elif block_weeks:
        block_sum = sum(r["cost"] for r in extras["blocks"]["rows"] if not r["isGap"])
        session_sum = _sum_field(extras["sessions"]["rows"], "totalCost")
        if abs(block_sum - session_sum) > tol:
            issues.append({
                "level": "warn", "scope": "wochenlauf",
                "key": ", ".join(sorted(block_weeks)),
                "code": "check.weekrun.cost_mismatch",
                "params": {"blockSum": block_sum, "sessionSum": session_sum},
            })

    # agents[] gegen den Tageswert
    for day in days:
        if not day.get("agentBreakdowns"):
            continue
        summed = sum(a["totalCost"] for a in day["agentBreakdowns"])
        if abs(summed - day["totalCost"]) > tol:
            issues.append({
                "level": "warn", "scope": "agents", "key": day["date"],
                "code": "check.agents.cost_mismatch",
                "params": {"summed": summed, "total": day["totalCost"]},
            })

    # Kreuzpruefung: Projekte gegen Monatsdatei, nur fuer gemeinsame Monate
    project_months = {r["month"] for r in extras["projects"]["rows"]}
    project_months.update(
        f["name"][:7] for f in extras["projects"]["files"] if f["accepted"]
    )
    day_months = {d["month"] for d in days}
    for month in sorted(project_months & day_months):
        month_days = [d for d in days if d["month"] == month]
        if any(_claude_cost(d) is None and abs(d["totalCost"]) > tol
               for d in month_days):
            issues.append({
                "level": "info", "scope": "kreuzpruefung", "key": month,
                "code": "check.crosscheck.skipped", "params": {},
            })
            continue
        project_costs: dict[str, float] = {}
        for row in extras["projects"]["rows"]:
            if row["month"] == month:
                project_costs[row["date"]] = (
                    project_costs.get(row["date"], 0.0) + row["totalCost"]
                )
        monthly_costs = {
            d["date"]: _claude_cost(d) or 0.0
            for d in month_days if _has_claude_breakdown(d)
        }
        missing_projects = sorted(monthly_costs.keys() - project_costs.keys())
        if missing_projects:
            issues.append({
                "level": "warn", "scope": "kreuzpruefung", "key": month,
                "code": "check.crosscheck.projects_days_missing",
                "params": {"dates": missing_projects},
            })
        missing_monthly = sorted(project_costs.keys() - monthly_costs.keys())
        if missing_monthly:
            issues.append({
                "level": "warn", "scope": "kreuzpruefung", "key": month,
                "code": "check.crosscheck.monthly_days_missing",
                "params": {"dates": missing_monthly},
            })
        differing_dates = [
            day for day in sorted(monthly_costs.keys() & project_costs.keys())
            if abs(project_costs[day] - monthly_costs[day]) > tol
        ]
        if differing_dates:
            issues.append({
                "level": "warn", "scope": "kreuzpruefung", "key": month,
                "code": "check.crosscheck.cost_mismatch",
                "params": {
                    "projectSum": sum(project_costs[d] for d in differing_dates),
                    "monthlySum": sum(monthly_costs[d] for d in differing_dates),
                    "dates": differing_dates,
                },
            })

    # RTK: Monatszuordnung und Eindeutigkeit der Tage. Die Quelle hat kein
    # totals, keine Kosten und keinen zweiten Exportlauf, gegen den sich etwas
    # stellen liesse; geprueft werden stattdessen die zwei Zusagen, die
    # rtk-merge.py beim Gruppieren nach Monat und Zusammenfuehren nach date
    # brechen kann.
    for row in extras["rtk"]["rows"]:
        expected_month = row["sourceFile"][:7]
        if row["month"] != expected_month:
            issues.append({
                "level": "warn", "scope": "rtk", "key": row["sourceFile"],
                "code": "check.rtk.month_mismatch",
                "params": {"date": row["date"], "file": row["sourceFile"],
                           "month": row["month"]},
            })

    rtk_dates: dict[str, list[str]] = {}
    for row in extras["rtk"]["rows"]:
        rtk_dates.setdefault(row["date"], []).append(row["sourceFile"])
    for day, files in sorted(rtk_dates.items()):
        if len(files) > 1:
            issues.append({
                "level": "warn", "scope": "rtk", "key": day,
                "code": "check.rtk.duplicate_date",
                "params": {"date": day, "files": files},
            })

    checks = {
        "projectFiles": sum(1 for f in extras["projects"]["files"] if f["accepted"]),
        "sessionFiles": sum(1 for f in extras["sessions"]["files"] if f["accepted"]),
        "blockFiles": sum(1 for f in extras["blocks"]["files"] if f["accepted"]),
        "projectRows": len(extras["projects"]["rows"]),
        "sessionRows": len(extras["sessions"]["rows"]),
        "blockRows": len(extras["blocks"]["rows"]),
        "gapRows": sum(1 for r in extras["blocks"]["rows"] if r["isGap"]),
        "crossCheckedMonths": sorted(project_months & day_months),
        "weekFilesCompared": sorted(block_weeks & session_weeks),
        "rtkFiles": sum(1 for f in extras["rtk"]["files"] if f["accepted"]),
        "rtkRows": len(extras["rtk"]["rows"]),
        "rtkDays": len({r["date"] for r in extras["rtk"]["rows"]}),
    }
    return {"issues": issues, "checks": checks}

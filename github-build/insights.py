# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Kennzahlen zu den Zusatzquellen aus sources.py.

Ergaenzt metrics.py, das ausschliesslich auf den Tagesdaten der
Monatsdateien arbeitet.
"""

from __future__ import annotations

import statistics

import loader
import metrics

TOP_PROJECTS = 8
# Sentinel for the rest bucket. Not a string: every string could be a real
# project label, and the bucket would then silently swallow that project.
_OTHER = object()

# Every message key this module can emit. A new message needs an entry here
# and in every catalogue under static/i18n/, otherwise the dashboard shows
# the bare key in angle brackets. tests/test_i18n.py checks both directions.
MESSAGE_CODES = frozenset({
    "range.no_data",
    "range.empty",
    "range.partial",
})


def _calendar_axis(dates) -> list[str]:
    """Achse ueber alle Kalendertage von der ersten bis zur letzten Angabe.

    Fehlende Tage bleiben als Position erhalten und werden von den Aufrufern
    mit ``None`` gefuellt. Ohne das wuerde ein Diagramm zwei Tage nebeneinander
    zeichnen, zwischen denen in Wirklichkeit eine Luecke liegt. Dieselbe Regel
    gilt in ``metrics.daily_series`` und ``metrics.stacked_by_model``; der
    Kalenderhelfer wird von dort uebernommen statt verdoppelt.
    """
    known = sorted(set(dates))
    if not known:
        return []
    return metrics._calendar_labels(known[0], known[-1])


def coverage(dates: list[str], date_from: str | None,
             date_to: str | None) -> dict:
    """Compare the requested range with the range actually present.

    The result carries a message key and raw parameters instead of a
    finished sentence: only the frontend knows the active language.
    """
    first = min(dates) if dates else None
    last = max(dates) if dates else None
    complete = True
    note_code = ""
    note_params: dict = {}
    if first is None:
        complete = False
        note_code = "range.no_data"
    else:
        no_overlap = (bool(date_from) and date_from > last) or (
            bool(date_to) and date_to < first
        )
        if no_overlap:
            complete = False
            note_code = "range.empty"
            note_params = {"first": first, "last": last}
        else:
            missing_front = bool(date_from) and first > date_from
            missing_back = bool(date_to) and last < date_to
            if missing_front or missing_back:
                complete = False
                note_code = "range.partial"
                note_params = {"first": first, "last": last}
    return {"from": first, "to": last, "requestedFrom": date_from,
            "requestedTo": date_to, "complete": complete,
            "noteCode": note_code, "noteParams": note_params}


def _apply_models(row: dict, selected: set[str]) -> dict | None:
    """Rechnet eine Zeile auf die gewaehlten Modelle um. None heisst: faellt weg."""
    breakdowns = [b for b in row["modelBreakdowns"] if b["modelName"] in selected]
    if not breakdowns:
        return None
    subset = dict(row)
    subset["modelBreakdowns"] = breakdowns
    subset["modelsUsed"] = sorted({b["modelName"] for b in breakdowns})
    for field in loader.TOKEN_FIELDS:
        subset[field] = sum(b[field] for b in breakdowns)
    subset["totalTokens"] = sum(subset[field] for field in loader.TOKEN_FIELDS)
    subset["sumTokens"] = subset["totalTokens"]
    subset["totalCost"] = sum(b["cost"] for b in breakdowns)
    return subset


def filter_rows(rows: list[dict], date_from: str | None = None,
                date_to: str | None = None,
                models: list[str] | None = None) -> list[dict]:
    """Filtert nach Zeitraum und Modellen, analog zu metrics.filter_days."""
    selected = set(models) if models else None
    result: list[dict] = []
    for row in rows:
        if date_from and row["date"] < date_from:
            continue
        if date_to and row["date"] > date_to:
            continue
        if selected is None:
            result.append(row)
            continue
        subset = _apply_models(row, selected)
        if subset is not None:
            result.append(subset)
    return result


def _cost_per_million(cost: float, tokens: float) -> float | None:
    if not tokens:
        return None
    return cost / tokens * 1_000_000


def project_insights(rows: list[dict], date_from: str | None = None,
                     date_to: str | None = None,
                     models: list[str] | None = None) -> dict:
    """KPIs, gestapelte Tagesreihe und Tabelle je Projekt."""
    cov = coverage([r["date"] for r in rows], date_from, date_to)
    selected = filter_rows(rows, date_from, date_to, models)

    per_project: dict[str, dict] = {}
    for row in selected:
        entry = per_project.setdefault(row["projectLabel"], {
            "project": row["project"], "projectLabel": row["projectLabel"],
            "cost": 0.0, "tokens": 0, "dates": set(),
        })
        entry["cost"] += row["totalCost"]
        entry["tokens"] += row["totalTokens"]
        entry["dates"].add(row["date"])

    total_cost = sum(e["cost"] for e in per_project.values())
    table = []
    for entry in sorted(per_project.values(), key=lambda e: -e["cost"]):
        table.append({
            "project": entry["project"],
            "projectLabel": entry["projectLabel"],
            "cost": entry["cost"],
            "share": entry["cost"] / total_cost if total_cost else 0.0,
            "tokens": entry["tokens"],
            "days": len(entry["dates"]),
            "costPerMillion": _cost_per_million(entry["cost"], entry["tokens"]),
        })

    labels = _calendar_axis(r["date"] for r in selected)
    top = [t["projectLabel"] for t in table[:TOP_PROJECTS]]
    rest = [t["projectLabel"] for t in table[TOP_PROJECTS:]]
    buckets = {name: {"cost": {}, "tokens": {}} for name in top}
    if rest:
        buckets[_OTHER] = {"cost": {}, "tokens": {}}
    for row in selected:
        name = row["projectLabel"] if row["projectLabel"] in buckets else _OTHER
        bucket = buckets[name]
        bucket["cost"][row["date"]] = bucket["cost"].get(row["date"], 0.0) + row["totalCost"]
        bucket["tokens"][row["date"]] = bucket["tokens"].get(row["date"], 0) + row["totalTokens"]

    datasets = []
    for name in [*top, *([_OTHER] if rest else [])]:
        bucket = buckets[name]
        datasets.append({
            "label": "" if name is _OTHER else name,
            "isOther": name is _OTHER,
            "cost": [bucket["cost"].get(d) for d in labels],
            "tokens": [bucket["tokens"].get(d) for d in labels],
        })

    top_entry = table[0] if table else None
    kpis = {
        "projectCount": len(table),
        "topProject": top_entry["projectLabel"] if top_entry else None,
        "topProjectCost": top_entry["cost"] if top_entry else 0.0,
        "topProjectShare": top_entry["share"] if top_entry else 0.0,
        "totalCost": total_cost,
        "totalTokens": sum(e["tokens"] for e in per_project.values()),
        "days": len({r["date"] for r in selected}),
    }
    return {"kpis": kpis, "stacked": {"labels": labels, "datasets": datasets},
            "table": table, "coverage": cov}


TOP_SESSIONS = 20
HISTOGRAM_BOUNDS = (0.10, 1.0, 5.0, 20.0, 50.0)
# The class bounds are closed on the left: a value of exactly 50 goes into
# the top class, not the one below. The label says so. The labels
# themselves are built in the frontend, which is the only side that knows
# the active language and its number format.


def _histogram(costs: list[float]) -> dict:
    """Cost classes. The median alone hides the skew of the distribution."""
    counts = [0] * (len(HISTOGRAM_BOUNDS) + 1)
    sums = [0.0] * (len(HISTOGRAM_BOUNDS) + 1)
    for value in costs:
        index = len(HISTOGRAM_BOUNDS)
        for position, bound in enumerate(HISTOGRAM_BOUNDS):
            if value < bound:
                index = position
                break
        counts[index] += 1
        sums[index] += value
    return {"bounds": list(HISTOGRAM_BOUNDS), "counts": counts, "cost": sums}


def session_insights(rows: list[dict], date_from: str | None = None,
                     date_to: str | None = None,
                     models: list[str] | None = None) -> dict:
    """KPIs, teuerste Sessions und Kostenverteilung."""
    cov = coverage([r["date"] for r in rows], date_from, date_to)
    selected = filter_rows(rows, date_from, date_to, models)

    costs = [r["totalCost"] for r in selected]
    durations = [r["durationMinutes"] for r in selected
                 if r["durationMinutes"] is not None]
    ranked = sorted(selected, key=lambda r: -r["totalCost"])
    top = [
        {
            "sessionId": r["sessionId"],
            "project": r["project"],
            "projectLabel": r["projectLabel"],
            "first": r["first"],
            "last": r["last"],
            "durationMinutes": r["durationMinutes"],
            "cost": r["totalCost"],
            "tokens": r["totalTokens"],
            "modelsUsed": r["modelsUsed"],
            "costPerMillion": _cost_per_million(r["totalCost"], r["totalTokens"]),
        }
        for r in ranked[:TOP_SESSIONS]
    ]

    kpis = {
        "sessionCount": len(selected),
        "medianCost": statistics.median(costs) if costs else None,
        "maxCost": max(costs) if costs else None,
        "maxSessionId": ranked[0]["sessionId"] if ranked else None,
        "maxSessionProject": ranked[0]["projectLabel"] if ranked else None,
        "medianDurationMinutes":
            round(statistics.median(durations)) if durations else None,
        "totalCost": sum(costs),
        "totalTokens": sum(r["totalTokens"] for r in selected),
    }
    return {"kpis": kpis, "top": top, "histogram": _histogram(costs),
            "coverage": cov}


def block_insights(rows: list[dict], date_from: str | None = None,
                   date_to: str | None = None) -> dict:
    """KPIs und Zeitleiste der 5-Stunden-Bloecke.

    Kein Modellfilter: die Quelle liefert je Block nur ``models[]`` ohne
    Kostenaufteilung.
    """
    cov = coverage([r["date"] for r in rows], date_from, date_to)
    selected = [r for r in rows
                if (not date_from or r["date"] >= date_from)
                and (not date_to or r["date"] <= date_to)]

    real = [r for r in selected if not r["isGap"]]
    gaps = [r for r in selected if r["isGap"]]
    costs = [r["cost"] for r in real]

    used_minutes = sum(r["durationMinutes"] or 0 for r in real)
    gap_minutes = sum(r["durationMinutes"] or 0 for r in gaps)
    span = used_minutes + gap_minutes

    top_block = max(real, key=lambda r: r["cost"]) if real else None
    active = next((r for r in selected if r["isActive"]), None)

    points = [
        {
            "id": r["id"],
            "start": r["start"],
            "end": r["end"],
            "isGap": r["isGap"],
            "isActive": r["isActive"],
            "cost": None if r["isGap"] else r["cost"],
            "tokens": None if r["isGap"] else r["totalTokens"],
            "burnRate": r["burnRateCostPerHour"],
            "durationMinutes": r["durationMinutes"],
        }
        for r in selected
    ]

    kpis = {
        "blockCount": len(real),
        "gapCount": len(gaps),
        "maxCost": max(costs) if costs else None,
        "maxBlockStart": top_block["start"] if top_block else None,
        "meanCost": sum(costs) / len(costs) if costs else None,
        "activeShare": used_minutes / span if span else None,
        "totalCost": sum(costs),
        "totalTokens": sum(r["totalTokens"] for r in real),
    }
    active_out = None
    if active is not None:
        active_out = {
            "id": active["id"],
            "start": active["start"],
            "end": active["end"],
            "cost": active["cost"],
            "burnRate": active["burnRateCostPerHour"],
            "projectionCost": active["projectionCost"],
            "projectionTokens": active["projectionTokens"],
            "projectionRemainingMinutes": active["projectionRemainingMinutes"],
        }
    return {"kpis": kpis, "timeline": {"points": points}, "active": active_out,
            "coverage": cov, "modelFilterSupported": False}


def rtk_insights(rows: list[dict], date_from: str | None = None,
                 date_to: str | None = None) -> dict:
    """KPIs, Tagesreihe und Monatssummen der rtk-Ersparnis.

    Kein Modellfilter: die Quelle kennt keine Modelle. Die Sparquote wird
    genau einmal aus den Summen ueber den gefilterten Zeitraum gerechnet
    (Summe ``saved_tokens`` durch Summe ``input_tokens``), nicht als Mittel
    der Tagesquoten -- sonst wuerde sie mit der Filterstellung springen.
    Dieselbe Regel gilt fuer die Sparquote je Monat in ``months``: Summe je
    Monat durch Summe je Monat, nicht das Mittel der Tagesquoten.
    """
    cov = coverage([r["date"] for r in rows], date_from, date_to)
    selected = [r for r in rows
                if (not date_from or r["date"] >= date_from)
                and (not date_to or r["date"] <= date_to)]

    total_saved = sum(r["saved_tokens"] for r in selected)
    total_input = sum(r["input_tokens"] for r in selected)
    total_commands = sum(r["commands"] for r in selected)
    total_time = sum(r["total_time_ms"] for r in selected)

    kpis = {
        "savedTokens": total_saved if selected else None,
        "savingsRate": (total_saved / total_input) if total_input else None,
        "commands": total_commands if selected else None,
        "savedTokensPerCommand":
            (total_saved / total_commands) if total_commands else None,
        "totalTimeMs": total_time if selected else None,
        "avgTimeMsPerCommand":
            (total_time / total_commands) if total_commands else None,
    }

    labels = _calendar_axis(r["date"] for r in selected)
    by_date = {r["date"]: r for r in selected}
    daily_saved = []
    daily_rate = []
    for day in labels:
        entry = by_date.get(day)
        if entry is None:
            daily_saved.append(None)
            daily_rate.append(None)
        else:
            daily_saved.append(entry["saved_tokens"])
            daily_rate.append(
                entry["saved_tokens"] / entry["input_tokens"]
                if entry["input_tokens"] else None
            )

    by_month: dict[str, dict] = {}
    for row in selected:
        bucket = by_month.setdefault(row["month"], {
            "month": row["month"], "commands": 0, "inputTokens": 0,
            "savedTokens": 0,
        })
        bucket["commands"] += row["commands"]
        bucket["inputTokens"] += row["input_tokens"]
        bucket["savedTokens"] += row["saved_tokens"]
    months = [by_month[key] for key in sorted(by_month)]
    for bucket in months:
        bucket["savingsRate"] = (
            bucket["savedTokens"] / bucket["inputTokens"]
            if bucket["inputTokens"] else None
        )

    return {
        "kpis": kpis,
        "daily": {"labels": labels, "savedTokens": daily_saved,
                  "savingsRate": daily_rate},
        "months": months,
        "coverage": cov,
        "modelFilterSupported": False,
    }


_EMPTY = {"agents": {}}


def agent_series(split: list[dict]) -> dict:
    """Formt sources.agent_split in eine Chart-Struktur um.

    ``firstAgentsDate`` ist der erste Tag, an dem die Aufteilung aus dem Feld
    ``agents`` stammt statt aus der Modellheuristik. Das UI benennt damit die
    Umschaltstelle in der Fussnote.
    """
    labels = _calendar_axis(entry["date"] for entry in split)
    by_date = {entry["date"]: entry for entry in split}
    names = sorted({name for entry in split for name in entry["agents"]})
    series = []
    for name in names:
        series.append({
            "label": name,
            "cost": [by_date.get(d, _EMPTY)["agents"].get(name, {}).get("cost")
                     for d in labels],
            "tokens": [by_date.get(d, _EMPTY)["agents"].get(name, {}).get("tokens")
                       for d in labels],
        })
    first_agents = next((e["date"] for e in split if e["source"] == "agents"), None)
    return {"labels": labels, "datasets": series,
            "sources": [by_date[d]["source"] if d in by_date else None
                        for d in labels],
            "firstAgentsDate": first_agents}

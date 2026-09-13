# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Berechnung der Kennzahlen aus den normalisierten Tagesdaten.

Grundregel: fehlende Kalendertage sind Luecken, keine Nullen. Mittelwerte und
Mediane laufen ausschliesslich ueber Tage mit Daten, Zeitreihen tragen an
fehlenden Tagen ``None``.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from loader import TOKEN_FIELDS, agent_for_model

MA_WINDOW_DAYS = 7
MA_MIN_POINTS = 3
# Sentinel for the rest bucket, see insights._OTHER.
_OTHER = object()


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _ratio(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return numerator / denominator


def _cost_per_million(cost: float, tokens: float) -> float | None:
    if not tokens:
        return None
    return cost / tokens * 1_000_000


def available_models(days: list[dict]) -> list[str]:
    models = set()
    for day in days:
        for breakdown in day["modelBreakdowns"]:
            models.add(breakdown["modelName"])
        models.update(day["modelsUsed"])
    return sorted(models)


def date_range(days: list[dict]) -> tuple[str | None, str | None]:
    if not days:
        return None, None
    return days[0]["date"], days[-1]["date"]


def _calendar_labels(first: str, last: str) -> list[str]:
    start = date.fromisoformat(first)
    end = date.fromisoformat(last)
    labels = []
    current = start
    while current <= end:
        labels.append(current.isoformat())
        current += timedelta(days=1)
    return labels


# --------------------------------------------------------------------------
# Filter
# --------------------------------------------------------------------------

def filter_days(
    days: list[dict],
    date_from: str | None = None,
    date_to: str | None = None,
    models: list[str] | None = None,
) -> list[dict]:
    """Filtert nach Zeitraum und Modellen.

    Ist ein Modellfilter aktiv, werden die Tageswerte aus den passenden
    ``modelBreakdowns`` neu gebildet. Ohne Modellfilter bleiben die
    Originalwerte der Datei unveraendert erhalten.
    """
    selected = set(models) if models else None
    result: list[dict] = []

    for day in days:
        if date_from and day["date"] < date_from:
            continue
        if date_to and day["date"] > date_to:
            continue
        if selected is None:
            result.append(day)
            continue

        breakdowns = [
            b for b in day["modelBreakdowns"] if b["modelName"] in selected
        ]
        if not breakdowns:
            continue
        subset = dict(day)
        subset["modelBreakdowns"] = breakdowns
        subset["modelsUsed"] = sorted({b["modelName"] for b in breakdowns})
        subset["agents"] = sorted({b["agent"] for b in breakdowns})
        for field in TOKEN_FIELDS:
            subset[field] = sum(b[field] for b in breakdowns)
        subset["totalTokens"] = sum(b["totalTokens"] for b in breakdowns)
        subset["sumTokens"] = subset["totalTokens"]
        subset["totalCost"] = sum(b["cost"] for b in breakdowns)
        result.append(subset)

    return result


# --------------------------------------------------------------------------
# Einzelne Kennzahlen
# --------------------------------------------------------------------------

def monthly_totals(days: list[dict]) -> list[dict]:
    months: dict[str, dict] = {}
    for day in days:
        bucket = months.setdefault(
            day["month"],
            {
                "month": day["month"],
                "days": 0,
                "totalTokens": 0,
                "totalCost": 0.0,
                **{field: 0 for field in TOKEN_FIELDS},
            },
        )
        bucket["days"] += 1
        bucket["totalTokens"] += day["totalTokens"]
        bucket["totalCost"] += day["totalCost"]
        for field in TOKEN_FIELDS:
            bucket[field] += day[field]
    result = [months[key] for key in sorted(months)]
    for bucket in result:
        bucket["costPerMillionTokens"] = _cost_per_million(
            bucket["totalCost"], bucket["totalTokens"]
        )
    return result


def cumulative_by_month(days: list[dict]) -> dict:
    """Kumulierte Monatskosten, X-Achse ist der Tag im Monat."""
    months: dict[str, dict[int, float]] = {}
    max_day = 28
    for day in days:
        months.setdefault(day["month"], {})
        months[day["month"]][day["day"]] = (
            months[day["month"]].get(day["day"], 0.0) + day["totalCost"]
        )
        max_day = max(max_day, day["day"])

    labels = list(range(1, max_day + 1))
    series = []
    for month in sorted(months):
        running = 0.0
        seen = False
        data: list[float | None] = []
        for day_number in labels:
            if day_number in months[month]:
                running += months[month][day_number]
                seen = True
            data.append(round(running, 6) if seen else None)
        series.append({"month": month, "data": data})
    return {"labels": labels, "series": series}


def daily_series(days: list[dict]) -> dict:
    """Tageszeitreihen ueber den gesamten Kalenderbereich, Luecken als None."""
    if not days:
        return {
            "labels": [],
            "cost": [],
            "tokens": [],
            "outputTokens": [],
            "costPerMillionTokens": [],
            "costPerMillionTokensMA7": [],
            "contextReloadFactor": [],
        }

    by_date = {day["date"]: day for day in days}
    labels = _calendar_labels(days[0]["date"], days[-1]["date"])

    cost: list[float | None] = []
    tokens: list[int | None] = []
    output: list[int | None] = []
    cpm: list[float | None] = []
    reload_factor: list[float | None] = []

    for label in labels:
        day = by_date.get(label)
        if day is None:
            cost.append(None)
            tokens.append(None)
            output.append(None)
            cpm.append(None)
            reload_factor.append(None)
            continue
        cost.append(day["totalCost"])
        tokens.append(day["totalTokens"])
        output.append(day["outputTokens"])
        cpm.append(_cost_per_million(day["totalCost"], day["totalTokens"]))
        reload_factor.append(_ratio(day["cacheReadTokens"], day["outputTokens"]))

    return {
        "labels": labels,
        "cost": cost,
        "tokens": tokens,
        "outputTokens": output,
        "costPerMillionTokens": cpm,
        "costPerMillionTokensMA7": rolling_mean(cpm),
        "contextReloadFactor": reload_factor,
    }


def rolling_mean(
    values: list[float | None],
    window: int = MA_WINDOW_DAYS,
    min_points: int = MA_MIN_POINTS,
) -> list[float | None]:
    """Gleitendes Mittel ueber ein Kalenderfenster.

    Fehlende Tage gehen nicht als Null ein, sie fehlen schlicht. Liegen im
    Fenster weniger als ``min_points`` Werte, bleibt das Ergebnis None.
    """
    result: list[float | None] = []
    for index in range(len(values)):
        start = max(0, index - window + 1)
        present = [v for v in values[start : index + 1] if v is not None]
        if len(present) < min_points:
            result.append(None)
        else:
            result.append(sum(present) / len(present))
    return result


def model_totals(days: list[dict]) -> list[dict]:
    """Kosten-, Token- und Nutzungskennzahlen je Modell."""
    models: dict[str, dict] = {}
    for day in days:
        for breakdown in day["modelBreakdowns"]:
            name = breakdown["modelName"]
            bucket = models.setdefault(
                name,
                {
                    "model": name,
                    "agent": agent_for_model(name),
                    "cost": 0.0,
                    "totalTokens": 0,
                    "days": 0,
                    "firstDay": day["date"],
                    "lastDay": day["date"],
                    **{field: 0 for field in TOKEN_FIELDS},
                },
            )
            bucket["cost"] += breakdown["cost"]
            bucket["totalTokens"] += breakdown["totalTokens"]
            bucket["days"] += 1
            bucket["firstDay"] = min(bucket["firstDay"], day["date"])
            bucket["lastDay"] = max(bucket["lastDay"], day["date"])
            for field in TOKEN_FIELDS:
                bucket[field] += breakdown[field]

    total_cost = sum(b["cost"] for b in models.values())
    total_tokens = sum(b["totalTokens"] for b in models.values())

    result = []
    for bucket in models.values():
        bucket["costShare"] = (
            bucket["cost"] / total_cost * 100 if total_cost else 0.0
        )
        bucket["tokenShare"] = (
            bucket["totalTokens"] / total_tokens * 100 if total_tokens else 0.0
        )
        # Nutzungsverhaeltnis, kein Listenpreis.
        bucket["costPerMillionOutputTokens"] = _cost_per_million(
            bucket["cost"], bucket["outputTokens"]
        )
        bucket["costPerMillionTokens"] = _cost_per_million(
            bucket["cost"], bucket["totalTokens"]
        )
        bucket["contextReloadFactor"] = _ratio(
            bucket["cacheReadTokens"], bucket["outputTokens"]
        )
        result.append(bucket)

    result.sort(key=lambda b: b["cost"], reverse=True)
    return result


def pareto(models: list[dict]) -> dict:
    """Balken absteigend plus kumulierte Prozentlinie."""
    ordered = sorted(models, key=lambda m: m["cost"], reverse=True)
    total = sum(m["cost"] for m in ordered)
    labels, cost, tokens, cumulative = [], [], [], []
    running = 0.0
    for entry in ordered:
        running += entry["cost"]
        labels.append(entry["model"])
        cost.append(entry["cost"])
        tokens.append(entry["totalTokens"])
        cumulative.append(running / total * 100 if total else 0.0)
    return {
        "labels": labels,
        "cost": cost,
        "tokens": tokens,
        "cumulativePercent": cumulative,
    }


def stacked_by_model(days: list[dict], top: int = 10) -> dict:
    """Tageswerte je Modell fuer den gestapelten Balken."""
    if not days:
        return {"labels": [], "datasets": []}
    ranked = [m["model"] for m in model_totals(days)]
    keep = ranked[:top]
    rest = set(ranked[top:])

    labels = _calendar_labels(days[0]["date"], days[-1]["date"])
    index = {label: position for position, label in enumerate(labels)}
    series = {
        name: {"cost": [None] * len(labels), "tokens": [None] * len(labels)}
        for name in keep
    }
    if rest:
        series[_OTHER] = {
            "cost": [None] * len(labels),
            "tokens": [None] * len(labels),
        }

    for day in days:
        position = index[day["date"]]
        for breakdown in day["modelBreakdowns"]:
            name = breakdown["modelName"]
            key = name if name in series else _OTHER
            if key not in series:
                continue
            target = series[key]
            target["cost"][position] = (target["cost"][position] or 0.0) + breakdown["cost"]
            target["tokens"][position] = (
                target["tokens"][position] or 0
            ) + breakdown["totalTokens"]

    datasets = [
        {"model": "" if name is _OTHER else name,
         "isOther": name is _OTHER,
         "cost": values["cost"], "tokens": values["tokens"]}
        for name, values in series.items()
    ]
    return {"labels": labels, "datasets": datasets}


def model_timeline(models: list[dict]) -> list[dict]:
    """Erster und letzter Einsatztag je Modell sowie Anzahl Nutzungstage."""
    timeline = [
        {
            "model": entry["model"],
            "agent": entry["agent"],
            "firstDay": entry["firstDay"],
            "lastDay": entry["lastDay"],
            "days": entry["days"],
            "spanDays": (
                date.fromisoformat(entry["lastDay"])
                - date.fromisoformat(entry["firstDay"])
            ).days
            + 1,
            "cost": entry["cost"],
        }
        for entry in models
    ]
    timeline.sort(key=lambda e: (e["firstDay"], e["model"]))
    return timeline


def top_days(days: list[dict], limit: int = 10) -> list[dict]:
    ordered = sorted(days, key=lambda d: d["totalCost"], reverse=True)[:limit]
    return [
        {
            "date": day["date"],
            "totalCost": day["totalCost"],
            "totalTokens": day["totalTokens"],
            "outputTokens": day["outputTokens"],
            "costPerMillionTokens": _cost_per_million(
                day["totalCost"], day["totalTokens"]
            ),
            "models": sorted(
                (
                    {
                        "model": b["modelName"],
                        "cost": b["cost"],
                        "totalTokens": b["totalTokens"],
                    }
                    for b in day["modelBreakdowns"]
                ),
                key=lambda m: m["cost"],
                reverse=True,
            ),
        }
        for day in ordered
    ]


def summary(days: list[dict]) -> dict:
    costs = [day["totalCost"] for day in days]
    total_cost = sum(costs)
    total_tokens = sum(day["totalTokens"] for day in days)
    first, last = date_range(days)
    calendar_days = len(_calendar_labels(first, last)) if first else 0

    min_day = min(days, key=lambda d: d["totalCost"], default=None)
    max_day = max(days, key=lambda d: d["totalCost"], default=None)

    cpm_values = [
        (day["date"], _cost_per_million(day["totalCost"], day["totalTokens"]))
        for day in days
    ]
    cpm_values = [(d, v) for d, v in cpm_values if v is not None]
    cpm_min = min(cpm_values, key=lambda item: item[1], default=None)
    cpm_max = max(cpm_values, key=lambda item: item[1], default=None)

    return {
        "firstDay": first,
        "lastDay": last,
        "daysWithData": len(days),
        "calendarDays": calendar_days,
        "missingDays": max(0, calendar_days - len(days)),
        "totalCost": total_cost,
        "totalTokens": total_tokens,
        "outputTokens": sum(day["outputTokens"] for day in days),
        "cacheReadTokens": sum(day["cacheReadTokens"] for day in days),
        "meanCostPerDay": total_cost / len(days) if days else None,
        "medianCostPerDay": _median(costs),
        "minCostDay": (
            {"date": min_day["date"], "value": min_day["totalCost"]} if min_day else None
        ),
        "maxCostDay": (
            {
                "date": max_day["date"],
                "value": max_day["totalCost"],
                "totalTokens": max_day["totalTokens"],
            }
            if max_day
            else None
        ),
        "costPerMillionTokens": _cost_per_million(total_cost, total_tokens),
        "medianCostPerMillionTokens": _median([v for _, v in cpm_values]),
        "minCostPerMillionTokens": (
            {"date": cpm_min[0], "value": cpm_min[1]} if cpm_min else None
        ),
        "maxCostPerMillionTokens": (
            {"date": cpm_max[0], "value": cpm_max[1]} if cpm_max else None
        ),
        "contextReloadFactor": _ratio(
            sum(day["cacheReadTokens"] for day in days),
            sum(day["outputTokens"] for day in days),
        ),
    }


def projection(days: list[dict]) -> dict | None:
    """Hochrechnung des letzten, noch unvollstaendigen Monats.

    Ausdruecklich eine Schaetzung auf Basis des bisherigen Tagesmittels, keine
    Trendextrapolation.
    """
    if not days:
        return None
    last_month = days[-1]["month"]
    month_days = [d for d in days if d["month"] == last_month]
    year, month = int(last_month[:4]), int(last_month[5:7])
    days_in_month = calendar.monthrange(year, month)[1]
    observed_days = len({d["date"] for d in month_days})
    if observed_days == 0 or observed_days >= days_in_month:
        return None
    actual_cost = sum(d["totalCost"] for d in month_days)
    mean_cost = actual_cost / observed_days
    return {
        "month": last_month,
        "daysWithData": observed_days,
        "daysInMonth": days_in_month,
        "actualCost": actual_cost,
        "meanCostPerDay": mean_cost,
        "projectedCost": mean_cost * days_in_month,
        "basisCode": "ui.projection.basis",
        "isEstimate": True,
    }


# --------------------------------------------------------------------------
# Sammelaufruf
# --------------------------------------------------------------------------

def compute_metrics(
    days: list[dict],
    date_from: str | None = None,
    date_to: str | None = None,
    models: list[str] | None = None,
) -> dict:
    selected = filter_days(days, date_from, date_to, models)
    per_model = model_totals(selected)
    return {
        "filter": {
            "from": date_from,
            "to": date_to,
            "models": sorted(models) if models else [],
        },
        "summary": summary(selected),
        "months": monthly_totals(selected),
        "cumulativeByMonth": cumulative_by_month(selected),
        "dailySeries": daily_series(selected),
        "stackedByModel": stacked_by_model(selected),
        "models": per_model,
        "pareto": pareto(per_model),
        "timeline": model_timeline(per_model),
        "topDays": top_days(selected),
        "projection": projection(selected),
    }

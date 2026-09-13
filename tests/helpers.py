"""Gemeinsame Testhilfen: Pfade und synthetische Monatsdateien."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

_real_data = os.environ.get("TOKEN_DASHBOARD_REAL_DATA", "").strip()

# Bewusst None und nicht Path(""): ein leerer Pfad ist das aktuelle
# Verzeichnis und besteht jeden is_dir()-Test. Die Referenztests liefen dann
# gegen das Repo-Wurzelverzeichnis und meldeten Unsinn, statt sich zu
# ueberspringen.
REAL_DATA_DIR = Path(_real_data).expanduser() if _real_data else None


def require_real_data() -> Path:
    """Gibt das echte Datenverzeichnis zurueck oder ueberspringt den Test."""
    if REAL_DATA_DIR is None:
        raise unittest.SkipTest(
            "TOKEN_DASHBOARD_REAL_DATA ist nicht gesetzt; "
            "Referenztests uebersprungen."
        )
    if not REAL_DATA_DIR.is_dir():
        raise unittest.SkipTest(f"Datenverzeichnis fehlt: {REAL_DATA_DIR}")
    return REAL_DATA_DIR


def breakdown(model, inp, out, cc, cr, cost):
    return {
        "modelName": model,
        "inputTokens": inp,
        "outputTokens": out,
        "cacheCreationTokens": cc,
        "cacheReadTokens": cr,
        "cost": cost,
    }


def old_day(date_str, breakdowns):
    """Eintrag im alten Schema mit ``date``."""
    day = {"date": date_str}
    day.update(_aggregate(breakdowns))
    day["modelsUsed"] = sorted({b["modelName"] for b in breakdowns})
    day["modelBreakdowns"] = breakdowns
    return day


def new_day(date_str, breakdowns, agents=("claude",), agent_rows=None):
    """Eintrag im neuen Schema mit ``period``, ``agent`` und ``metadata``.

    ``agent_rows`` fuellt das seit 09/2026 vorhandene Feld ``agents``:
    Liste von ``(agentname, [breakdowns])``.
    """
    day = {"period": date_str, "agent": "all", "metadata": {"agents": list(agents)}}
    day.update(_aggregate(breakdowns))
    day["modelsUsed"] = sorted({b["modelName"] for b in breakdowns})
    day["modelBreakdowns"] = breakdowns
    if agent_rows is not None:
        day["agents"] = []
        for name, rows in agent_rows:
            entry = {"agent": name}
            entry.update(_aggregate(rows))
            entry["modelsUsed"] = sorted({b["modelName"] for b in rows})
            entry["modelBreakdowns"] = rows
            day["agents"].append(entry)
    return day


def _aggregate(breakdowns):
    fields = ("inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens")
    values = {f: sum(b[f] for b in breakdowns) for f in fields}
    values["totalTokens"] = sum(values[f] for f in fields)
    values["totalCost"] = sum(b["cost"] for b in breakdowns)
    return values


def write_projects(directory: Path, month: str, mapping: dict, totals=None):
    """Schreibt projects/<month>.json aus {projektschluessel: [tage]}."""
    sub = Path(directory) / "projects"
    sub.mkdir(parents=True, exist_ok=True)
    all_days = [d for days in mapping.values() for d in days]
    if totals is None:
        fields = ("inputTokens", "outputTokens", "cacheCreationTokens",
                  "cacheReadTokens", "totalTokens")
        totals = {f: sum(d[f] for d in all_days) for f in fields}
        totals["totalCost"] = sum(d["totalCost"] for d in all_days)
    payload = {"projects": mapping, "totals": totals}
    path = sub / f"{month}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def project_day(date_str, project, breakdowns):
    """Tageseintrag im projects-Schema."""
    day = {"date": date_str, "project": project}
    day.update(_aggregate(breakdowns))
    day["modelsUsed"] = sorted({b["modelName"] for b in breakdowns})
    day["modelBreakdowns"] = breakdowns
    return day


def write_month(directory: Path, month: str, days: list[dict], totals=None):
    payload = {"daily": days}
    if totals is None:
        fields = ("inputTokens", "outputTokens", "cacheCreationTokens",
                  "cacheReadTokens", "totalTokens")
        totals = {f: sum(d[f] for d in days) for f in fields}
        totals["totalCost"] = sum(d["totalCost"] for d in days)
    payload["totals"] = totals
    path = Path(directory) / f"{month}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_week(directory: Path, subdir: str, week: str, key: str, items: list,
               totals=None):
    """Schreibt <subdir>/<week>.json mit {key: items} und optional totals."""
    sub = Path(directory) / subdir
    sub.mkdir(parents=True, exist_ok=True)
    payload = {key: items}
    if totals is not None:
        payload["totals"] = totals
    path = sub / f"{week}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path

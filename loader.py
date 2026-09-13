# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Einlesen, Normalisieren und Pruefen der Claude-Code-Nutzungsdaten.

Unterstuetzt beide Schema-Varianten der Monatsdateien (``date`` bzw.
``period``) und normalisiert sie auf ein einheitliches internes Format.
"""

from __future__ import annotations

import json
import re
import tomllib
from datetime import date as _date
from pathlib import Path

MONTH_FILE_RE = re.compile(r"^(\d{4})-(\d{2})\.json$")

# Every message key this module can emit. A new message needs an entry here
# and in every catalogue under static/i18n/, otherwise the dashboard shows
# the bare key in angle brackets. tests/test_i18n.py checks both directions.
MESSAGE_CODES = frozenset({
    "source.file.unreadable",
    "source.monthly.daily_missing",
    "source.monthly.bad_date",
    "check.day.token_sum_mismatch",
    "check.day.cost_sum_mismatch",
    "check.file.field_mismatch",
    "check.file.cost_mismatch",
    "check.file.totals_missing",
})

TOKEN_FIELDS = (
    "inputTokens",
    "outputTokens",
    "cacheCreationTokens",
    "cacheReadTokens",
)

DEFAULT_CONFIG = {
    "data": {
        "directory": "~/Library/Application Support/Claude-Code-Usage",
    },
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "open_browser": True,
    },
}

DEFAULT_CONFIG_TEXT = """[data]
directory = "~/Library/Application Support/Claude-Code-Usage"

[server]
host = "127.0.0.1"
port = 8000
open_browser = true
"""

COST_TOLERANCE = 0.01


class ConfigError(Exception):
    """Konfiguration ist unbrauchbar."""


class DataDirectoryError(Exception):
    """Datenverzeichnis fehlt oder enthaelt keine passenden Dateien."""


# --------------------------------------------------------------------------
# Konfiguration
# --------------------------------------------------------------------------

def load_config(config_path: Path) -> tuple[dict, list[str]]:
    """Liest ``config.toml``. Legt sie mit Defaults an, falls sie fehlt.

    Rueckgabe: (Konfiguration, Konsolen-Hinweise). Fehlende Schluessel fallen
    einzeln auf die Defaults zurueck.
    """
    config_path = Path(config_path)
    notes: list[str] = []

    if not config_path.exists():
        config_path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
        notes.append(
            f"HINWEIS: {config_path} war nicht vorhanden und wurde mit "
            f"Standardwerten angelegt. Bitte [data].directory pruefen."
        )

    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"Konfigurationsdatei {config_path} ist kein gueltiges TOML: {exc}"
        ) from exc
    except OSError as exc:
        raise ConfigError(
            f"Konfigurationsdatei {config_path} konnte nicht gelesen werden: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Konfigurationsdatei {config_path} ist unbrauchbar.")

    config = {
        "data": dict(DEFAULT_CONFIG["data"]),
        "server": dict(DEFAULT_CONFIG["server"]),
    }
    for section in ("data", "server"):
        values = raw.get(section)
        if values is None:
            continue
        if not isinstance(values, dict):
            notes.append(
                f"HINWEIS: Abschnitt [{section}] in {config_path} ist kein "
                f"Tabellenabschnitt und wird ignoriert."
            )
            continue
        for key, value in values.items():
            if key in config[section]:
                config[section][key] = value

    port = config["server"]["port"]
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        notes.append(
            f"HINWEIS: [server].port = {port!r} ist ungueltig, verwende "
            f"{DEFAULT_CONFIG['server']['port']}."
        )
        config["server"]["port"] = DEFAULT_CONFIG["server"]["port"]

    if not isinstance(config["server"]["open_browser"], bool):
        config["server"]["open_browser"] = bool(config["server"]["open_browser"])

    return config, notes


def resolve_data_directory(config: dict, config_path: Path) -> Path:
    """Loest ``[data].directory`` relativ zum Ort der ``config.toml`` auf."""
    directory = config.get("data", {}).get("directory")
    if not isinstance(directory, str) or not directory.strip():
        raise ConfigError(
            "In config.toml fehlt ein gueltiger Wert fuer [data].directory."
        )
    path = Path(directory.strip()).expanduser()
    if not path.is_absolute():
        path = (Path(config_path).resolve().parent / path).resolve()
    return path


def find_month_files(directory: Path) -> list[Path]:
    """Alle Dateien im Muster ``YYYY-MM.json``, aufsteigend sortiert."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    return sorted(
        (p for p in directory.iterdir() if p.is_file() and MONTH_FILE_RE.match(p.name)),
        key=lambda p: p.name,
    )


def check_data_directory(directory: Path) -> list[Path]:
    """Prueft das Datenverzeichnis. Kein stiller Fallback."""
    directory = Path(directory)
    if not directory.exists():
        raise DataDirectoryError(
            f"Das konfigurierte Datenverzeichnis existiert nicht: {directory}"
        )
    if not directory.is_dir():
        raise DataDirectoryError(
            f"Der konfigurierte Pfad ist kein Verzeichnis: {directory}"
        )
    files = find_month_files(directory)
    if not files:
        raise DataDirectoryError(
            f"Im Datenverzeichnis {directory} liegt keine Datei im Muster "
            f"YYYY-MM.json."
        )
    return files


# --------------------------------------------------------------------------
# Einlesen und Normalisieren
# --------------------------------------------------------------------------

def _as_int(value) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_breakdown(raw: dict) -> dict:
    entry = {
        "modelName": str(raw.get("modelName") or "unbekannt"),
        "cost": _as_float(raw.get("cost")),
    }
    for field in TOKEN_FIELDS:
        entry[field] = _as_int(raw.get(field))
    entry["totalTokens"] = sum(entry[f] for f in TOKEN_FIELDS)
    entry["agent"] = agent_for_model(entry["modelName"])
    return entry


def agent_for_model(model_name: str) -> str:
    """Modelle mit Praefix ``gpt-`` stammen von Codex, nicht von Claude."""
    return "codex" if str(model_name).startswith("gpt-") else "claude"


def normalize_day(raw: dict, source: str) -> dict | None:
    """Normalisiert einen ``daily``-Eintrag beider Schema-Varianten."""
    if not isinstance(raw, dict):
        return None
    day_date = raw.get("date") or raw.get("period")
    if not isinstance(day_date, str) or not day_date.strip():
        return None
    day_date = day_date.strip()[:10]
    try:
        _date.fromisoformat(day_date)
    except ValueError:
        return None

    breakdowns = raw.get("modelBreakdowns")
    if not isinstance(breakdowns, list):
        breakdowns = []
    normalized_breakdowns = [
        normalize_breakdown(b) for b in breakdowns if isinstance(b, dict)
    ]

    models_used = raw.get("modelsUsed")
    if not isinstance(models_used, list):
        models_used = [b["modelName"] for b in normalized_breakdowns]
    models_used = sorted({str(m) for m in models_used})

    metadata = raw.get("metadata")
    agents = []
    if isinstance(metadata, dict) and isinstance(metadata.get("agents"), list):
        agents = sorted({str(a) for a in metadata["agents"]})
    if not agents:
        agents = sorted({agent_for_model(m) for m in models_used}) or ["claude"]

    agent_rows = raw.get("agents")
    agent_breakdowns = []
    if isinstance(agent_rows, list):
        for entry in agent_rows:
            if not isinstance(entry, dict):
                continue
            agent_breakdowns.append({
                "agent": str(entry.get("agent") or "unbekannt"),
                "totalCost": _as_float(entry.get("totalCost")),
                "totalTokens": _as_int(entry.get("totalTokens")),
            })

    day = {
        "date": day_date,
        "month": day_date[:7],
        "day": int(day_date[8:10]),
        "agent": str(raw.get("agent") or "all"),
        "agents": agents,
        "agentBreakdowns": agent_breakdowns,
        "modelsUsed": models_used,
        "modelBreakdowns": normalized_breakdowns,
        "totalCost": _as_float(raw.get("totalCost")),
        "sourceFile": source,
        "schema": "period" if "period" in raw else "date",
    }
    for field in TOKEN_FIELDS:
        day[field] = _as_int(raw.get(field))
    day["totalTokens"] = _as_int(raw.get("totalTokens"))
    day["sumTokens"] = sum(day[f] for f in TOKEN_FIELDS)
    return day


def normalize_totals(raw) -> dict:
    totals = {field: 0 for field in TOKEN_FIELDS}
    totals["totalTokens"] = 0
    totals["totalCost"] = 0.0
    if isinstance(raw, dict):
        for field in TOKEN_FIELDS:
            totals[field] = _as_int(raw.get(field))
        totals["totalTokens"] = _as_int(raw.get("totalTokens"))
        totals["totalCost"] = _as_float(raw.get("totalCost"))
    return totals


def load_directory(directory: Path) -> dict:
    """Liest alle Monatsdateien ein und normalisiert sie.

    Rueckgabe: ``{"directory", "days", "files", "errors"}``. Dateien ohne
    brauchbares ``daily`` werden zurueckgewiesen und in ``errors`` gemeldet.
    """
    directory = Path(directory)
    files = check_data_directory(directory)

    days: list[dict] = []
    file_infos: list[dict] = []
    errors: list[dict] = []

    for path in files:
        info = {
            "name": path.name,
            "month": path.stem,
            "days": 0,
            "accepted": False,
            "schemas": [],
            "totals": normalize_totals(None),
            "hasTotals": False,
        }
        try:
            with path.open("rb") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({"file": path.name,
                           "code": "source.file.unreadable",
                           "params": {"file": path.name, "reason": str(exc)}})
            file_infos.append(info)
            continue

        if not isinstance(payload, dict) or not isinstance(payload.get("daily"), list):
            errors.append({"file": path.name,
                           "code": "source.monthly.daily_missing",
                           "params": {"file": path.name}})
            file_infos.append(info)
            continue

        file_days = []
        for index, raw_day in enumerate(payload["daily"]):
            day = normalize_day(raw_day, path.name)
            if day is None:
                errors.append({"file": path.name,
                               "code": "source.monthly.bad_date",
                               "params": {"file": path.name, "index": index}})
                continue
            file_days.append(day)

        info["accepted"] = True
        info["days"] = len(file_days)
        info["schemas"] = sorted({d["schema"] for d in file_days})
        info["hasTotals"] = isinstance(payload.get("totals"), dict)
        info["totals"] = normalize_totals(payload.get("totals"))
        file_infos.append(info)
        days.extend(file_days)

    days.sort(key=lambda d: d["date"])
    return {
        "directory": str(directory),
        "days": days,
        "files": file_infos,
        "errors": errors,
    }


# --------------------------------------------------------------------------
# Plausibilitaetspruefung
# --------------------------------------------------------------------------

def check_plausibility(dataset: dict) -> dict:
    """Prueft Tages- und Dateisummen. Ergebnis fuer den Statusbereich im UI."""
    days = dataset["days"]
    issues: list[dict] = []

    token_ok = 0
    cost_ok = 0
    for day in days:
        if day["sumTokens"] == day["totalTokens"]:
            token_ok += 1
        else:
            issues.append({
                "level": "warn", "scope": "day", "key": day["date"],
                "code": "check.day.token_sum_mismatch",
                "params": {
                    "sum": day["sumTokens"],
                    "total": day["totalTokens"],
                    "delta": day["sumTokens"] - day["totalTokens"],
                },
            })
        breakdown_cost = sum(b["cost"] for b in day["modelBreakdowns"])
        if abs(breakdown_cost - day["totalCost"]) <= COST_TOLERANCE:
            cost_ok += 1
        else:
            issues.append({
                "level": "warn", "scope": "day", "key": day["date"],
                "code": "check.day.cost_sum_mismatch",
                "params": {"breakdownCost": breakdown_cost,
                           "totalCost": day["totalCost"]},
            })

    file_checks = []
    for info in dataset["files"]:
        if not info["accepted"]:
            continue
        month_days = [d for d in days if d["sourceFile"] == info["name"]]
        summed = {field: sum(d[field] for d in month_days) for field in TOKEN_FIELDS}
        summed["totalTokens"] = sum(d["totalTokens"] for d in month_days)
        summed["totalCost"] = sum(d["totalCost"] for d in month_days)
        ok = True
        if info["hasTotals"]:
            for field in (*TOKEN_FIELDS, "totalTokens"):
                if summed[field] != info["totals"][field]:
                    ok = False
                    issues.append({
                        "level": "warn", "scope": "file", "key": info["name"],
                        "code": "check.file.field_mismatch",
                        "params": {"field": field, "summed": summed[field],
                                   "total": info["totals"][field]},
                    })
            if abs(summed["totalCost"] - info["totals"]["totalCost"]) > COST_TOLERANCE:
                ok = False
                issues.append({
                    "level": "warn", "scope": "file", "key": info["name"],
                    "code": "check.file.cost_mismatch",
                    "params": {"summed": summed["totalCost"],
                               "total": info["totals"]["totalCost"]},
                })
        else:
            ok = False
            issues.append({
                "level": "warn", "scope": "file", "key": info["name"],
                "code": "check.file.totals_missing",
                "params": {},
            })
        file_checks.append({"file": info["name"], "ok": ok, "sums": summed})

    for error in dataset["errors"]:
        issues.append({
            "level": "error", "scope": "file", "key": error["file"],
            "code": error["code"], "params": error["params"],
        })

    return {
        "directory": dataset["directory"],
        "filesFound": len(dataset["files"]),
        "filesAccepted": sum(1 for f in dataset["files"] if f["accepted"]),
        "filesRejected": sum(1 for f in dataset["files"] if not f["accepted"]),
        "daysLoaded": len(days),
        "tokenSumOk": token_ok,
        "tokenSumFailed": len(days) - token_ok,
        "costSumOk": cost_ok,
        "costSumFailed": len(days) - cost_ok,
        "fileChecks": file_checks,
        "issues": issues,
        "ok": not issues,
    }

#!/usr/bin/env python3
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Token-Usage-Dashboard: lokaler HTTP-Server, nur Standardbibliothek.

Start: ``python3 app.py``
"""

from __future__ import annotations

import json
import mimetypes
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import insights
import loader
import metrics
import sources

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.toml"
STATIC_DIR = BASE_DIR / "static"

# Every message key this module can emit. A new message needs an entry here
# and in every catalogue under static/i18n/, otherwise the dashboard shows
# the bare key in angle brackets. tests/test_i18n.py checks both directions.
MESSAGE_CODES = frozenset({
    "http.path_unknown",
    "http.internal_error",
    "http.file_missing",
    "http.data_directory",
})


class DataStore:
    """Haelt die eingelesenen Daten und laedt bei Aenderungen neu."""

    SUBDIRS = (
        (sources.PROJECT_DIR, sources.MONTH_FILE_RE),
        (sources.BLOCK_DIR, sources.WEEK_FILE_RE),
        (sources.SESSION_DIR, sources.WEEK_FILE_RE),
        (sources.RTK_DIR, sources.MONTH_FILE_RE),
    )

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._dataset: dict | None = None
        self._extras: dict | None = None
        self._health: dict | None = None
        self._fingerprint: tuple | None = None

    def _current_fingerprint(self) -> tuple:
        entries = []
        paths = list(loader.find_month_files(self.directory))
        for subdir, pattern in self.SUBDIRS:
            paths.extend(sources.find_source_files(self.directory, subdir, pattern))
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(entries)

    def get(self, force: bool = False) -> tuple[dict, dict, dict]:
        with self._lock:
            fingerprint = self._current_fingerprint()
            if force or self._dataset is None or fingerprint != self._fingerprint:
                dataset = loader.load_directory(self.directory)
                extras = sources.load_extras(self.directory)
                health = loader.check_plausibility(dataset)
                extra_health = sources.check_extras(extras, dataset["days"])
                extra_errors = [
                    {
                        "level": "error",
                        "scope": error["source"],
                        "key": error["file"],
                        "code": error["code"],
                        "params": error["params"],
                    }
                    for error in extras["errors"]
                ]
                health["issues"] = health["issues"] + extra_health["issues"] + extra_errors
                health["extras"] = extra_health["checks"]
                # Eine Meldung der Stufe "info" benennt einen uebersprungenen
                # Pruefschritt und ist kein Befund. Sie darf den Statusbereich
                # nicht auf "nicht in Ordnung" ziehen.
                health["ok"] = not [i for i in health["issues"]
                                    if i.get("level") != "info"]
                self._dataset = dataset
                self._extras = extras
                self._health = health
                self._fingerprint = fingerprint
            return self._dataset, self._extras, self._health


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "TokenDashboard/1.0"
    store: DataStore

    # -- Ausgabe ----------------------------------------------------------
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        sys.stderr.write(
            "%s - %s\n" % (self.address_string(), format % args)
        )

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send_error_json(self, status: int, code: str, params: dict) -> None:
        """Send an error as a message key plus raw parameters.

        The browser is the only side that knows the active language, so the
        server never assembles a sentence.
        """
        body = json.dumps({"code": code, "params": params}).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    # -- Routing ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        try:
            if path in ("/", "/index.html"):
                self._serve_static("index.html")
            elif path.startswith("/static/"):
                self._serve_static(path[len("/static/") :])
            elif path == "/LICENSE":
                self._serve_license()
            elif path == "/api/data":
                self._api_data(query)
            elif path == "/api/metrics":
                self._api_metrics(query)
            elif path == "/api/health":
                self._api_health(query)
            elif path == "/api/projects":
                self._api_projects(query)
            elif path == "/api/sessions":
                self._api_sessions(query)
            elif path == "/api/blocks":
                self._api_blocks(query)
            elif path == "/api/rtk":
                self._api_rtk(query)
            else:
                self._send_error_json(404, "http.path_unknown", {"path": path})
        except loader.DataDirectoryError as exc:
            # The exception text stays German by design: only whoever edits
            # the configuration ever sees it.
            self._send_error_json(500, "http.data_directory",
                                  {"reason": str(exc)})
        except BrokenPipeError:
            pass
        except Exception as exc:  # pragma: no cover - Schutznetz
            self._send_error_json(500, "http.internal_error",
                                  {"reason": str(exc)})

    do_HEAD = do_GET

    # -- Statische Dateien ------------------------------------------------
    def _serve_static(self, relative: str) -> None:
        target = (STATIC_DIR / relative).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self._send_error_json(404, "http.file_missing", {"file": relative})
            return
        content_type, _ = mimetypes.guess_type(target.name)
        if content_type and content_type.startswith("text/"):
            content_type += "; charset=utf-8"
        self._send(200, target.read_bytes(), content_type or "application/octet-stream")

    def _serve_license(self) -> None:
        """Liefert den Lizenztext aus. § 13 AGPL verlangt, dass die Nutzer der
        laufenden Anwendung an den Quelltext und die Lizenz herankommen; die
        Datei liegt im Wurzelverzeichnis und nicht unter ``static/``, deshalb
        eine eigene Route statt eines zweiten Fundorts."""
        target = BASE_DIR / "LICENSE"
        if not target.is_file():
            self._send_error_json(404, "http.file_missing", {"file": "LICENSE"})
            return
        self._send(200, target.read_bytes(), "text/plain; charset=utf-8")

    # -- API --------------------------------------------------------------
    @staticmethod
    def _flag(query: dict, name: str) -> bool:
        return query.get(name, ["0"])[0].lower() in ("1", "true", "yes", "ja")

    @staticmethod
    def _param(query: dict, name: str) -> str | None:
        value = query.get(name, [""])[0].strip()
        return value or None

    @staticmethod
    def _models(query: dict) -> list[str] | None:
        raw = query.get("models", [])
        names = []
        for item in raw:
            names.extend(part for part in item.split(",") if part.strip())
        return sorted({n.strip() for n in names}) or None

    def _api_data(self, query: dict) -> None:
        dataset, extras, health = self.store.get(force=self._flag(query, "reload"))
        self._send_json(
            {
                "directory": dataset["directory"],
                "days": dataset["days"],
                "files": dataset["files"],
                "errors": dataset["errors"],
                "models": metrics.available_models(dataset["days"]),
                "months": sorted({d["month"] for d in dataset["days"]}),
                "range": dict(
                    zip(("from", "to"), metrics.date_range(dataset["days"]))
                ),
                "health": health,
            }
        )

    def _api_metrics(self, query: dict) -> None:
        dataset, _, _ = self.store.get(force=self._flag(query, "reload"))
        date_from = self._param(query, "from")
        date_to = self._param(query, "to")
        selected_models = self._models(query)
        result = metrics.compute_metrics(
            dataset["days"],
            date_from=date_from,
            date_to=date_to,
            models=selected_models,
        )
        result["directory"] = dataset["directory"]
        result["availableModels"] = metrics.available_models(dataset["days"])
        result["availableMonths"] = sorted({d["month"] for d in dataset["days"]})
        result["agentSplit"] = insights.agent_series(
            sources.agent_split(
                metrics.filter_days(
                    dataset["days"],
                    date_from=date_from,
                    date_to=date_to,
                    models=selected_models,
                ),
                prefer_agents=not selected_models,
            )
        )
        self._send_json(result)

    def _api_health(self, query: dict) -> None:
        _, _, health = self.store.get(force=self._flag(query, "reload"))
        self._send_json(health)

    def _api_projects(self, query: dict) -> None:
        _, extras, _ = self.store.get(force=self._flag(query, "reload"))
        self._send_json(insights.project_insights(
            extras["projects"]["rows"],
            date_from=self._param(query, "from"),
            date_to=self._param(query, "to"),
            models=self._models(query),
        ))

    def _api_sessions(self, query: dict) -> None:
        _, extras, _ = self.store.get(force=self._flag(query, "reload"))
        self._send_json(insights.session_insights(
            extras["sessions"]["rows"],
            date_from=self._param(query, "from"),
            date_to=self._param(query, "to"),
            models=self._models(query),
        ))

    def _api_blocks(self, query: dict) -> None:
        _, extras, _ = self.store.get(force=self._flag(query, "reload"))
        self._send_json(insights.block_insights(
            extras["blocks"]["rows"],
            date_from=self._param(query, "from"),
            date_to=self._param(query, "to"),
        ))

    def _api_rtk(self, query: dict) -> None:
        _, extras, _ = self.store.get(force=self._flag(query, "reload"))
        self._send_json(insights.rtk_insights(
            extras["rtk"]["rows"],
            date_from=self._param(query, "from"),
            date_to=self._param(query, "to"),
        ))


def build_server(directory: Path, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (DashboardHandler,), {"store": DataStore(directory)})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    try:
        config, notes = loader.load_config(CONFIG_PATH)
    except loader.ConfigError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    for note in notes:
        print(note)

    try:
        directory = loader.resolve_data_directory(config, CONFIG_PATH)
        files = loader.check_data_directory(directory)
    except (loader.ConfigError, loader.DataDirectoryError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        print(f"Geprueft wurde der Pfad aus {CONFIG_PATH}.", file=sys.stderr)
        return 2

    host = str(config["server"]["host"])
    port = int(config["server"]["port"])

    try:
        server = build_server(directory, host, port)
    except OSError as exc:
        print(f"FEHLER: Server konnte nicht auf {host}:{port} starten: {exc}",
              file=sys.stderr)
        return 2

    url = f"http://{host}:{server.server_port}/"
    print(f"Datenverzeichnis: {directory}")
    print(f"Gefundene Monatsdateien: {len(files)}")
    print(f"Dashboard laeuft auf {url}")
    print("Beenden mit Strg+C")

    if config["server"]["open_browser"]:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests fuer HTTP-Server, API-Endpunkte und Start ohne gueltiges Verzeichnis."""

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tests.helpers import (
    breakdown,
    new_day,
    old_day,
    project_day,
    write_month,
    write_projects,
    write_week,
)

import app
import loader


def get(url):
    with urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        write_month(cls.tmp, "2026-05", [
            old_day("2026-05-01", [breakdown("claude-opus-5", 1, 100, 10, 900, 12.0)]),
            old_day("2026-05-03", [breakdown("claude-sonnet-5", 1, 50, 10, 400, 4.0)]),
        ])
        write_month(cls.tmp, "2026-06", [
            new_day("2026-06-01", [
                breakdown("claude-opus-5", 1, 100, 10, 900, 20.0),
                breakdown("gpt-5.6-sol", 1, 20, 5, 100, 2.0),
            ]),
        ])
        cls.server = app.build_server(cls.tmp, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()

    def test_index_is_served(self):
        with urlopen(self.base + "/", timeout=5) as response:
            body = response.read().decode("utf-8")
        self.assertIn("Token-Usage-Dashboard", body)
        self.assertIn("/static/app.js", body)

    def test_static_files_are_served(self):
        for path in ("/static/style.css", "/static/app.js"):
            with urlopen(self.base + path, timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())

    def test_lizenz_wird_ausgeliefert(self):
        with urlopen(self.base + "/LICENSE", timeout=5) as antwort:
            self.assertEqual(antwort.status, 200)
            text = antwort.read().decode("utf-8")
        self.assertIn("GNU AFFERO GENERAL PUBLIC LICENSE", text)

    def test_static_path_traversal_is_blocked(self):
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self.base + "/static/../app.py", timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_api_data(self):
        payload = get(self.base + "/api/data")
        self.assertEqual(len(payload["days"]), 3)
        self.assertEqual(payload["directory"], str(self.tmp))
        self.assertEqual(payload["months"], ["2026-05", "2026-06"])
        self.assertEqual(
            payload["models"], ["claude-opus-5", "claude-sonnet-5", "gpt-5.6-sol"]
        )
        self.assertEqual(payload["range"], {"from": "2026-05-01", "to": "2026-06-01"})
        self.assertIn("health", payload)

    def test_api_health(self):
        payload = get(self.base + "/api/health")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["daysLoaded"], 3)
        self.assertEqual(payload["directory"], str(self.tmp))

    def test_api_metrics_without_filter(self):
        payload = get(self.base + "/api/metrics")
        self.assertAlmostEqual(payload["summary"]["totalCost"], 38.0)
        self.assertEqual(len(payload["months"]), 2)
        self.assertEqual(len(payload["dailySeries"]["labels"]), 32)

    def test_api_metrics_with_date_filter(self):
        payload = get(self.base + "/api/metrics?from=2026-05-01&to=2026-05-31")
        self.assertAlmostEqual(payload["summary"]["totalCost"], 16.0)

    def test_api_metrics_with_model_filter(self):
        payload = get(self.base + "/api/metrics?models=claude-opus-5,gpt-5.6-sol")
        self.assertAlmostEqual(payload["summary"]["totalCost"], 34.0)
        self.assertEqual(
            sorted(m["model"] for m in payload["models"]),
            ["claude-opus-5", "gpt-5.6-sol"],
        )

    def test_unknown_path_returns_json_error(self):
        with self.assertRaises(HTTPError) as ctx:
            urlopen(self.base + "/api/gibtsnicht", timeout=5)
        self.assertEqual(ctx.exception.code, 404)
        payload = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertEqual(payload["code"], "http.path_unknown")
        self.assertNotIn("error", payload)

    def test_unbekannter_pfad_liefert_schluessel_statt_satz(self):
        request = Request(self.base + "/api/gibtsnicht")
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request)
        payload = json.loads(ctx.exception.read())
        self.assertEqual(ctx.exception.code, 404)
        self.assertEqual(payload["code"], "http.path_unknown")
        self.assertEqual(payload["params"], {"path": "/api/gibtsnicht"})
        self.assertNotIn("error", payload)

    def test_new_file_appears_after_reload(self):
        before = get(self.base + "/api/data")
        self.assertNotIn("2026-07", before["months"])

        write_month(self.tmp, "2026-07", [
            new_day("2026-07-04", [breakdown("claude-fable-5", 1, 10, 5, 80, 7.5)]),
        ])
        after = get(self.base + "/api/data?reload=1")
        self.assertIn("2026-07", after["months"])
        self.assertIn("claude-fable-5", after["models"])

        metrics_payload = get(self.base + "/api/metrics?reload=1")
        self.assertAlmostEqual(metrics_payload["summary"]["totalCost"], 45.5)

        (self.tmp / "2026-07.json").unlink()
        get(self.base + "/api/data?reload=1")


class RejectedFileServingTests(unittest.TestCase):
    def test_rejected_file_is_reported_through_the_api(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            write_month(directory, "2026-05", [
                old_day("2026-05-01", [breakdown("claude-opus-5", 1, 10, 10, 100, 1.0)]),
            ])
            (directory / "2026-06.json").write_text('{"totals": {}}', encoding="utf-8")

            server = app.build_server(directory, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                payload = get(f"http://127.0.0.1:{server.server_port}/api/health")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertFalse(payload["ok"])
            self.assertEqual(payload["filesRejected"], 1)
            self.assertTrue(
                any(i["key"] == "2026-06.json" and i["level"] == "error"
                    for i in payload["issues"])
            )


class StartupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._original = app.CONFIG_PATH

    def tearDown(self):
        app.CONFIG_PATH = self._original

    def _run_main(self, config_text=None):
        config_path = self.tmp / "config.toml"
        if config_text is not None:
            config_path.write_text(config_text, encoding="utf-8")
        app.CONFIG_PATH = config_path
        return app.main([])

    def test_missing_data_directory_aborts_with_code_two(self):
        missing = self.tmp / "gibtsnicht"
        code = self._run_main(f'[data]\ndirectory = "{missing}"\n')
        self.assertEqual(code, 2)

    def test_empty_data_directory_aborts(self):
        empty = self.tmp / "leer"
        empty.mkdir()
        self.assertEqual(self._run_main(f'[data]\ndirectory = "{empty}"\n'), 2)

    def test_broken_config_aborts(self):
        self.assertEqual(self._run_main("[data\n"), 2)

    def test_single_month_file_starts_and_serves(self):
        data_dir = self.tmp / "daten"
        data_dir.mkdir()
        write_month(data_dir, "2026-05", [
            old_day("2026-05-01", [breakdown("claude-opus-5", 1, 10, 10, 100, 1.0)]),
        ])
        server = app.build_server(data_dir, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = get(f"http://127.0.0.1:{server.server_port}/api/metrics")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertEqual(payload["summary"]["daysWithData"], 1)

    def test_directory_switch_via_config(self):
        first = self.tmp / "eins"
        second = self.tmp / "zwei"
        for directory, cost in ((first, 1.0), (second, 5.0)):
            directory.mkdir()
            write_month(directory, "2026-05", [
                old_day("2026-05-01", [breakdown("claude-opus-5", 1, 10, 10, 100, cost)]),
            ])

        config_path = self.tmp / "config.toml"
        for directory, expected in ((first, 1.0), (second, 5.0)):
            config_path.write_text(f'[data]\ndirectory = "{directory}"\n', encoding="utf-8")
            config, _ = loader.load_config(config_path)
            resolved = loader.resolve_data_directory(config, config_path)
            self.assertEqual(resolved, directory)
            dataset = loader.load_directory(resolved)
            self.assertAlmostEqual(dataset["days"][0]["totalCost"], expected)


class SkippedCrossCheckTests(unittest.TestCase):
    """blocks/ ohne passende sessions/: die Gegenprobe faellt aus."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        directory = Path(cls._tmp.name)
        bd = [breakdown("claude-opus-5", 1, 2000, 30, 4000, 12.0)]
        write_month(directory, "2026-09", [new_day("2026-09-01", bd)])
        write_week(directory, "blocks", "2026-W37", "blocks", [{
            "id": "2026-09-08T10:00:00.000Z",
            "startTime": "2026-09-08T10:00:00.000Z",
            "endTime": "2026-09-08T15:00:00.000Z",
            "actualEndTime": "2026-09-08T11:00:00.000Z",
            "isActive": False, "isGap": False, "entries": 10,
            "costUSD": 12.0, "totalTokens": 6031, "models": ["claude-opus-5"],
            "tokenCounts": {"inputTokens": 1, "outputTokens": 2000,
                            "cacheCreationInputTokens": 30,
                            "cacheReadInputTokens": 4000},
        }])
        cls.server = app.build_server(directory, "127.0.0.1", 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls._tmp.cleanup()

    def test_uebersprungene_gegenprobe_ist_info_und_haelt_health_ok(self):
        health = get(self.base + "/api/health")
        levels = {i["level"] for i in health["issues"]}
        self.assertEqual(levels, {"info"})
        self.assertEqual(health["issues"][0]["code"], "check.weekrun.skipped")
        self.assertTrue(
            health["ok"],
            "Eine reine info-Meldung ist kein Befund und darf den "
            "Statusbereich nicht auf nicht in Ordnung ziehen.")


class ExtraSourceApiTests(unittest.TestCase):
    """Server mit Monatsdatei plus projects/, sessions/, blocks/."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        directory = Path(cls.tmp.name)
        bd = [breakdown("claude-opus-5", 1, 2000, 30, 4000, 12.0)]
        write_month(directory, "2026-09", [new_day("2026-09-01", bd)])
        write_projects(directory, "2026-09", {
            "-home-du-projekte-alpha": [
                project_day("2026-09-01", "-home-du-projekte-alpha", bd),
            ],
        })
        write_week(directory, "sessions", "2026-W36", "sessions", [{
            "sessionId": "s1", "projectPath": "-home-du-projekte-alpha",
            "firstActivity": "2026-09-01T10:00:00.000Z",
            "lastActivity": "2026-09-01T11:00:00.000Z",
            "inputTokens": 1, "outputTokens": 2000,
            "cacheCreationTokens": 30, "cacheReadTokens": 4000,
            "totalTokens": 6031, "totalCost": 12.0,
            "modelsUsed": ["claude-opus-5"], "modelBreakdowns": bd,
        }])
        write_week(directory, "blocks", "2026-W36", "blocks", [{
            "id": "2026-09-01T10:00:00.000Z",
            "startTime": "2026-09-01T10:00:00.000Z",
            "endTime": "2026-09-01T15:00:00.000Z",
            "actualEndTime": "2026-09-01T11:00:00.000Z",
            "isActive": False, "isGap": False, "entries": 10,
            "costUSD": 12.0, "totalTokens": 6031, "models": ["claude-opus-5"],
            "tokenCounts": {"inputTokens": 1, "outputTokens": 2000,
                            "cacheCreationInputTokens": 30,
                            "cacheReadInputTokens": 4000},
            "burnRate": {"costPerHour": 12.0, "tokensPerMinute": 100.0},
            "projection": None,
        }])
        write_week(directory, "rtk", "2026-09", "days", [{
            "date": "2026-09-01", "commands": 10, "input_tokens": 10000,
            "output_tokens": 5000, "saved_tokens": 4000, "savings_pct": 40.0,
            "total_time_ms": 500, "avg_time_ms": 50,
        }])
        cls.server = app.build_server(directory, "127.0.0.1", 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def test_api_projects(self):
        payload = get(self.base + "/api/projects")
        self.assertEqual(payload["kpis"]["projectCount"], 1)
        self.assertEqual(payload["table"][0]["projectLabel"], "alpha")
        self.assertIn("coverage", payload)
        self.assertTrue(payload["coverage"]["complete"])

    def test_api_sessions(self):
        payload = get(self.base + "/api/sessions")
        self.assertEqual(payload["kpis"]["sessionCount"], 1)
        self.assertEqual(payload["top"][0]["sessionId"], "s1")
        self.assertEqual(len(payload["histogram"]["counts"]), 6)
        self.assertEqual(len(payload["histogram"]["bounds"]), 5)

    def test_api_blocks(self):
        payload = get(self.base + "/api/blocks")
        self.assertEqual(payload["kpis"]["blockCount"], 1)
        self.assertFalse(payload["modelFilterSupported"])
        self.assertIsNone(payload["active"])

    def test_api_rtk(self):
        payload = get(self.base + "/api/rtk")
        self.assertEqual(payload["kpis"]["savedTokens"], 4000)
        self.assertFalse(payload["modelFilterSupported"])
        self.assertIn("coverage", payload)

    def test_api_rtk_nimmt_from_to(self):
        payload = get(self.base + "/api/rtk?from=2026-09-02")
        self.assertIsNone(payload["kpis"]["savedTokens"])
        self.assertFalse(payload["coverage"]["complete"])

    def test_api_rtk_ignoriert_models(self):
        mit_models = get(self.base + "/api/rtk?models=claude-opus-5")
        ohne_models = get(self.base + "/api/rtk")
        self.assertEqual(mit_models, ohne_models)

    def test_api_rtk_reload_funktioniert(self):
        payload = get(self.base + "/api/rtk?reload=1")
        self.assertEqual(payload["kpis"]["savedTokens"], 4000)

    def test_zeitraumfilter_wirkt(self):
        payload = get(self.base + "/api/projects?from=2026-09-02")
        self.assertEqual(payload["kpis"]["projectCount"], 0)
        self.assertFalse(payload["coverage"]["complete"])
        self.assertNotEqual(payload["coverage"]["noteCode"], "")

    def test_metrics_traegt_agentsplit(self):
        payload = get(self.base + "/api/metrics")
        self.assertIn("agentSplit", payload)
        self.assertEqual(payload["agentSplit"]["labels"], ["2026-09-01"])

    def test_health_traegt_extras(self):
        payload = get(self.base + "/api/health")
        self.assertIn("extras", payload)
        self.assertEqual(payload["extras"]["projectFiles"], 1)
        self.assertEqual(payload["extras"]["blockRows"], 1)

    def test_neue_blockdatei_wird_nach_reload_gefunden(self):
        directory = Path(self.tmp.name)
        write_week(directory, "blocks", "2026-W37", "blocks", [{
            "id": "2026-09-08T10:00:00.000Z",
            "startTime": "2026-09-08T10:00:00.000Z",
            "endTime": "2026-09-08T15:00:00.000Z",
            "actualEndTime": "2026-09-08T11:00:00.000Z",
            "isActive": False, "isGap": False, "entries": 1,
            "costUSD": 1.0, "totalTokens": 4, "models": ["claude-opus-5"],
            "tokenCounts": {"inputTokens": 1, "outputTokens": 1,
                            "cacheCreationInputTokens": 1,
                            "cacheReadInputTokens": 1},
        }])
        payload = get(self.base + "/api/blocks?reload=1")
        self.assertEqual(payload["kpis"]["blockCount"], 2)


class RtkFingerprintTests(unittest.TestCase):
    """Der vierte SUBDIRS-Eintrag: neue rtk/-Dateien muessen den Fingerprint aendern."""

    def test_neue_rtk_datei_aendert_fingerprint_ohne_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_month(directory, "2026-09", [
                new_day("2026-09-01", [breakdown("claude-opus-5", 1, 100, 10, 900, 1.0)]),
            ])
            write_week(directory, "rtk", "2026-09", "days", [{
                "date": "2026-09-01", "commands": 10, "input_tokens": 10000,
                "output_tokens": 5000, "saved_tokens": 4000, "savings_pct": 40.0,
                "total_time_ms": 500, "avg_time_ms": 50,
            }])
            store = app.DataStore(directory)
            store.get()

            write_week(directory, "rtk", "2026-10", "days", [{
                "date": "2026-10-01", "commands": 1, "input_tokens": 100,
                "output_tokens": 50, "saved_tokens": 40, "savings_pct": 40.0,
                "total_time_ms": 5, "avg_time_ms": 5,
            }])
            _, extras, _ = store.get()

            self.assertEqual(len(extras["rtk"]["rows"]), 2)


class ExtraSourceErrorTests(unittest.TestCase):
    """Eigener Serverlauf: eine kaputte Zusatzquellendatei darf nicht stillschweigend verschwinden."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        directory = Path(cls.tmp.name)
        write_month(directory, "2026-09", [
            new_day("2026-09-01", [breakdown("claude-opus-5", 1, 100, 10, 900, 1.0)]),
        ])
        # projects-Datei ohne Feld 'projects': strukturell falsch, muss als
        # Fehler gemeldet werden statt still uebersprungen zu werden.
        sub = directory / "projects"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "2026-09.json").write_text('{"totals": {}}', encoding="utf-8")

        cls.server = app.build_server(directory, "127.0.0.1", 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def test_kaputte_zusatzquelle_erscheint_in_health(self):
        payload = get(self.base + "/api/health")
        self.assertFalse(payload["ok"])
        self.assertTrue(
            any(i["level"] == "error" and i["scope"] == "projects"
                and i["key"] == "2026-09.json" for i in payload["issues"])
        )


if __name__ == "__main__":
    unittest.main()

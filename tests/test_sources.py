"""Tests fuer sources.py: Einlesen der daily- und weekly-Zusatzquellen."""

from __future__ import annotations

import contextlib
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers import (  # noqa: F401 - setzt sys.path
    BASE_DIR, breakdown, new_day, project_day, write_projects, write_week,
)

import insights
import loader
import sources

NEEDS_TZSET = unittest.skipUnless(
    hasattr(time, "tzset"), "time.tzset() gibt es auf dieser Plattform nicht.")


@contextlib.contextmanager
def fixed_timezone(name: str):
    """Setzt die Zeitzone des Prozesses fest und stellt sie danach zurueck.

    Ohne das haengt jede Aussage ueber ein Ortszeit-Datum an der Zeitzone der
    ausfuehrenden Maschine und der Test belegt nichts.
    """
    previous = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


class LabelTests(unittest.TestCase):
    def test_gemeinsames_praefix_faellt_weg(self):
        keys = [
            "-home-devuser-projekte-alpha",
            "-home-devuser-projekte-beta-tool",
            "-home-devuser-ablage-export-daten",
        ]
        self.assertEqual(
            sources.assign_labels(keys),
            {
                "-home-devuser-projekte-alpha": "projekte-alpha",
                "-home-devuser-projekte-beta-tool": "projekte-beta-tool",
                "-home-devuser-ablage-export-daten": "ablage-export-daten",
            },
        )

    def test_bindestrich_im_verzeichnisnamen_bleibt_erhalten(self):
        keys = [
            "-home-du-projekte-beta-tool",
            "-home-du-projekte-alpha",
        ]
        self.assertEqual(
            sources.assign_labels(keys)["-home-du-projekte-beta-tool"],
            "beta-tool",
        )

    def test_einzelnes_projekt_behaelt_letztes_segment(self):
        keys = ["-home-devuser-projekte-alpha"]
        self.assertEqual(sources.assign_labels(keys), {keys[0]: "alpha"})

    def test_leere_liste(self):
        self.assertEqual(sources.assign_labels([]), {})


class FindFilesTests(unittest.TestCase):
    def test_findet_nur_passende_dateien_sortiert(self):
        with TemporaryDirectory() as tmp:
            sub = Path(tmp) / "blocks"
            sub.mkdir()
            for name in ("2026-W36.json", "2026-W35.json", "notiz.txt",
                         "2026-09.json"):
                (sub / name).write_text("{}", encoding="utf-8")
            found = sources.find_source_files(
                Path(tmp), "blocks", sources.WEEK_FILE_RE
            )
            self.assertEqual([p.name for p in found],
                             ["2026-W35.json", "2026-W36.json"])

    def test_fehlendes_verzeichnis_ist_kein_fehler(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(
                sources.find_source_files(Path(tmp), "blocks",
                                          sources.WEEK_FILE_RE),
                [],
            )


class LoadProjectsTests(unittest.TestCase):
    def _fixture(self, tmp):
        write_projects(Path(tmp), "2026-09", {
            "-home-du-projekte-alpha": [
                project_day("2026-09-01", "-home-du-projekte-alpha",
                            [breakdown("claude-opus-5", 10, 100, 20, 30, 2.5)]),
                project_day("2026-09-02", "-home-du-projekte-alpha",
                            [breakdown("gpt-5.6-sol", 1, 10, 2, 3, 0.5)]),
            ],
            "-home-du-projekte-beta-tool": [
                project_day("2026-09-01", "-home-du-projekte-beta-tool",
                            [breakdown("claude-sonnet-5", 5, 50, 10, 15, 1.0)]),
            ],
        })

    def test_flache_zeilen_mit_label(self):
        with TemporaryDirectory() as tmp:
            self._fixture(tmp)
            result = sources.load_projects(Path(tmp))
            self.assertEqual(len(result["rows"]), 3)
            self.assertEqual(result["errors"], [])
            labels = {r["projectLabel"] for r in result["rows"]}
            self.assertEqual(labels, {"alpha", "beta-tool"})
            first = result["rows"][0]
            self.assertEqual(first["date"], "2026-09-01")
            self.assertEqual(first["month"], "2026-09")
            self.assertEqual(first["sourceFile"], "2026-09.json")
            self.assertEqual(first["sumTokens"], first["totalTokens"])

    def test_zeilen_sind_nach_datum_sortiert(self):
        with TemporaryDirectory() as tmp:
            self._fixture(tmp)
            dates = [r["date"] for r in sources.load_projects(Path(tmp))["rows"]]
            self.assertEqual(dates, sorted(dates))

    def test_breakdowns_bekommen_agent(self):
        with TemporaryDirectory() as tmp:
            self._fixture(tmp)
            rows = sources.load_projects(Path(tmp))["rows"]
            agents = {b["agent"] for r in rows for b in r["modelBreakdowns"]}
            self.assertEqual(agents, {"claude", "codex"})

    def test_fehlendes_verzeichnis_liefert_leer(self):
        with TemporaryDirectory() as tmp:
            result = sources.load_projects(Path(tmp))
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["errors"], [])

    def test_kaputte_datei_wird_gemeldet(self):
        with TemporaryDirectory() as tmp:
            sub = Path(tmp) / "projects"
            sub.mkdir()
            (sub / "2026-09.json").write_text("{kein json", encoding="utf-8")
            result = sources.load_projects(Path(tmp))
            self.assertEqual(result["rows"], [])
            self.assertEqual(len(result["errors"]), 1)
            self.assertIn("2026-09.json", result["errors"][0]["file"])

    def test_fehlendes_feld_projects_wird_gemeldet(self):
        with TemporaryDirectory() as tmp:
            sub = Path(tmp) / "projects"
            sub.mkdir()
            (sub / "2026-09.json").write_text('{"totals": {}}', encoding="utf-8")
            result = sources.load_projects(Path(tmp))
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["errors"][0]["code"],
                             "source.projects.not_an_object")
            self.assertFalse(result["files"][0]["accepted"])

    def test_eintrag_ohne_datum_wird_uebersprungen(self):
        with TemporaryDirectory() as tmp:
            write_projects(Path(tmp), "2026-09", {
                "-a-b": [
                    {"project": "-a-b", "totalCost": 1.0, "totalTokens": 10,
                     "inputTokens": 1, "outputTokens": 2,
                     "cacheCreationTokens": 3, "cacheReadTokens": 4,
                     "modelsUsed": [], "modelBreakdowns": []},
                ],
            }, totals={"inputTokens": 1, "outputTokens": 2,
                       "cacheCreationTokens": 3, "cacheReadTokens": 4,
                       "totalTokens": 10, "totalCost": 1.0})
            result = sources.load_projects(Path(tmp))
            self.assertEqual(result["rows"], [])
            self.assertEqual(len(result["errors"]), 1)


def _session(sid, project, first, last, cost, breakdowns):
    entry = {"sessionId": sid, "projectPath": project,
             "firstActivity": first, "lastActivity": last}
    entry.update(_aggregate_for_test(breakdowns))
    entry["totalCost"] = cost
    entry["modelsUsed"] = sorted({b["modelName"] for b in breakdowns})
    entry["modelBreakdowns"] = breakdowns
    return entry


def _aggregate_for_test(breakdowns):
    fields = ("inputTokens", "outputTokens", "cacheCreationTokens",
              "cacheReadTokens")
    values = {f: sum(b[f] for b in breakdowns) for f in fields}
    values["totalTokens"] = sum(values[f] for f in fields)
    return values


class LoadSessionsTests(unittest.TestCase):
    def test_normalisiert_dauer_und_label(self):
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "sessions", "2026-W36", "sessions", [
                _session("s1", "-home-du-projekte-alpha",
                         "2026-08-22T16:35:56.679Z", "2026-08-23T05:44:45.421Z",
                         158.06, [breakdown("claude-opus-5", 1, 2, 3, 4, 158.06)]),
                _session("s2", "-home-du-projekte-beta-tool",
                         "2026-09-01T10:00:00.000Z", "2026-09-01T10:30:00.000Z",
                         2.0, [breakdown("claude-sonnet-5", 1, 2, 3, 4, 2.0)]),
            ])
            with fixed_timezone("Europe/Berlin"):
                rows = sources.load_sessions(Path(tmp))["rows"]
            self.assertEqual(len(rows), 2)
            by_id = {r["sessionId"]: r for r in rows}
            self.assertEqual(by_id["s1"]["date"], "2026-08-22")
            self.assertEqual(by_id["s1"]["durationMinutes"], 788)
            self.assertEqual(by_id["s2"]["durationMinutes"], 30)
            self.assertEqual(by_id["s2"]["projectLabel"], "beta-tool")

    def test_doppelte_session_id_letzte_datei_gewinnt(self):
        with TemporaryDirectory() as tmp:
            bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 1.0)]
            write_week(Path(tmp), "sessions", "2026-W35", "sessions", [
                _session("s1", "-a-b", "2026-08-20T00:00:00.000Z",
                         "2026-08-20T01:00:00.000Z", 1.0, bd)])
            write_week(Path(tmp), "sessions", "2026-W36", "sessions", [
                _session("s1", "-a-b", "2026-08-20T00:00:00.000Z",
                         "2026-08-20T02:00:00.000Z", 9.0, bd)])
            rows = sources.load_sessions(Path(tmp))["rows"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["durationMinutes"], 120)
            self.assertEqual(rows[0]["sourceFile"], "2026-W36.json")

    @NEEDS_TZSET
    def test_datum_folgt_der_ortszeit_nicht_der_utc_zeit(self):
        """Gefiltert wird nach dem Ortszeit-Datum, nicht nach dem UTC-Datum.

        Die Tabelle zeigt den Zeitstempel per toLocaleString in Ortszeit. Ohne
        die Umrechnung wuerde eine Session als 22.08. gefiltert, waehrend die
        Tabelle 23.08. anzeigt. Der Zeitstempel selbst bleibt UTC.
        """
        bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 1.0)]
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "sessions", "2026-W36", "sessions", [
                _session("s1", "-a-b", "2026-08-22T23:30:00.000Z",
                         "2026-08-22T23:45:00.000Z", 1.0, bd)])
            with fixed_timezone("Europe/Berlin"):
                berlin = sources.load_sessions(Path(tmp))["rows"][0]
            with fixed_timezone("America/Los_Angeles"):
                west = sources.load_sessions(Path(tmp))["rows"][0]
        self.assertEqual(berlin["date"], "2026-08-23")
        self.assertEqual(west["date"], "2026-08-22")
        self.assertEqual(berlin["first"], "2026-08-22T23:30:00.000Z")
        self.assertEqual(west["first"], "2026-08-22T23:30:00.000Z")

    @NEEDS_TZSET
    def test_session_vom_21_august_aus_w36_faellt_in_den_augustfilter(self):
        """Wochendateien decken nicht die Woche ab, die ihr Name nennt.

        Der Export ruft ``blocks --json -s 20260821`` auf, weshalb
        2026-W36.json Daten ab dem 21.08. traegt. Gefiltert wird deshalb nach
        dem Zeitstempel im Datensatz, nie nach dem Dateinamen. Ein Filter auf
        August muss diese Session finden, obwohl W36 in den September faellt.
        """
        bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 7.0)]
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "sessions", "2026-W36", "sessions", [
                _session("frueh", "-a-b", "2026-08-21T04:13:00.000Z",
                         "2026-08-21T05:00:00.000Z", 7.0, bd),
                _session("spaet", "-a-b", "2026-09-04T17:18:00.000Z",
                         "2026-09-04T17:30:00.000Z", 3.0, bd),
            ])
            with fixed_timezone("Europe/Berlin"):
                rows = sources.load_sessions(Path(tmp))["rows"]
                august = insights.filter_rows(rows, "2026-08-01", "2026-08-31")
        self.assertEqual([r["sessionId"] for r in rows], ["frueh", "spaet"])
        self.assertEqual([r["sourceFile"] for r in rows],
                         ["2026-W36.json", "2026-W36.json"])
        self.assertEqual([r["sessionId"] for r in august], ["frueh"])

    def test_fehlendes_feld_sessions_wird_gemeldet(self):
        with TemporaryDirectory() as tmp:
            sub = Path(tmp) / "sessions"
            sub.mkdir()
            (sub / "2026-W36.json").write_text('{"totals": {}}', encoding="utf-8")
            result = sources.load_sessions(Path(tmp))
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["errors"][0]["code"],
                             "source.week.field_missing")
            self.assertEqual(result["errors"][0]["params"]["field"], "sessions")


class LoadBlocksTests(unittest.TestCase):
    BLOCK = {
        "id": "2026-09-04T13:00:00.000Z",
        "startTime": "2026-09-04T13:00:00.000Z",
        "endTime": "2026-09-04T18:00:00.000Z",
        "actualEndTime": "2026-09-04T17:18:53.931Z",
        "isActive": True,
        "isGap": False,
        "entries": 897,
        "costUSD": 72.70344700000007,
        "totalTokens": 106868524,
        "models": ["claude-opus-5"],
        "tokenCounts": {
            "cacheCreationInputTokens": 4055928,
            "cacheReadInputTokens": 102089149,
            "inputTokens": 1796,
            "outputTokens": 721651,
        },
        "burnRate": {"costPerHour": 16.854133667961634,
                     "tokensPerMinute": 412904.8581868395,
                     "tokensPerMinuteForIndicator": 2795.16147280835},
        "projection": {"remainingMinutes": 41, "totalCost": 84.22,
                       "totalTokens": 123797623},
    }
    GAP = {
        "id": "gap-2026-08-21T02:26:19.934Z",
        "startTime": "2026-08-21T02:26:19.934Z",
        "endTime": "2026-08-21T04:13:42.170Z",
        "actualEndTime": None, "isActive": False, "isGap": True,
        "entries": 0, "costUSD": 0, "totalTokens": 0, "models": [],
        "tokenCounts": {"cacheCreationInputTokens": 0,
                        "cacheReadInputTokens": 0,
                        "inputTokens": 0, "outputTokens": 0},
        "burnRate": None, "projection": None,
    }

    def test_tokencounts_werden_umbenannt(self):
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "blocks", "2026-W36", "blocks", [self.BLOCK])
            row = sources.load_blocks(Path(tmp))["rows"][0]
            self.assertEqual(row["cacheCreationTokens"], 4055928)
            self.assertEqual(row["cacheReadTokens"], 102089149)
            self.assertEqual(row["outputTokens"], 721651)
            self.assertEqual(row["sumTokens"], row["totalTokens"])

    def test_burnrate_und_projection_flach(self):
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "blocks", "2026-W36", "blocks", [self.BLOCK])
            row = sources.load_blocks(Path(tmp))["rows"][0]
            self.assertAlmostEqual(row["burnRateCostPerHour"], 16.8541336, places=5)
            self.assertEqual(row["projectionCost"], 84.22)
            self.assertEqual(row["projectionRemainingMinutes"], 41)
            self.assertTrue(row["isActive"])
            self.assertEqual(row["date"], "2026-09-04")

    def test_gap_bleibt_erhalten_aber_markiert(self):
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "blocks", "2026-W36", "blocks",
                       [self.GAP, self.BLOCK])
            rows = sources.load_blocks(Path(tmp))["rows"]
            self.assertEqual(len(rows), 2)
            self.assertTrue(rows[0]["isGap"])
            self.assertIsNone(rows[0]["burnRateCostPerHour"])

    def test_rows_nach_start_sortiert(self):
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "blocks", "2026-W36", "blocks",
                       [self.BLOCK, self.GAP])
            rows = sources.load_blocks(Path(tmp))["rows"]
            self.assertEqual([r["start"] for r in rows],
                             sorted(r["start"] for r in rows))

    @NEEDS_TZSET
    def test_blockdatum_folgt_der_ortszeit(self):
        """Auch Bloecke werden nach dem Ortszeit-Tag ihres Starts gefiltert."""
        block = dict(self.BLOCK)
        block["id"] = "2026-08-22T23:00:00.000Z"
        block["startTime"] = "2026-08-22T23:00:00.000Z"
        block["endTime"] = "2026-08-23T04:00:00.000Z"
        block["actualEndTime"] = "2026-08-23T01:00:00.000Z"
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "blocks", "2026-W36", "blocks", [block])
            with fixed_timezone("Europe/Berlin"):
                berlin = sources.load_blocks(Path(tmp))["rows"][0]
            with fixed_timezone("America/Los_Angeles"):
                west = sources.load_blocks(Path(tmp))["rows"][0]
        self.assertEqual(berlin["date"], "2026-08-23")
        self.assertEqual(west["date"], "2026-08-22")
        self.assertEqual(berlin["start"], "2026-08-22T23:00:00.000Z")

    def test_fehlendes_feld_blocks_wird_gemeldet(self):
        with TemporaryDirectory() as tmp:
            sub = Path(tmp) / "blocks"
            sub.mkdir()
            (sub / "2026-W36.json").write_text("[]", encoding="utf-8")
            result = sources.load_blocks(Path(tmp))
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["errors"][0]["code"],
                             "source.week.field_missing")
            self.assertEqual(result["errors"][0]["params"]["field"], "blocks")


class LoadRtkTests(unittest.TestCase):
    DAY = {"date": "2026-09-10", "commands": 47, "input_tokens": 44458,
           "output_tokens": 31655, "saved_tokens": 15031,
           "savings_pct": 33.8, "total_time_ms": 193, "avg_time_ms": 4}

    def test_vollstaendige_datei_wird_gelesen(self):
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "rtk", "2026-09", "days", [self.DAY])
            result = sources.load_rtk(Path(tmp))
            self.assertEqual(result["errors"], [])
            self.assertEqual(len(result["rows"]), 1)
            row = result["rows"][0]
            self.assertEqual(row["date"], "2026-09-10")
            self.assertEqual(row["month"], "2026-09")
            self.assertEqual(row["commands"], 47)
            self.assertEqual(row["input_tokens"], 44458)
            self.assertEqual(row["output_tokens"], 31655)
            self.assertEqual(row["saved_tokens"], 15031)
            self.assertEqual(row["savings_pct"], 33.8)
            self.assertEqual(row["total_time_ms"], 193)
            self.assertEqual(row["avg_time_ms"], 4)
            self.assertEqual(row["sourceFile"], "2026-09.json")
            self.assertFalse(result["files"][0]["hasTotals"])

    def test_fehlendes_verzeichnis_liefert_leer(self):
        with TemporaryDirectory() as tmp:
            result = sources.load_rtk(Path(tmp))
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["errors"], [])

    def test_defekte_zeile_landet_in_errors(self):
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "rtk", "2026-09", "days", [
                {"commands": 1, "input_tokens": 1, "output_tokens": 1,
                 "saved_tokens": 0, "savings_pct": 0, "total_time_ms": 1,
                 "avg_time_ms": 1},
                dict(self.DAY),
            ])
            result = sources.load_rtk(Path(tmp))
            self.assertEqual(len(result["rows"]), 1)
            self.assertEqual(len(result["errors"]), 1)
            self.assertIn("2026-09.json", result["errors"][0]["file"])

    def test_mehrere_monatsdateien_werden_zusammengefuehrt(self):
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "rtk", "2026-06", "days", [
                {"date": "2026-06-12", "commands": 1, "input_tokens": 10,
                 "output_tokens": 5, "saved_tokens": 5, "savings_pct": 50.0,
                 "total_time_ms": 10, "avg_time_ms": 10},
            ])
            write_week(Path(tmp), "rtk", "2026-09", "days", [self.DAY])
            rows = sources.load_rtk(Path(tmp))["rows"]
            self.assertEqual([r["date"] for r in rows],
                             ["2026-06-12", "2026-09-10"])

    def test_month_wird_aus_datum_gebildet(self):
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "rtk", "2026-09", "days", [self.DAY])
            row = sources.load_rtk(Path(tmp))["rows"][0]
            self.assertEqual(row["month"], row["date"][:7])


class AgentSplitTests(unittest.TestCase):
    def test_nutzt_agents_feld_wenn_vorhanden(self):
        raw = new_day(
            "2026-09-01",
            [breakdown("claude-opus-5", 1, 2, 3, 4, 8.0),
             breakdown("gpt-5.6-sol", 1, 1, 1, 1, 2.0)],
            agent_rows=[
                ("claude", [breakdown("claude-opus-5", 1, 2, 3, 4, 8.0)]),
                ("codex", [breakdown("gpt-5.6-sol", 1, 1, 1, 1, 2.0)]),
            ],
        )
        day = loader.normalize_day(raw, "2026-09.json")
        split = sources.agent_split([day])
        self.assertEqual(split[0]["source"], "agents")
        self.assertAlmostEqual(split[0]["agents"]["claude"]["cost"], 8.0)
        self.assertAlmostEqual(split[0]["agents"]["codex"]["cost"], 2.0)

    def test_faellt_ohne_agents_feld_auf_heuristik_zurueck(self):
        raw = new_day("2026-08-01",
                      [breakdown("claude-opus-5", 1, 2, 3, 4, 8.0),
                       breakdown("gpt-5.6-sol", 1, 1, 1, 1, 2.0)])
        day = loader.normalize_day(raw, "2026-08.json")
        split = sources.agent_split([day])
        self.assertEqual(split[0]["source"], "heuristik")
        self.assertAlmostEqual(split[0]["agents"]["codex"]["cost"], 2.0)
        self.assertEqual(split[0]["agents"]["codex"]["tokens"], 4)

    def test_prefer_agents_false_erzwingt_heuristik(self):
        raw = new_day(
            "2026-09-01",
            [breakdown("claude-opus-5", 1, 2, 3, 4, 8.0),
             breakdown("gpt-5.6-sol", 1, 1, 1, 1, 2.0)],
            agent_rows=[("claude", [breakdown("claude-opus-5", 1, 2, 3, 4, 8.0)]),
                        ("codex", [breakdown("gpt-5.6-sol", 1, 1, 1, 1, 2.0)])],
        )
        day = loader.normalize_day(raw, "2026-09.json")
        split = sources.agent_split([day], prefer_agents=False)
        self.assertEqual(split[0]["source"], "heuristik")
        self.assertAlmostEqual(split[0]["agents"]["codex"]["cost"], 2.0)

    def test_unbekannter_agentname_wird_uebernommen(self):
        raw = new_day("2026-09-02", [breakdown("claude-opus-5", 1, 2, 3, 4, 8.0)],
                      agent_rows=[("gemini",
                                   [breakdown("claude-opus-5", 1, 2, 3, 4, 8.0)])])
        day = loader.normalize_day(raw, "2026-09.json")
        split = sources.agent_split([day])
        self.assertIn("gemini", split[0]["agents"])


class CheckExtrasTests(unittest.TestCase):
    def _dir_with_matching_data(self, tmp):
        bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)]
        write_projects(Path(tmp), "2026-09", {
            "-a-b": [project_day("2026-09-01", "-a-b", bd)],
        })
        return Path(tmp)

    def test_stimmige_daten_erzeugen_keine_meldung(self):
        with TemporaryDirectory() as tmp:
            extras = sources.load_extras(self._dir_with_matching_data(tmp))
            result = sources.check_extras(extras, [])
            self.assertEqual(result["issues"], [])
            self.assertEqual(result["checks"]["projectFiles"], 1)

    def test_abweichende_totals_werden_gemeldet(self):
        with TemporaryDirectory() as tmp:
            bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)]
            write_projects(Path(tmp), "2026-09",
                           {"-a-b": [project_day("2026-09-01", "-a-b", bd)]},
                           totals={"inputTokens": 999, "outputTokens": 2,
                                   "cacheCreationTokens": 3, "cacheReadTokens": 4,
                                   "totalTokens": 10, "totalCost": 5.0})
            extras = sources.load_extras(Path(tmp))
            issues = sources.check_extras(extras, [])["issues"]
            self.assertTrue(any(i["scope"] == "projects" for i in issues))

    def test_projektmeldungen_nennen_konkrete_zahlen(self):
        """Jede Meldung soll nachvollziehbar sein, ohne die Datei zu oeffnen."""
        with TemporaryDirectory() as tmp:
            bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)]
            write_projects(Path(tmp), "2026-09",
                           {"-a-b": [project_day("2026-09-01", "-a-b", bd)]},
                           totals={"inputTokens": 999, "outputTokens": 2,
                                   "cacheCreationTokens": 3, "cacheReadTokens": 4,
                                   "totalTokens": 1008, "totalCost": 5.0})
            issues = sources.check_extras(sources.load_extras(Path(tmp)), [])["issues"]
        codes = [i["code"] for i in issues if i["scope"] == "projects"]
        tokensumme = next(i for i in issues if i["scope"] == "projects"
                          and i["code"] == "check.projects.token_mismatch")
        self.assertEqual(tokensumme["params"]["summed"], 10)
        self.assertEqual(tokensumme["params"]["total"], 1008)
        feld = next(i for i in issues if i["scope"] == "projects"
                    and i["code"] == "check.projects.field_mismatch"
                    and i["params"]["field"] == "inputTokens")
        self.assertEqual(feld["params"]["summed"], 1)
        self.assertEqual(feld["params"]["total"], 999)
        self.assertIn("check.projects.token_mismatch", codes)
        self.assertIn("check.projects.field_mismatch", codes)

    def test_block_tokencounts_abweichung_wird_gemeldet(self):
        with TemporaryDirectory() as tmp:
            block = dict(LoadBlocksTests.BLOCK)
            block["totalTokens"] = 42
            write_week(Path(tmp), "blocks", "2026-W36", "blocks", [block])
            extras = sources.load_extras(Path(tmp))
            issues = sources.check_extras(extras, [])["issues"]
            self.assertTrue(any(i["scope"] == "block" for i in issues))

    def test_kreuzpruefung_projekte_gegen_monatsdatei(self):
        with TemporaryDirectory() as tmp:
            bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)]
            write_projects(Path(tmp), "2026-09",
                           {"-a-b": [project_day("2026-09-01", "-a-b", bd)]})
            other = [breakdown("claude-opus-5", 1, 2, 3, 4, 99.0)]
            days = [loader.normalize_day(new_day("2026-09-01", other), "2026-09.json")]
            extras = sources.load_extras(Path(tmp))
            issues = sources.check_extras(extras, days)["issues"]
            self.assertTrue(any(i["scope"] == "kreuzpruefung" for i in issues))

    def test_bloecke_gegen_sessions(self):
        with TemporaryDirectory() as tmp:
            bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)]
            write_week(Path(tmp), "sessions", "2026-W36", "sessions", [{
                "sessionId": "s1", "projectPath": "-a-b",
                "firstActivity": "2026-09-01T10:00:00.000Z",
                "lastActivity": "2026-09-01T11:00:00.000Z",
                "inputTokens": 1, "outputTokens": 2, "cacheCreationTokens": 3,
                "cacheReadTokens": 4, "totalTokens": 10, "totalCost": 5.0,
                "modelsUsed": ["claude-opus-5"], "modelBreakdowns": bd,
            }])
            block = dict(LoadBlocksTests.BLOCK)
            block["costUSD"] = 99.0
            write_week(Path(tmp), "blocks", "2026-W36", "blocks", [block])
            extras = sources.load_extras(Path(tmp))
            issues = sources.check_extras(extras, [])["issues"]
            self.assertTrue(any(i["scope"] == "wochenlauf" for i in issues))

    def test_gegenprobe_wird_bei_gleicher_wochenabdeckung_ausgefuehrt(self):
        """Deckungsgleiche Wochen: es wird verglichen, nicht uebersprungen."""
        bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)]
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "sessions", "2026-W36", "sessions", [
                _session("s1", "-a-b", "2026-09-01T10:00:00.000Z",
                         "2026-09-01T11:00:00.000Z", 5.0, bd)])
            block = dict(LoadBlocksTests.BLOCK)
            block["costUSD"] = 5.0
            write_week(Path(tmp), "blocks", "2026-W36", "blocks", [block])
            result = sources.check_extras(sources.load_extras(Path(tmp)), [])
        self.assertEqual([i for i in result["issues"]
                          if i["scope"] == "wochenlauf"], [])
        self.assertEqual(result["checks"]["weekFilesCompared"],
                         ["2026-W36.json"])

    def test_fehlende_sessiondatei_meldet_die_uebersprungene_gegenprobe(self):
        """Bricht der weekly-Lauf nach den Bloecken ab, faellt die Gegenprobe aus.

        Der Ausstieg war bisher still: der Statusbereich blieb gruen und der
        Nutzer glaubte, gegengeprueft worden zu sein. Die Meldung der Stufe
        info benennt jetzt, dass und warum uebersprungen wurde.
        """
        with TemporaryDirectory() as tmp:
            block = dict(LoadBlocksTests.BLOCK)
            write_week(Path(tmp), "blocks", "2026-W37", "blocks", [block])
            issues = sources.check_extras(sources.load_extras(Path(tmp)), [])["issues"]
        gemeldet = [i for i in issues if i["scope"] == "wochenlauf"]
        self.assertEqual(len(gemeldet), 1)
        self.assertEqual(gemeldet[0]["level"], "info")
        self.assertEqual(gemeldet[0]["code"], "check.weekrun.skipped")
        self.assertEqual(gemeldet[0]["params"]["missingSessions"],
                         ["2026-W37.json"])
        self.assertEqual(gemeldet[0]["params"]["missingBlocks"], [])

    def test_fehlende_blockdatei_meldet_die_uebersprungene_gegenprobe(self):
        bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)]
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "sessions", "2026-W36", "sessions", [
                _session("s1", "-a-b", "2026-09-01T10:00:00.000Z",
                         "2026-09-01T11:00:00.000Z", 5.0, bd)])
            block = dict(LoadBlocksTests.BLOCK)
            write_week(Path(tmp), "blocks", "2026-W37", "blocks", [block])
            issues = sources.check_extras(sources.load_extras(Path(tmp)), [])["issues"]
        gemeldet = [i for i in issues if i["scope"] == "wochenlauf"]
        self.assertEqual(len(gemeldet), 1)
        self.assertEqual(gemeldet[0]["level"], "info")
        self.assertEqual(gemeldet[0]["code"], "check.weekrun.skipped")
        self.assertTrue(gemeldet[0]["params"]["missingBlocks"])
        self.assertTrue(gemeldet[0]["params"]["missingSessions"])

    def test_ohne_blockdateien_gibt_es_nichts_zu_ueberspringen(self):
        bd = [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)]
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "sessions", "2026-W36", "sessions", [
                _session("s1", "-a-b", "2026-09-01T10:00:00.000Z",
                         "2026-09-01T11:00:00.000Z", 5.0, bd)])
            issues = sources.check_extras(sources.load_extras(Path(tmp)), [])["issues"]
        self.assertEqual([i for i in issues if i["scope"] == "wochenlauf"], [])

    def test_agents_summe_abweichung_wird_gemeldet(self):
        raw = new_day("2026-09-01", [breakdown("claude-opus-5", 1, 2, 3, 4, 10.0)],
                      agent_rows=[("claude",
                                   [breakdown("claude-opus-5", 1, 2, 3, 4, 1.0)])])
        day = loader.normalize_day(raw, "2026-09.json")
        empty = {"projects": {"rows": [], "files": [], "errors": []},
                 "sessions": {"rows": [], "files": [], "errors": []},
                 "blocks": {"rows": [], "files": [], "errors": []},
                 "rtk": {"rows": [], "files": [], "errors": []},
                 "errors": []}
        issues = sources.check_extras(empty, [day])["issues"]
        self.assertTrue(any(i["scope"] == "agents" for i in issues))

    def test_rtk_datum_passt_nicht_zum_dateinamen(self):
        with TemporaryDirectory() as tmp:
            write_week(Path(tmp), "rtk", "2026-09", "days", [
                {"date": "2026-08-31", "commands": 1, "input_tokens": 10,
                 "output_tokens": 5, "saved_tokens": 5, "savings_pct": 50.0,
                 "total_time_ms": 10, "avg_time_ms": 10},
            ])
            extras = sources.load_extras(Path(tmp))
            result = sources.check_extras(extras, [])
            self.assertTrue(any(i["scope"] == "rtk" for i in result["issues"]))
            self.assertEqual(result["checks"]["rtkFiles"], 1)
            self.assertEqual(result["checks"]["rtkRows"], 1)
            self.assertEqual(result["checks"]["rtkDays"], 1)

    def test_rtk_datum_mehrfach_in_verschiedenen_dateien(self):
        with TemporaryDirectory() as tmp:
            day = {"date": "2026-09-10", "commands": 1, "input_tokens": 10,
                   "output_tokens": 5, "saved_tokens": 5, "savings_pct": 50.0,
                   "total_time_ms": 10, "avg_time_ms": 10}
            write_week(Path(tmp), "rtk", "2026-09", "days", [day])
            write_week(Path(tmp), "rtk", "2026-10", "days", [dict(day)])
            extras = sources.load_extras(Path(tmp))
            issues = sources.check_extras(extras, [])["issues"]
            duplicate = [i for i in issues
                         if i["code"] == "check.rtk.duplicate_date"]
            self.assertEqual(duplicate[0]["params"]["files"],
                             ["2026-09.json", "2026-10.json"])


if __name__ == "__main__":
    unittest.main()

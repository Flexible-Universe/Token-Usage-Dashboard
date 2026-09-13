"""Tests fuer Konfiguration, Einlesen, Normalisierung und Pruefungen."""

import json
import tempfile
import unittest
from pathlib import Path

from tests.helpers import breakdown, new_day, old_day, write_month  # noqa: F401

import loader


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class ConfigTests(TempDirCase):
    def test_missing_config_is_created_with_defaults(self):
        config_path = self.tmp / "config.toml"
        config, notes = loader.load_config(config_path)

        self.assertTrue(config_path.exists())
        self.assertTrue(any("angelegt" in note for note in notes))
        self.assertEqual(config["server"]["host"], "127.0.0.1")
        self.assertEqual(config["server"]["port"], 8000)
        self.assertTrue(config["server"]["open_browser"])
        self.assertEqual(
            config["data"]["directory"],
            loader.DEFAULT_CONFIG["data"]["directory"],
        )

    def test_created_config_is_reread_identically(self):
        config_path = self.tmp / "config.toml"
        first, _ = loader.load_config(config_path)
        second, notes = loader.load_config(config_path)
        self.assertEqual(first, second)
        self.assertEqual(notes, [])

    def test_partial_config_falls_back_key_by_key(self):
        config_path = self.tmp / "config.toml"
        config_path.write_text('[server]\nport = 9111\n', encoding="utf-8")
        config, _ = loader.load_config(config_path)

        self.assertEqual(config["server"]["port"], 9111)
        self.assertEqual(config["server"]["host"], "127.0.0.1")
        self.assertTrue(config["server"]["open_browser"])
        self.assertEqual(
            config["data"]["directory"],
            loader.DEFAULT_CONFIG["data"]["directory"],
        )

    def test_empty_config_uses_all_defaults(self):
        config_path = self.tmp / "config.toml"
        config_path.write_text("", encoding="utf-8")
        config, _ = loader.load_config(config_path)
        self.assertEqual(config["server"]["port"], 8000)

    def test_unknown_keys_are_ignored(self):
        config_path = self.tmp / "config.toml"
        config_path.write_text('[data]\nverzeichnis = "x"\n', encoding="utf-8")
        config, _ = loader.load_config(config_path)
        self.assertNotIn("verzeichnis", config["data"])

    def test_broken_toml_raises_config_error(self):
        config_path = self.tmp / "config.toml"
        config_path.write_text("[data\ndirectory = ", encoding="utf-8")
        with self.assertRaises(loader.ConfigError) as ctx:
            loader.load_config(config_path)
        self.assertIn(str(config_path), str(ctx.exception))

    def test_invalid_port_falls_back_with_note(self):
        config_path = self.tmp / "config.toml"
        config_path.write_text('[server]\nport = "achttausend"\n', encoding="utf-8")
        config, notes = loader.load_config(config_path)
        self.assertEqual(config["server"]["port"], 8000)
        self.assertTrue(any("port" in note for note in notes))

    def test_relative_directory_resolves_next_to_config(self):
        nested = self.tmp / "conf"
        nested.mkdir()
        config_path = nested / "config.toml"
        config_path.write_text('[data]\ndirectory = "../daten"\n', encoding="utf-8")
        config, _ = loader.load_config(config_path)
        resolved = loader.resolve_data_directory(config, config_path)
        self.assertEqual(resolved, (self.tmp / "daten").resolve())

    def test_tilde_is_expanded(self):
        config_path = self.tmp / "config.toml"
        config_path.write_text('[data]\ndirectory = "~/Daten"\n', encoding="utf-8")
        config, _ = loader.load_config(config_path)
        resolved = loader.resolve_data_directory(config, config_path)
        self.assertEqual(resolved, Path.home() / "Daten")
        self.assertNotIn("~", str(resolved))

    def test_empty_directory_value_is_config_error(self):
        config_path = self.tmp / "config.toml"
        config_path.write_text('[data]\ndirectory = "   "\n', encoding="utf-8")
        config, _ = loader.load_config(config_path)
        with self.assertRaises(loader.ConfigError):
            loader.resolve_data_directory(config, config_path)


class DataDirectoryTests(TempDirCase):
    def test_missing_directory_names_the_checked_path(self):
        missing = self.tmp / "gibtsnicht"
        with self.assertRaises(loader.DataDirectoryError) as ctx:
            loader.check_data_directory(missing)
        self.assertIn(str(missing), str(ctx.exception))

    def test_file_instead_of_directory(self):
        target = self.tmp / "datei.txt"
        target.write_text("x", encoding="utf-8")
        with self.assertRaises(loader.DataDirectoryError):
            loader.check_data_directory(target)

    def test_directory_without_month_files_is_an_error(self):
        (self.tmp / "notizen.json").write_text("{}", encoding="utf-8")
        (self.tmp / "2026-05.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(loader.DataDirectoryError) as ctx:
            loader.check_data_directory(self.tmp)
        self.assertIn(str(self.tmp), str(ctx.exception))

    def test_single_month_file_is_enough(self):
        write_month(self.tmp, "2026-05", [old_day(
            "2026-05-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 1.5)])])
        files = loader.check_data_directory(self.tmp)
        self.assertEqual([f.name for f in files], ["2026-05.json"])
        dataset = loader.load_directory(self.tmp)
        self.assertEqual(len(dataset["days"]), 1)

    def test_only_month_pattern_files_are_picked_up(self):
        write_month(self.tmp, "2026-05", [old_day(
            "2026-05-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 1.5)])])
        (self.tmp / "backup-2026-05.json").write_text('{"daily": []}', encoding="utf-8")
        (self.tmp / "2026-5.json").write_text('{"daily": []}', encoding="utf-8")
        self.assertEqual(
            [p.name for p in loader.find_month_files(self.tmp)], ["2026-05.json"]
        )


class NormalizationTests(TempDirCase):
    def setUp(self):
        super().setUp()
        self.old = old_day(
            "2026-05-01",
            [breakdown("claude-sonnet-4-6", 8, 646, 13843, 131996, 0.10122405)],
        )
        self.new = new_day(
            "2026-08-01",
            [
                breakdown("claude-opus-5", 604, 338297, 3288680, 53346472, 65.6799185),
                breakdown("gpt-5.6-sol", 100, 2000, 5000, 40000, 3.5),
            ],
            agents=("claude", "codex"),
        )
        write_month(self.tmp, "2026-05", [self.old])
        write_month(self.tmp, "2026-08", [self.new])
        self.dataset = loader.load_directory(self.tmp)

    def test_both_schemas_are_loaded_together(self):
        dates = [d["date"] for d in self.dataset["days"]]
        self.assertEqual(dates, ["2026-05-01", "2026-08-01"])
        self.assertEqual(self.dataset["errors"], [])

    def test_period_is_normalized_to_date(self):
        new = self.dataset["days"][1]
        self.assertEqual(new["date"], "2026-08-01")
        self.assertEqual(new["schema"], "period")
        self.assertEqual(new["month"], "2026-08")
        self.assertEqual(new["day"], 1)
        self.assertNotIn("period", new)

    def test_old_schema_keeps_all_values(self):
        old = self.dataset["days"][0]
        self.assertEqual(old["schema"], "date")
        self.assertEqual(old["inputTokens"], 8)
        self.assertEqual(old["outputTokens"], 646)
        self.assertEqual(old["cacheCreationTokens"], 13843)
        self.assertEqual(old["cacheReadTokens"], 131996)
        self.assertEqual(old["totalTokens"], 146493)
        self.assertAlmostEqual(old["totalCost"], 0.10122405)
        self.assertEqual(old["agent"], "all")

    def test_agent_and_metadata_of_new_schema(self):
        new = self.dataset["days"][1]
        self.assertEqual(new["agent"], "all")
        self.assertEqual(new["agents"], ["claude", "codex"])

    def test_agents_are_derived_when_metadata_is_absent(self):
        day = loader.normalize_day(self.old, "2026-05.json")
        self.assertEqual(day["agents"], ["claude"])

    def test_gpt_models_map_to_codex(self):
        self.assertEqual(loader.agent_for_model("gpt-5.6-sol"), "codex")
        self.assertEqual(loader.agent_for_model("claude-opus-5"), "claude")
        breakdowns = self.dataset["days"][1]["modelBreakdowns"]
        agents = {b["modelName"]: b["agent"] for b in breakdowns}
        self.assertEqual(agents["gpt-5.6-sol"], "codex")
        self.assertEqual(agents["claude-opus-5"], "claude")

    def test_breakdown_total_tokens_are_derived(self):
        entry = self.dataset["days"][1]["modelBreakdowns"][0]
        self.assertEqual(
            entry["totalTokens"], 604 + 338297 + 3288680 + 53346472
        )

    def test_file_metadata_lists_schema_and_totals(self):
        infos = {f["name"]: f for f in self.dataset["files"]}
        self.assertEqual(infos["2026-05.json"]["schemas"], ["date"])
        self.assertEqual(infos["2026-08.json"]["schemas"], ["period"])
        self.assertTrue(all(f["accepted"] for f in self.dataset["files"]))

    def test_day_without_date_or_period_is_reported(self):
        write_month(self.tmp, "2026-06", [old_day(
            "2026-06-01", [breakdown("claude-opus-5", 1, 2, 3, 4, 0.5)])])
        path = self.tmp / "2026-06.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["daily"].append({"inputTokens": 1})
        path.write_text(json.dumps(payload), encoding="utf-8")

        dataset = loader.load_directory(self.tmp)
        self.assertEqual(len(dataset["errors"]), 1)
        self.assertEqual(dataset["errors"][0]["code"], "source.monthly.bad_date")
        self.assertEqual(dataset["errors"][0]["params"]["index"], 1)


class RejectionTests(TempDirCase):
    def setUp(self):
        super().setUp()
        write_month(self.tmp, "2026-05", [old_day(
            "2026-05-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 1.5)])])

    def test_file_without_daily_is_rejected_and_reported(self):
        (self.tmp / "2026-06.json").write_text('{"totals": {}}', encoding="utf-8")
        dataset = loader.load_directory(self.tmp)
        self.assertEqual(len(dataset["days"]), 1)
        self.assertEqual(len(dataset["errors"]), 1)
        self.assertEqual(dataset["errors"][0]["code"],
                         "source.monthly.daily_missing")

        health = loader.check_plausibility(dataset)
        self.assertEqual(health["filesRejected"], 1)
        self.assertFalse(health["ok"])
        self.assertTrue(
            any(i["level"] == "error" and i["key"] == "2026-06.json"
                for i in health["issues"])
        )

    def test_daily_as_object_is_rejected(self):
        (self.tmp / "2026-06.json").write_text('{"daily": {"a": 1}}', encoding="utf-8")
        dataset = loader.load_directory(self.tmp)
        self.assertEqual(len(dataset["errors"]), 1)

    def test_broken_json_is_rejected(self):
        (self.tmp / "2026-06.json").write_text("{kaputt", encoding="utf-8")
        dataset = loader.load_directory(self.tmp)
        self.assertEqual(len(dataset["errors"]), 1)
        self.assertEqual(dataset["errors"][0]["code"], "source.file.unreadable")
        self.assertIn("reason", dataset["errors"][0]["params"])


class PlausibilityTests(TempDirCase):
    def test_clean_data_passes_all_checks(self):
        write_month(self.tmp, "2026-05", [
            old_day("2026-05-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 1.5)]),
            new_day("2026-05-03", [breakdown("claude-sonnet-5", 2, 20, 200, 2000, 2.5)]),
        ])
        health = loader.check_plausibility(loader.load_directory(self.tmp))
        self.assertTrue(health["ok"])
        self.assertEqual(health["tokenSumFailed"], 0)
        self.assertEqual(health["costSumFailed"], 0)
        self.assertEqual(health["daysLoaded"], 2)
        self.assertTrue(all(check["ok"] for check in health["fileChecks"]))

    def test_tagespruefung_liefert_rohe_zahlen_als_parameter(self):
        raw_day = old_day("2026-09-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 1.5)])
        raw_day["totalTokens"] = 1200
        write_month(self.tmp, "2026-09", [raw_day])
        dataset = loader.load_directory(self.tmp)
        day = dataset["days"][0]
        day["sumTokens"] = 1234
        health = loader.check_plausibility({"directory": ".", "days": [day],
                                            "files": [], "errors": []})
        issue = next(i for i in health["issues"]
                     if i["code"] == "check.day.token_sum_mismatch")
        self.assertEqual(issue["params"],
                         {"sum": 1234, "total": 1200, "delta": 34})
        self.assertNotIn("message", issue)

    def test_token_sum_mismatch_is_flagged(self):
        day = old_day("2026-05-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 1.5)])
        day["totalTokens"] = 999
        write_month(self.tmp, "2026-05", [day])
        health = loader.check_plausibility(loader.load_directory(self.tmp))
        self.assertEqual(health["tokenSumFailed"], 1)
        self.assertTrue(any(i["code"] == "check.day.token_sum_mismatch"
                            for i in health["issues"]))

    def test_cost_mismatch_beyond_tolerance_is_flagged(self):
        day = old_day("2026-05-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 1.5)])
        day["totalCost"] = 1.9
        write_month(self.tmp, "2026-05", [day])
        health = loader.check_plausibility(loader.load_directory(self.tmp))
        self.assertEqual(health["costSumFailed"], 1)

    def test_cost_mismatch_within_tolerance_passes(self):
        day = old_day("2026-05-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 1.5)])
        day["totalCost"] = 1.505
        write_month(self.tmp, "2026-05", [day])
        health = loader.check_plausibility(loader.load_directory(self.tmp))
        self.assertEqual(health["costSumFailed"], 0)

    def test_file_totals_mismatch_is_flagged(self):
        days = [old_day("2026-05-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 1.5)])]
        totals = {
            "inputTokens": 1, "outputTokens": 10, "cacheCreationTokens": 100,
            "cacheReadTokens": 1000, "totalTokens": 1111, "totalCost": 99.0,
        }
        write_month(self.tmp, "2026-05", days, totals=totals)
        health = loader.check_plausibility(loader.load_directory(self.tmp))
        self.assertFalse(health["fileChecks"][0]["ok"])
        self.assertTrue(any(i["code"] == "check.file.cost_mismatch"
                            for i in health["issues"]))

    def test_missing_totals_is_flagged(self):
        payload = {"daily": [old_day(
            "2026-05-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 1.5)])]}
        (self.tmp / "2026-05.json").write_text(json.dumps(payload), encoding="utf-8")
        health = loader.check_plausibility(loader.load_directory(self.tmp))
        self.assertFalse(health["fileChecks"][0]["ok"])
        self.assertTrue(any(i["code"] == "check.file.totals_missing"
                            for i in health["issues"]))


class AgentBreakdownTests(unittest.TestCase):
    def test_agents_feld_wird_durchgereicht(self):
        raw = new_day("2026-09-01", [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)],
                      agent_rows=[("claude",
                                   [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)])])
        day = loader.normalize_day(raw, "2026-09.json")
        self.assertEqual(len(day["agentBreakdowns"]), 1)
        self.assertEqual(day["agentBreakdowns"][0]["agent"], "claude")
        self.assertAlmostEqual(day["agentBreakdowns"][0]["totalCost"], 5.0)
        self.assertEqual(day["agentBreakdowns"][0]["totalTokens"], 10)

    def test_ohne_agents_feld_leere_liste(self):
        raw = new_day("2026-08-01", [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)])
        day = loader.normalize_day(raw, "2026-08.json")
        self.assertEqual(day["agentBreakdowns"], [])

    def test_beide_schemavarianten_tragen_das_feld_agents(self):
        """Datum und Feld agents werden unabhaengig voneinander gelesen.

        normalize_day nimmt das Datum aus ``date`` oder ``period`` und das Feld
        ``agents`` getrennt davon. Belegt war bisher nur die Kombination
        period + agents[]; die alte Variante date + agents[] ist genauso
        moeglich, sobald ein Altbestand nachtraeglich neu exportiert wird.
        """
        bds = [breakdown("claude-opus-5", 1, 2, 3, 4, 8.0),
               breakdown("gpt-5.6-sol", 1, 1, 1, 1, 2.0)]
        agent_rows = [("claude", [bds[0]]), ("codex", [bds[1]])]
        neu = new_day("2026-09-01", bds, agent_rows=agent_rows)
        alt = old_day("2026-09-02", bds)
        alt["agents"] = neu["agents"]

        tag_neu = loader.normalize_day(neu, "2026-09.json")
        tag_alt = loader.normalize_day(alt, "2026-09.json")

        self.assertEqual(tag_neu["schema"], "period")
        self.assertEqual(tag_alt["schema"], "date")
        for tag in (tag_neu, tag_alt):
            self.assertEqual([a["agent"] for a in tag["agentBreakdowns"]],
                             ["claude", "codex"])
            self.assertAlmostEqual(
                sum(a["totalCost"] for a in tag["agentBreakdowns"]),
                tag["totalCost"])
        # Der Schluessel agents bleibt in beiden Faellen die Namensliste.
        self.assertEqual(tag_neu["agents"], ["claude"])
        self.assertEqual(tag_alt["agents"], ["claude", "codex"])

    def test_bestehender_schluessel_agents_bleibt_namensliste(self):
        raw = new_day("2026-09-01", [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)],
                      agent_rows=[("claude",
                                   [breakdown("claude-opus-5", 1, 2, 3, 4, 5.0)])])
        day = loader.normalize_day(raw, "2026-09.json")
        self.assertEqual(day["agents"], ["claude"])


if __name__ == "__main__":
    unittest.main()

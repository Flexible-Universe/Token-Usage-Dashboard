"""Tests fuer die Kennzahlen, besonders fuer den Umgang mit fehlenden Tagen."""

import tempfile
import unittest

from tests.helpers import breakdown, new_day, old_day, require_real_data, write_month

import loader
import metrics


# Die Referenztests pruefen gegen die echten Monatsdateien. Das Datenverzeichnis
# waechst durch den taeglichen Export weiter, deshalb sind die Tests auf die
# abgeschlossenen Monate begrenzt. Ohne diese Grenze muessten die erwarteten
# Werte nach jedem Exportlauf erneut angepasst werden.
REFERENCE_FROM = "2026-05-01"
REFERENCE_TO = "2026-08-31"


def build(days):
    """Baut aus Tagesrohdaten normalisierte Tage ohne Dateiumweg."""
    return [loader.normalize_day(day, "test.json") for day in days]


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.days = build([
            old_day("2026-05-01", [breakdown("claude-opus-5", 1, 10, 100, 1000, 10.0)]),
            new_day("2026-06-10", [
                breakdown("claude-opus-5", 1, 10, 100, 1000, 20.0),
                breakdown("gpt-5.6-sol", 1, 5, 50, 500, 5.0),
            ]),
            new_day("2026-07-20", [breakdown("gpt-5.6-sol", 1, 5, 50, 500, 7.0)]),
        ])

    def test_date_range_filter(self):
        selected = metrics.filter_days(self.days, "2026-06-01", "2026-06-30")
        self.assertEqual([d["date"] for d in selected], ["2026-06-10"])

    def test_model_filter_recomputes_day_values(self):
        selected = metrics.filter_days(self.days, models=["claude-opus-5"])
        self.assertEqual([d["date"] for d in selected], ["2026-05-01", "2026-06-10"])
        self.assertAlmostEqual(selected[1]["totalCost"], 20.0)
        self.assertEqual(selected[1]["totalTokens"], 1 + 10 + 100 + 1000)

    def test_without_model_filter_original_values_are_kept(self):
        selected = metrics.filter_days(self.days)
        self.assertAlmostEqual(selected[1]["totalCost"], 25.0)

    def test_days_without_matching_model_drop_out(self):
        selected = metrics.filter_days(self.days, models=["gpt-5.6-sol"])
        self.assertEqual([d["date"] for d in selected], ["2026-06-10", "2026-07-20"])

    def test_available_models_are_sorted(self):
        self.assertEqual(
            metrics.available_models(self.days), ["claude-opus-5", "gpt-5.6-sol"]
        )


class MissingDayTests(unittest.TestCase):
    """Fehlende Tage sind Luecken, keine Nullen."""

    def setUp(self):
        # 01., 03. und 10. Mai. Sieben Kalendertage fehlen dazwischen.
        self.days = build([
            old_day("2026-05-01", [breakdown("claude-opus-5", 0, 100, 0, 900, 30.0)]),
            old_day("2026-05-03", [breakdown("claude-opus-5", 0, 100, 0, 900, 60.0)]),
            new_day("2026-05-10", [breakdown("claude-opus-5", 0, 100, 0, 900, 90.0)]),
        ])

    def test_mean_ignores_missing_days(self):
        summary = metrics.summary(self.days)
        self.assertEqual(summary["daysWithData"], 3)
        self.assertEqual(summary["calendarDays"], 10)
        self.assertEqual(summary["missingDays"], 7)
        # Mittelwert ueber drei Tage, nicht ueber zehn.
        self.assertAlmostEqual(summary["meanCostPerDay"], 60.0)

    def test_median_ignores_missing_days(self):
        self.assertAlmostEqual(metrics.summary(self.days)["medianCostPerDay"], 60.0)

    def test_median_of_even_count(self):
        days = self.days[:2]
        self.assertAlmostEqual(metrics.summary(days)["medianCostPerDay"], 45.0)

    def test_time_series_marks_gaps_as_none(self):
        series = metrics.daily_series(self.days)
        self.assertEqual(len(series["labels"]), 10)
        self.assertEqual(series["labels"][0], "2026-05-01")
        self.assertEqual(series["labels"][-1], "2026-05-10")
        self.assertAlmostEqual(series["cost"][0], 30.0)
        self.assertIsNone(series["cost"][1])
        self.assertAlmostEqual(series["cost"][2], 60.0)
        self.assertEqual(series["cost"][3:9], [None] * 6)
        self.assertAlmostEqual(series["cost"][9], 90.0)
        self.assertNotIn(0, [v for v in series["cost"] if v is not None])

    def test_stacked_series_marks_gaps_as_none(self):
        stacked = metrics.stacked_by_model(self.days)
        values = stacked["datasets"][0]["cost"]
        self.assertEqual(len(values), 10)
        self.assertIsNone(values[1])

    def test_rolling_mean_skips_gaps_instead_of_counting_zeros(self):
        values = [10.0, None, 20.0, None, None, None, 30.0]
        result = metrics.rolling_mean(values, window=7, min_points=3)
        # Erst ab dem dritten vorhandenen Wert gibt es ein Mittel.
        self.assertEqual(result[:6], [None] * 6)
        self.assertAlmostEqual(result[6], 20.0)

    def test_rolling_mean_window_is_calendar_based(self):
        values = [10.0, 10.0, 10.0, None, None, None, None, 100.0, 100.0, 100.0]
        result = metrics.rolling_mean(values, window=7, min_points=3)
        self.assertAlmostEqual(result[2], 10.0)
        # An Position 9 liegen nur noch die drei hohen Werte im Fenster.
        self.assertAlmostEqual(result[9], 100.0)

    def test_cumulative_curve_holds_value_across_gaps(self):
        cumulative = metrics.cumulative_by_month(self.days)
        data = cumulative["series"][0]["data"]
        self.assertAlmostEqual(data[0], 30.0)
        self.assertAlmostEqual(data[1], 30.0)
        self.assertAlmostEqual(data[2], 90.0)
        self.assertAlmostEqual(data[9], 180.0)

    def test_cumulative_curve_is_none_before_first_day(self):
        days = build([
            old_day("2026-05-05", [breakdown("claude-opus-5", 0, 10, 0, 90, 5.0)]),
        ])
        data = metrics.cumulative_by_month(days)["series"][0]["data"]
        self.assertEqual(data[:4], [None] * 4)
        self.assertAlmostEqual(data[4], 5.0)


class MetricValueTests(unittest.TestCase):
    def setUp(self):
        self.days = build([
            old_day("2026-05-01", [
                breakdown("claude-opus-5", 0, 1000, 0, 999000, 100.0),
                breakdown("claude-sonnet-5", 0, 500, 0, 499500, 25.0),
            ]),
            new_day("2026-06-02", [
                breakdown("claude-opus-5", 0, 1000, 0, 999000, 200.0),
            ]),
        ])

    def test_cost_per_million_tokens_per_day(self):
        series = metrics.daily_series(self.days)
        # Tag 1: 125 $ auf 1.500.000 Tokens.
        self.assertAlmostEqual(series["costPerMillionTokens"][0], 125 / 1.5)

    def test_model_share_absolute_and_percent(self):
        models = {m["model"]: m for m in metrics.model_totals(self.days)}
        self.assertAlmostEqual(models["claude-opus-5"]["cost"], 300.0)
        self.assertAlmostEqual(models["claude-opus-5"]["costShare"], 300 / 325 * 100)
        self.assertAlmostEqual(models["claude-sonnet-5"]["costShare"], 25 / 325 * 100)

    def test_cost_per_million_output_tokens_per_model(self):
        models = {m["model"]: m for m in metrics.model_totals(self.days)}
        # 300 $ auf 2000 Output-Token.
        self.assertAlmostEqual(models["claude-opus-5"]["costPerMillionOutputTokens"], 150000.0)

    def test_context_reload_factor_per_model(self):
        models = {m["model"]: m for m in metrics.model_totals(self.days)}
        self.assertAlmostEqual(models["claude-opus-5"]["contextReloadFactor"], 999.0)

    def test_context_reload_factor_as_series(self):
        series = metrics.daily_series(self.days)
        self.assertAlmostEqual(series["contextReloadFactor"][0], 1498500 / 1500)

    def test_model_timeline(self):
        timeline = {t["model"]: t for t in metrics.model_timeline(metrics.model_totals(self.days))}
        self.assertEqual(timeline["claude-opus-5"]["firstDay"], "2026-05-01")
        self.assertEqual(timeline["claude-opus-5"]["lastDay"], "2026-06-02")
        self.assertEqual(timeline["claude-opus-5"]["days"], 2)
        self.assertEqual(timeline["claude-sonnet-5"]["days"], 1)

    def test_pareto_is_descending_and_cumulates_to_hundred(self):
        pareto = metrics.pareto(metrics.model_totals(self.days))
        self.assertEqual(pareto["labels"], ["claude-opus-5", "claude-sonnet-5"])
        self.assertEqual(pareto["cost"], sorted(pareto["cost"], reverse=True))
        self.assertAlmostEqual(pareto["cumulativePercent"][-1], 100.0)

    def test_top_days_are_sorted_and_carry_model_breakdown(self):
        top = metrics.top_days(self.days)
        self.assertEqual(top[0]["date"], "2026-06-02")
        self.assertEqual([m["model"] for m in top[1]["models"]],
                         ["claude-opus-5", "claude-sonnet-5"])

    def test_zero_tokens_do_not_divide_by_zero(self):
        days = build([old_day("2026-05-01", [breakdown("claude-opus-5", 0, 0, 0, 0, 0.0)])])
        series = metrics.daily_series(days)
        self.assertIsNone(series["costPerMillionTokens"][0])
        self.assertIsNone(series["contextReloadFactor"][0])
        self.assertIsNone(metrics.model_totals(days)[0]["costPerMillionOutputTokens"])

    def test_empty_selection_stays_stable(self):
        result = metrics.compute_metrics([], models=["gibtsnicht"])
        self.assertEqual(result["summary"]["daysWithData"], 0)
        self.assertEqual(result["models"], [])
        self.assertIsNone(result["projection"])


class ProjectionTests(unittest.TestCase):
    def test_incomplete_last_month_is_projected_and_marked(self):
        days = build([
            old_day(f"2026-05-{d:02d}", [breakdown("claude-opus-5", 0, 10, 0, 90, 10.0)])
            for d in range(1, 11)
        ])
        projection = metrics.projection(days)
        self.assertTrue(projection["isEstimate"])
        self.assertEqual(projection["daysWithData"], 10)
        self.assertEqual(projection["daysInMonth"], 31)
        self.assertAlmostEqual(projection["actualCost"], 100.0)
        self.assertAlmostEqual(projection["projectedCost"], 310.0)

    def test_complete_month_is_not_projected(self):
        days = build([
            old_day(f"2026-06-{d:02d}", [breakdown("claude-opus-5", 0, 10, 0, 90, 1.0)])
            for d in range(1, 31)
        ])
        self.assertIsNone(metrics.projection(days))


class RestBucketAndProjectionTests(unittest.TestCase):
    def setUp(self):
        self.days = build([
            old_day(f"2026-05-{d:02d}", [
                breakdown("claude-opus-5", 0, 10, 0, 90, 10.0),
                breakdown("claude-sonnet-5", 0, 10, 0, 90, 5.0),
                breakdown("gpt-5.6-sol", 0, 10, 0, 90, 2.0),
            ])
            for d in range(1, 11)
        ])

    def test_restbucket_traegt_isother_und_keinen_namen(self):
        stacked = metrics.stacked_by_model(self.days, top=1)
        rest = [d for d in stacked["datasets"] if d["isOther"]]
        self.assertEqual(len(rest), 1)
        self.assertEqual(rest[0]["model"], "")

    def test_projektion_nennt_einen_schluessel_statt_eines_satzes(self):
        result = metrics.projection(self.days)
        if result is None:
            self.skipTest("Der Testdatensatz enthaelt keinen offenen Monat.")
        self.assertEqual(result["basisCode"], "ui.projection.basis")
        self.assertNotIn("basis", result)
        self.assertTrue(result["isEstimate"])


class ReferenceValueTests(unittest.TestCase):
    """Prueft die Kennzahlen gegen die Referenzwerte aus der Aufgabenstellung."""

    @classmethod
    def setUpClass(cls):
        cls.DATA_DIR = require_real_data()
        if not loader.find_month_files(cls.DATA_DIR):
            raise unittest.SkipTest(f"Referenzdaten fehlen: {cls.DATA_DIR}")
        cls.dataset = loader.load_directory(cls.DATA_DIR)
        # Die Plausibilitaetspruefung laeuft bewusst ueber alle Dateien,
        # auch ueber den laufenden Monat.
        cls.health = loader.check_plausibility(cls.dataset)
        cls.metrics = metrics.compute_metrics(
            cls.dataset["days"], REFERENCE_FROM, REFERENCE_TO
        )

    def test_day_count(self):
        self.assertEqual(self.metrics["summary"]["daysWithData"], 118)

    def test_data_is_plausible(self):
        self.assertEqual(self.health["tokenSumFailed"], 0)
        self.assertEqual(self.health["costSumFailed"], 0)
        self.assertTrue(all(check["ok"] for check in self.health["fileChecks"]))
        self.assertEqual(self.dataset["errors"], [])

    def test_monthly_totals(self):
        expected = {
            "2026-05": (29, 1424265547, 1058.53),
            "2026-06": (28, 1461333234, 1284.40),
            "2026-07": (30, 4999950700, 4379.95),
            "2026-08": (31, 7051509277, 4739.12),
        }
        actual = {m["month"]: m for m in self.metrics["months"]}
        self.assertEqual(sorted(actual), sorted(expected))
        for month, (days, tokens, cost) in expected.items():
            self.assertEqual(actual[month]["days"], days, month)
            self.assertEqual(actual[month]["totalTokens"], tokens, month)
            self.assertAlmostEqual(actual[month]["totalCost"], cost, places=2, msg=month)

    def test_total_cost(self):
        self.assertAlmostEqual(self.metrics["summary"]["totalCost"], 11462.00, places=2)

    def test_model_cost_shares(self):
        expected = [
            ("claude-opus-5", 3886, 33.9),
            ("claude-opus-4-8", 2537, 22.1),
            ("claude-sonnet-5", 1954, 17.0),
            ("claude-opus-4-7", 1279, 11.2),
            ("claude-fable-5", 1086, 9.5),
            ("claude-sonnet-4-6", 318, 2.8),
            ("gpt-5.6-sol", 246, 2.1),
            ("claude-haiku-4-5-20251001", 98, 0.9),
            ("gpt-5.6-terra", 56, 0.5),
            ("gpt-5.6-luna", 1, 0.0),
        ]
        actual = self.metrics["models"]
        self.assertEqual([m["model"] for m in actual], [e[0] for e in expected])
        for entry, (model, cost, share) in zip(actual, expected):
            self.assertEqual(round(entry["cost"]), cost, model)
            self.assertAlmostEqual(entry["costShare"], share, places=1, msg=model)

    def test_most_expensive_day(self):
        top = self.metrics["topDays"][0]
        self.assertEqual(top["date"], "2026-08-22")
        self.assertAlmostEqual(top["totalCost"], 384.53, places=2)
        self.assertEqual(top["totalTokens"], 533419976)

    def test_median_and_minimum_of_daily_cost(self):
        summary = self.metrics["summary"]
        self.assertAlmostEqual(summary["medianCostPerDay"], 87.73, places=2)
        self.assertAlmostEqual(summary["minCostDay"]["value"], 0.10, places=2)
        self.assertEqual(summary["minCostDay"]["date"], "2026-05-01")

    def test_cost_per_million_tokens_extremes(self):
        summary = self.metrics["summary"]
        self.assertEqual(summary["minCostPerMillionTokens"]["date"], "2026-08-03")
        self.assertAlmostEqual(summary["minCostPerMillionTokens"]["value"], 0.37, places=2)
        self.assertEqual(summary["maxCostPerMillionTokens"]["date"], "2026-07-06")
        self.assertAlmostEqual(summary["maxCostPerMillionTokens"]["value"], 2.07, places=2)

    def test_both_schema_variants_are_present_and_mixed(self):
        schemas = {d["schema"] for d in self.dataset["days"]}
        self.assertEqual(schemas, {"date", "period"})

    def test_codex_models_are_identified(self):
        codex = [m for m in self.metrics["models"] if m["agent"] == "codex"]
        self.assertEqual(
            sorted(m["model"] for m in codex),
            ["gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"],
        )


class FilteredReferenceTests(unittest.TestCase):
    """Der Zeitraumfilter muss dieselben Monatssummen liefern."""

    @classmethod
    def setUpClass(cls):
        cls.DATA_DIR = require_real_data()
        if not loader.find_month_files(cls.DATA_DIR):
            raise unittest.SkipTest(f"Referenzdaten fehlen: {cls.DATA_DIR}")
        cls.days = loader.load_directory(cls.DATA_DIR)["days"]

    def test_single_month_filter(self):
        result = metrics.compute_metrics(self.days, "2026-07-01", "2026-07-31")
        self.assertEqual(result["summary"]["daysWithData"], 30)
        self.assertAlmostEqual(result["summary"]["totalCost"], 4379.95, places=2)

    def test_free_range_filter(self):
        result = metrics.compute_metrics(self.days, "2026-05-01", "2026-06-30")
        self.assertAlmostEqual(
            result["summary"]["totalCost"], 1058.53 + 1284.40, places=1
        )

    def test_model_filter_matches_model_total(self):
        result = metrics.compute_metrics(
            self.days, REFERENCE_FROM, REFERENCE_TO, models=["claude-opus-5"]
        )
        self.assertEqual(len(result["models"]), 1)
        self.assertAlmostEqual(result["summary"]["totalCost"], 3886.3, places=1)


if __name__ == "__main__":
    unittest.main()

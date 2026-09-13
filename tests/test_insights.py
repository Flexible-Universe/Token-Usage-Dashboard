"""Tests fuer insights.py: Kennzahlen der daily- und weekly-Zusatzquellen."""

from __future__ import annotations

import json
import unittest

from tests.helpers import BASE_DIR, breakdown, require_real_data  # noqa: F401  - setzt sys.path

import insights
import loader
import sources


def row(date, project, label, cost, breakdowns):
    fields = ("inputTokens", "outputTokens", "cacheCreationTokens",
              "cacheReadTokens")
    entry = {"date": date, "month": date[:7], "project": project,
             "projectLabel": label, "sourceFile": "test.json",
             "modelBreakdowns": breakdowns,
             "modelsUsed": sorted({b["modelName"] for b in breakdowns}),
             "totalCost": cost}
    for f in fields:
        entry[f] = sum(b[f] for b in breakdowns)
    entry["totalTokens"] = sum(entry[f] for f in fields)
    entry["sumTokens"] = entry["totalTokens"]
    return entry


def bd(model, cost, out=1000):
    return breakdown(model, 1, out, 10, 100, cost)


class CoverageTests(unittest.TestCase):
    def test_vollstaendig(self):
        result = insights.coverage(["2026-09-01", "2026-09-04"],
                                   "2026-09-01", "2026-09-04")
        self.assertTrue(result["complete"])
        self.assertEqual(result["noteCode"], "")
        self.assertEqual(result["noteParams"], {})

    def test_beginnt_spaeter_als_angefragt(self):
        result = insights.coverage(["2026-09-01", "2026-09-04"],
                                   "2026-05-01", "2026-09-04")
        self.assertFalse(result["complete"])
        self.assertEqual(result["noteCode"], "range.partial")
        self.assertEqual(result["noteParams"],
                         {"first": "2026-09-01", "last": "2026-09-04"})

    def test_ohne_daten(self):
        result = insights.coverage([], "2026-05-01", None)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["from"])
        self.assertEqual(result["noteCode"], "range.no_data")
        self.assertEqual(result["noteParams"], {})

    def test_angefragter_zeitraum_liegt_komplett_hinter_den_daten(self):
        result = insights.coverage(["2026-09-01", "2026-09-04"],
                                   "2026-09-05", None)
        self.assertFalse(result["complete"])
        self.assertEqual(result["noteCode"], "range.empty")
        self.assertEqual(result["noteParams"],
                         {"first": "2026-09-01", "last": "2026-09-04"})

    def test_angefragter_zeitraum_liegt_komplett_vor_den_daten(self):
        result = insights.coverage(["2026-09-01", "2026-09-04"],
                                   None, "2026-08-31")
        self.assertFalse(result["complete"])
        self.assertEqual(result["noteCode"], "range.empty")
        self.assertEqual(result["noteParams"],
                         {"first": "2026-09-01", "last": "2026-09-04"})

    def test_datumswerte_gehen_als_iso_hinaus(self):
        result = insights.coverage(["2026-09-01", "2026-09-04"],
                                   "2026-05-01", "2026-09-04")
        for value in result["noteParams"].values():
            self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}$")


class FilterRowsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row("2026-09-01", "-a-lumo", "lumo", 10.0,
                [bd("claude-opus-5", 8.0), bd("gpt-5.6-sol", 2.0)]),
            row("2026-09-05", "-a-lumo", "lumo", 3.0, [bd("claude-opus-5", 3.0)]),
        ]

    def test_zeitraum(self):
        result = insights.filter_rows(self.rows, "2026-09-02", None)
        self.assertEqual([r["date"] for r in result], ["2026-09-05"])

    def test_modellfilter_rechnet_werte_neu(self):
        result = insights.filter_rows(self.rows, None, None, ["claude-opus-5"])
        self.assertAlmostEqual(result[0]["totalCost"], 8.0)
        self.assertEqual(result[0]["modelsUsed"], ["claude-opus-5"])

    def test_zeile_ohne_treffer_faellt_weg(self):
        result = insights.filter_rows(self.rows, None, None, ["gpt-5.6-sol"])
        self.assertEqual(len(result), 1)


class ProjectInsightsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row("2026-09-01", "-a-lumo", "lumo", 100.0, [bd("claude-opus-5", 100.0)]),
            row("2026-09-01", "-a-dash", "dash", 25.0, [bd("claude-sonnet-5", 25.0)]),
            row("2026-09-03", "-a-lumo", "lumo", 75.0, [bd("claude-opus-5", 75.0)]),
        ]

    def test_kpis(self):
        k = insights.project_insights(self.rows)["kpis"]
        self.assertEqual(k["projectCount"], 2)
        self.assertEqual(k["topProject"], "lumo")
        self.assertAlmostEqual(k["topProjectCost"], 175.0)
        self.assertAlmostEqual(k["topProjectShare"], 175.0 / 200.0)
        self.assertAlmostEqual(k["totalCost"], 200.0)

    def test_fehlender_tag_ist_luecke_keine_null(self):
        """Der 02.09. fehlt in den Daten, muss aber auf der Achse stehen.

        Sonst grenzt der 01.09. direkt an den 03.09. und das Diagramm
        behauptet durchgehende Nutzung.
        """
        stacked = insights.project_insights(self.rows)["stacked"]
        self.assertEqual(stacked["labels"],
                         ["2026-09-01", "2026-09-02", "2026-09-03"])
        dash = next(d for d in stacked["datasets"] if d["label"] == "dash")
        self.assertEqual(dash["cost"], [25.0, None, None])
        lumo = next(d for d in stacked["datasets"] if d["label"] == "lumo")
        self.assertEqual(lumo["cost"], [100.0, None, 75.0])

    def test_kennzahl_tage_zaehlt_nur_tage_mit_daten(self):
        kpis = insights.project_insights(self.rows)["kpis"]
        self.assertEqual(kpis["days"], 2)

    def test_tabelle_sortiert_und_mit_anteil(self):
        table = insights.project_insights(self.rows)["table"]
        self.assertEqual([t["projectLabel"] for t in table], ["lumo", "dash"])
        self.assertAlmostEqual(table[0]["share"], 0.875)
        self.assertEqual(table[0]["days"], 2)
        self.assertIsNotNone(table[0]["costPerMillion"])

    def test_sammelposten_sonstige_ab_neun_projekten(self):
        rows = [row("2026-09-01", f"-a-p{i}", f"p{i}", float(20 - i),
                    [bd("claude-opus-5", float(20 - i))]) for i in range(12)]
        datasets = insights.project_insights(rows)["stacked"]["datasets"]
        self.assertEqual(len(datasets), insights.TOP_PROJECTS + 1)
        self.assertTrue(datasets[-1]["isOther"])
        self.assertEqual(datasets[-1]["label"], "")
        self.assertFalse(any(d["isOther"] for d in datasets[:-1]))

    def test_projekt_namens_sonstige_faellt_nicht_in_den_sammelposten(self):
        """Der Restbucket hat keinen darstellbaren Namen mehr.

        Vorher lief die Zuordnung ueber ``row["projectLabel"] in buckets``
        gegen den deutschen Klartext "Sonstige"; ein gleichnamiges Projekt
        waere stillschweigend mit dem Rest verschmolzen.
        """
        rows = [row("2026-09-01", "-a-sonstige", "Sonstige", 100.0,
                    [bd("claude-opus-5", 100.0)])]
        rows += [row("2026-09-01", f"-a-p{i}", f"p{i}", float(20 - i),
                     [bd("claude-opus-5", float(20 - i))]) for i in range(12)]
        datasets = insights.project_insights(rows)["stacked"]["datasets"]
        named = [d for d in datasets if d["label"] == "Sonstige"]
        self.assertEqual(len(named), 1)
        self.assertFalse(named[0]["isOther"])

    def test_leere_eingabe(self):
        result = insights.project_insights([])
        self.assertEqual(result["kpis"]["projectCount"], 0)
        self.assertEqual(result["table"], [])
        self.assertEqual(result["stacked"]["labels"], [])


def session(sid, first, last, label, cost, breakdowns, minutes):
    fields = ("inputTokens", "outputTokens", "cacheCreationTokens",
              "cacheReadTokens")
    entry = {"sessionId": sid, "project": "-a-" + label, "projectLabel": label,
             "first": first, "last": last, "date": first[:10],
             "durationMinutes": minutes, "sourceFile": "test.json",
             "modelBreakdowns": breakdowns,
             "modelsUsed": sorted({b["modelName"] for b in breakdowns}),
             "totalCost": cost}
    for f in fields:
        entry[f] = sum(b[f] for b in breakdowns)
    entry["totalTokens"] = sum(entry[f] for f in fields)
    entry["sumTokens"] = entry["totalTokens"]
    return entry


class SessionInsightsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            session("s1", "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z",
                    "lumo", 0.05, [bd("claude-haiku-4-5-20251001", 0.05)], 60),
            session("s2", "2026-09-01T12:00:00Z", "2026-09-01T14:00:00Z",
                    "lumo", 3.0, [bd("claude-sonnet-5", 3.0)], 120),
            session("s3", "2026-09-02T09:00:00Z", "2026-09-02T18:00:00Z",
                    "dash", 158.0, [bd("claude-opus-5", 158.0)], 540),
        ]

    def test_kpis(self):
        k = insights.session_insights(self.rows)["kpis"]
        self.assertEqual(k["sessionCount"], 3)
        self.assertAlmostEqual(k["medianCost"], 3.0)
        self.assertAlmostEqual(k["maxCost"], 158.0)
        self.assertEqual(k["maxSessionProject"], "dash")
        self.assertEqual(k["medianDurationMinutes"], 120)
        self.assertAlmostEqual(k["totalCost"], 161.05)

    def test_top_liste_absteigend_und_begrenzt(self):
        top = insights.session_insights(self.rows)["top"]
        self.assertEqual([t["sessionId"] for t in top], ["s3", "s2", "s1"])
        self.assertEqual(top[0]["projectLabel"], "dash")
        self.assertEqual(top[0]["durationMinutes"], 540)
        self.assertEqual(top[0]["modelsUsed"], ["claude-opus-5"])

    def test_histogramm_klassen(self):
        h = insights.session_insights(self.rows)["histogram"]
        self.assertEqual(len(h["counts"]), 6)
        self.assertEqual(h["counts"], [1, 0, 1, 0, 0, 1])
        self.assertAlmostEqual(h["cost"][-1], 158.0)

    def test_klassengrenze_gehoert_zur_oberen_klasse(self):
        """Genau 50 $ faellt in die oberste Klasse, nicht in die darunter."""
        rows = [
            session("s1", "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z",
                    "lumo", 50.0, [bd("claude-opus-5", 50.0)], 60),
            session("s2", "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z",
                    "lumo", 49.99, [bd("claude-opus-5", 49.99)], 60),
            session("s3", "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z",
                    "lumo", 0.10, [bd("claude-opus-5", 0.10)], 60),
        ]
        h = insights.session_insights(rows)["histogram"]
        self.assertEqual(h["counts"], [0, 1, 0, 0, 1, 1])

    def test_histogramm_hat_eine_klasse_mehr_als_grenzen(self):
        h = insights.session_insights(self.rows)["histogram"]
        self.assertEqual(h["bounds"], list(insights.HISTOGRAM_BOUNDS))
        self.assertEqual(len(h["counts"]), len(insights.HISTOGRAM_BOUNDS) + 1)
        self.assertEqual(len(h["cost"]), len(h["counts"]))
        self.assertNotIn("labels", h)

    def test_zeitraumfilter_greift_auf_erstem_tag(self):
        result = insights.session_insights(self.rows, "2026-09-02", None)
        self.assertEqual(result["kpis"]["sessionCount"], 1)

    def test_leere_eingabe(self):
        result = insights.session_insights([])
        self.assertEqual(result["kpis"]["sessionCount"], 0)
        self.assertIsNone(result["kpis"]["medianCost"])
        self.assertEqual(result["top"], [])




def block(bid, start, end, cost, tokens, gap=False, active=False, burn=None,
          minutes=300):
    return {"id": bid, "start": start, "end": end, "actualEnd": end,
            "date": start[:10], "isGap": gap, "isActive": active,
            "entries": 0 if gap else 100, "cost": cost, "totalTokens": tokens,
            "sumTokens": tokens, "inputTokens": 0, "outputTokens": 0,
            "cacheCreationTokens": 0, "cacheReadTokens": tokens,
            "models": [] if gap else ["claude-opus-5"],
            "burnRateCostPerHour": burn, "burnRateTokensPerMinute": None,
            "projectionCost": None, "projectionTokens": None,
            "projectionRemainingMinutes": None,
            "durationMinutes": minutes, "sourceFile": "test.json"}


class BlockInsightsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            block("b1", "2026-09-01T04:00:00Z", "2026-09-01T09:00:00Z",
                  100.0, 1000, burn=20.0),
            block("gap-1", "2026-09-01T09:00:00Z", "2026-09-02T08:00:00Z",
                  0.0, 0, gap=True, minutes=1380),
            block("b2", "2026-09-02T08:00:00Z", "2026-09-02T13:00:00Z",
                  60.0, 600, burn=12.0, active=True),
        ]

    def test_kpis_ohne_gaps(self):
        k = insights.block_insights(self.rows)["kpis"]
        self.assertEqual(k["blockCount"], 2)
        self.assertEqual(k["gapCount"], 1)
        self.assertAlmostEqual(k["maxCost"], 100.0)
        self.assertEqual(k["maxBlockStart"], "2026-09-01T04:00:00Z")
        self.assertAlmostEqual(k["meanCost"], 80.0)
        self.assertAlmostEqual(k["totalCost"], 160.0)

    def test_anteil_zeit_mit_nutzung(self):
        k = insights.block_insights(self.rows)["kpis"]
        self.assertAlmostEqual(k["activeShare"], 600 / 1980)

    def test_gaps_bleiben_in_der_zeitleiste_ohne_kosten(self):
        points = insights.block_insights(self.rows)["timeline"]["points"]
        self.assertEqual(len(points), 3)
        self.assertTrue(points[1]["isGap"])
        self.assertIsNone(points[1]["cost"])

    def test_aktiver_block_wird_ausgewiesen(self):
        result = insights.block_insights(self.rows)
        self.assertEqual(result["active"]["id"], "b2")
        self.assertFalse(result["modelFilterSupported"])

    def test_zeitraumfilter(self):
        result = insights.block_insights(self.rows, "2026-09-02", None)
        self.assertEqual(result["kpis"]["blockCount"], 1)

    def test_leere_eingabe(self):
        result = insights.block_insights([])
        self.assertEqual(result["kpis"]["blockCount"], 0)
        self.assertIsNone(result["active"])
        self.assertEqual(result["timeline"]["points"], [])


def rtk_day(date, commands, input_tokens, saved_tokens, total_time_ms,
            output_tokens=0, avg_time_ms=0):
    savings_pct = (saved_tokens / input_tokens * 100) if input_tokens else 0.0
    return {"date": date, "month": date[:7], "commands": commands,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "saved_tokens": saved_tokens, "savings_pct": savings_pct,
            "total_time_ms": total_time_ms, "avg_time_ms": avg_time_ms,
            "sourceFile": "test.json"}


class RtkInsightsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            rtk_day("2026-09-01", 10, 10000, 3000, 1000),
            rtk_day("2026-09-03", 20, 20000, 7000, 2000),
        ]

    def test_kacheln(self):
        k = insights.rtk_insights(self.rows)["kpis"]
        self.assertEqual(k["savedTokens"], 10000)
        self.assertAlmostEqual(k["savingsRate"], 10000 / 30000)
        self.assertEqual(k["commands"], 30)
        self.assertAlmostEqual(k["savedTokensPerCommand"], 10000 / 30)
        self.assertEqual(k["totalTimeMs"], 3000)
        self.assertAlmostEqual(k["avgTimeMsPerCommand"], 3000 / 30)

    def test_leere_auswahl_liefert_null_kacheln(self):
        k = insights.rtk_insights([])["kpis"]
        self.assertIsNone(k["savedTokens"])
        self.assertIsNone(k["savingsRate"])
        self.assertIsNone(k["commands"])
        self.assertIsNone(k["savedTokensPerCommand"])
        self.assertIsNone(k["totalTimeMs"])
        self.assertIsNone(k["avgTimeMsPerCommand"])

    def test_zeitraumfilter(self):
        result = insights.rtk_insights(self.rows, "2026-09-02", None)
        self.assertEqual(result["kpis"]["commands"], 20)
        self.assertEqual(result["kpis"]["savedTokens"], 7000)

    def test_kalenderachse_mit_luecke(self):
        """Der 02.09. fehlt in den Rohdaten, muss aber als Luecke auftauchen."""
        daily = insights.rtk_insights(self.rows)["daily"]
        self.assertEqual(daily["labels"],
                         ["2026-09-01", "2026-09-02", "2026-09-03"])
        self.assertEqual(daily["savedTokens"], [3000, None, 7000])
        self.assertIsNone(daily["savingsRate"][1])

    def test_sparquote_ist_die_quote_der_summen_nicht_das_mittel(self):
        """Zwei Tage mit stark ungleicher Befehlszahl.

        Tag 1: wenige Befehle, sehr hohe Tagesquote (90 %).
        Tag 2: viele Befehle, sehr niedrige Tagesquote (10 %).
        Das Mittel der Tagesquoten waere 50 %, die Quote der Summen liegt bei
        rund 10,79 %. Rechnet ``rtk_insights`` versehentlich das Mittel der
        Tagesquoten statt die Quote der Summen, faellt dieser Test durch.
        """
        rows = [
            rtk_day("2026-09-01", 1, 100, 90, 10),
            rtk_day("2026-09-02", 100, 10000, 1000, 1000),
        ]
        k = insights.rtk_insights(rows)["kpis"]
        summenquote = (90 + 1000) / (100 + 10000)
        mittel_der_tagesquoten = (0.9 + 0.1) / 2
        self.assertAlmostEqual(k["savingsRate"], summenquote)
        self.assertNotAlmostEqual(k["savingsRate"], mittel_der_tagesquoten,
                                  places=2)

    def test_modellfilter_wird_nicht_unterstuetzt(self):
        result = insights.rtk_insights(self.rows)
        self.assertFalse(result["modelFilterSupported"])

    def test_eingabe_ohne_tokens_traegt_nichts_zur_quote_bei(self):
        """Ein Tag mit input_tokens gleich null darf nicht durch null teilen."""
        rows = [
            rtk_day("2026-09-01", 0, 0, 0, 0),
            rtk_day("2026-09-02", 5, 1000, 400, 500),
        ]
        k = insights.rtk_insights(rows)["kpis"]
        self.assertAlmostEqual(k["savingsRate"], 400 / 1000)
        daily = insights.rtk_insights(rows)["daily"]
        self.assertIsNone(daily["savingsRate"][0])

    def test_monate_werden_aus_den_gefilterten_tagen_aggregiert(self):
        """Monatstabelle der Oberflaeche: Summen je Monat, aufsteigend sortiert."""
        rows = [
            rtk_day("2026-08-30", 5, 5000, 1000, 100),
            rtk_day("2026-09-01", 10, 10000, 3000, 1000),
            rtk_day("2026-09-03", 20, 20000, 7000, 2000),
        ]
        months = insights.rtk_insights(rows)["months"]
        self.assertEqual([m["month"] for m in months], ["2026-08", "2026-09"])
        self.assertEqual(months[0]["commands"], 5)
        self.assertEqual(months[0]["inputTokens"], 5000)
        self.assertEqual(months[0]["savedTokens"], 1000)
        self.assertAlmostEqual(months[0]["savingsRate"], 1000 / 5000)
        self.assertEqual(months[1]["commands"], 30)
        self.assertEqual(months[1]["inputTokens"], 30000)
        self.assertEqual(months[1]["savedTokens"], 10000)
        self.assertAlmostEqual(months[1]["savingsRate"], 10000 / 30000)

    def test_monatsquote_ist_die_quote_der_summen_nicht_das_mittel(self):
        """Derselbe Adversarial-Fall wie bei der KPI-Kachel, aber fuer months.

        Beide Tage liegen im selben Monat: 1 Befehl mit sehr hoher Tagesquote
        (90 %) gegen 100 Befehle mit sehr niedriger Tagesquote (10 %). Das
        Mittel der Tagesquoten waere 50 %, die Quote der Summen liegt bei
        rund 10,79 %.
        """
        rows = [
            rtk_day("2026-09-01", 1, 100, 90, 10),
            rtk_day("2026-09-02", 100, 10000, 1000, 1000),
        ]
        months = insights.rtk_insights(rows)["months"]
        summenquote = (90 + 1000) / (100 + 10000)
        mittel_der_tagesquoten = (0.9 + 0.1) / 2
        self.assertAlmostEqual(months[0]["savingsRate"], summenquote)
        self.assertNotAlmostEqual(months[0]["savingsRate"],
                                  mittel_der_tagesquoten, places=2)

    def test_zeitraumfilter_wirkt_auch_auf_monate(self):
        rows = [
            rtk_day("2026-08-30", 5, 5000, 1000, 100),
            rtk_day("2026-09-01", 10, 10000, 3000, 1000),
            rtk_day("2026-09-03", 20, 20000, 7000, 2000),
        ]
        months = insights.rtk_insights(rows, "2026-09-02", None)["months"]
        self.assertEqual([m["month"] for m in months], ["2026-09"])
        self.assertEqual(months[0]["commands"], 20)
        self.assertEqual(months[0]["inputTokens"], 20000)
        self.assertEqual(months[0]["savedTokens"], 7000)

    def test_monat_ohne_rohausgabe_traegt_keine_quote_und_keine_division_durch_null(self):
        rows = [
            rtk_day("2026-09-01", 3, 0, 0, 50),
            rtk_day("2026-09-02", 2, 0, 0, 30),
        ]
        months = insights.rtk_insights(rows)["months"]
        self.assertEqual(len(months), 1)
        self.assertEqual(months[0]["commands"], 5)
        self.assertEqual(months[0]["inputTokens"], 0)
        self.assertEqual(months[0]["savedTokens"], 0)
        self.assertIsNone(months[0]["savingsRate"])


class AgentSeriesTests(unittest.TestCase):
    def test_umschaltstelle_wird_gemeldet(self):
        split = [
            {"date": "2026-08-31", "source": "heuristik",
             "agents": {"claude": {"cost": 5.0, "tokens": 10}}},
            {"date": "2026-09-01", "source": "agents",
             "agents": {"claude": {"cost": 8.0, "tokens": 20},
                        "codex": {"cost": 2.0, "tokens": 4}}},
        ]
        result = insights.agent_series(split)
        self.assertEqual(result["firstAgentsDate"], "2026-09-01")
        self.assertEqual(result["labels"], ["2026-08-31", "2026-09-01"])
        codex = next(d for d in result["datasets"] if d["label"] == "codex")
        self.assertEqual(codex["cost"], [None, 2.0])

    def test_fehlender_kalendertag_bleibt_luecke_auf_der_achse(self):
        """Zwischen dem 20.05. und dem 23.05. liegen zwei Tage ohne Nutzung.

        Gegen die echten Daten fehlen im Agent-Chart fuenf solche Tage. Ohne
        sie ruecken die Balken zusammen und taeuschen durchgehende Nutzung vor.
        """
        split = [
            {"date": "2026-05-20", "source": "heuristik",
             "agents": {"claude": {"cost": 5.0, "tokens": 10}}},
            {"date": "2026-05-23", "source": "heuristik",
             "agents": {"claude": {"cost": 7.0, "tokens": 14}}},
        ]
        result = insights.agent_series(split)
        self.assertEqual(result["labels"], ["2026-05-20", "2026-05-21",
                                            "2026-05-22", "2026-05-23"])
        claude = next(d for d in result["datasets"] if d["label"] == "claude")
        self.assertEqual(claude["cost"], [5.0, None, None, 7.0])
        self.assertEqual(claude["tokens"], [10, None, None, 14])
        self.assertEqual(result["sources"],
                         ["heuristik", None, None, "heuristik"])

    def test_leere_eingabe(self):
        result = insights.agent_series([])
        self.assertEqual(result["labels"], [])
        self.assertEqual(result["datasets"], [])
        self.assertIsNone(result["firstAgentsDate"])


class RealDataReferenceTests(unittest.TestCase):
    """Prueft gegen die echten Dateien. Wird uebersprungen, wenn sie fehlen."""

    @classmethod
    def setUpClass(cls):
        cls.directory = require_real_data()
        cls.extras = sources.load_extras(cls.directory)
        if not cls.extras["projects"]["rows"]:
            raise unittest.SkipTest("Keine Zusatzquellen im Datenverzeichnis.")

    def test_projekte_september_summieren_auf_totals(self):
        """KPIs der Septemberprojekte gegen das totals-Feld der Quelldatei.

        Bewusst kein fester Betrag: September ist der laufende Monat und
        waechst mit jedem daily-Lauf. Verglichen wird gegen die Referenz,
        die ccusage in derselben Datei mitliefert, damit beide Seiten
        gemeinsam wachsen. Geprueft wird damit die Aggregation in
        insights.project_insights; check_extras vergleicht dagegen die
        Rohzeilen mit denselben totals.
        """
        info = next((f for f in self.extras["projects"]["files"]
                     if f["name"] == "2026-09.json"), None)
        if info is None or not info["hasTotals"]:
            self.skipTest("projects/2026-09.json fehlt oder hat kein totals.")
        rows = [r for r in self.extras["projects"]["rows"]
                if r["month"] == "2026-09"]
        result = insights.project_insights(rows)
        self.assertAlmostEqual(result["kpis"]["totalCost"],
                               info["totals"]["totalCost"], places=4)
        self.assertGreaterEqual(result["kpis"]["projectCount"], 3)

    def test_sessions_und_bloecke_summieren_gleich(self):
        sessions = insights.session_insights(self.extras["sessions"]["rows"])
        blocks = insights.block_insights(self.extras["blocks"]["rows"])
        self.assertAlmostEqual(sessions["kpis"]["totalCost"],
                               blocks["kpis"]["totalCost"], places=2)

    def test_bloecke_w36_kennzahlen(self):
        """KPIs der Wochendatei gegen die Rohdatei, nicht gegen feste Zahlen.

        Der Wochenlauf mischt jeden Export in die bestehende Datei, die dadurch
        mit jedem Lauf waechst. Feste Erwartungswerte veralten hier also
        planmaessig. Die Rohdatei dient stattdessen als unabhaengige Referenz:
        sie wird direkt gezaehlt, waehrend die linke Seite den Weg ueber
        sources.load_extras und insights.block_insights nimmt. Ein Fehler in
        einer der beiden Stufen faellt damit weiterhin auf.
        """
        datei = self.directory / "blocks" / "2026-W36.json"
        if not datei.is_file():
            self.skipTest("blocks/2026-W36.json liegt nicht vor.")
        roh = json.loads(datei.read_text(encoding="utf-8"))["blocks"]
        bloecke = [b for b in roh if not b.get("isGap")]
        luecken = [b for b in roh if b.get("isGap")]

        rows = [r for r in self.extras["blocks"]["rows"]
                if r["sourceFile"] == "2026-W36.json"]
        result = insights.block_insights(rows)

        self.assertEqual(result["kpis"]["blockCount"], len(bloecke))
        self.assertEqual(result["kpis"]["gapCount"], len(luecken))
        self.assertAlmostEqual(result["kpis"]["maxCost"],
                               max(b["costUSD"] for b in bloecke), places=2)

    def test_rtk_september_summiert_gegen_rohdatei(self):
        """rtk-Kennzahlen fuer September gegen die Summen der Rohdatei.

        Kein fester Betrag: September ist der laufende Monat und waechst mit
        jedem rtk-Export. Verglichen wird gegen die Summen aus den geladenen
        Zeilen selbst, nicht gegen eine eingetragene Zahl.
        """
        if not (self.directory / "rtk").is_dir():
            self.skipTest("Keine rtk-Exporte im Datenverzeichnis.")
        rows = [r for r in self.extras["rtk"]["rows"] if r["month"] == "2026-09"]
        if not rows:
            self.skipTest("Keine rtk-Zeilen fuer September.")
        result = insights.rtk_insights(rows)
        total_saved = sum(r["saved_tokens"] for r in rows)
        total_input = sum(r["input_tokens"] for r in rows)
        total_commands = sum(r["commands"] for r in rows)
        self.assertEqual(result["kpis"]["savedTokens"], total_saved)
        self.assertEqual(result["kpis"]["commands"], total_commands)
        self.assertAlmostEqual(result["kpis"]["savingsRate"],
                               total_saved / total_input, places=6)

    def test_wochendatei_ist_frei_von_doppelten_block_ids(self):
        """Das Zusammenfuehren darf keinen Block zweimal ablegen."""
        datei = self.directory / "blocks" / "2026-W36.json"
        if not datei.is_file():
            self.skipTest("blocks/2026-W36.json liegt nicht vor.")
        ids = [b["id"] for b in json.loads(datei.read_text(encoding="utf-8"))["blocks"]]

        self.assertEqual(len(ids), len(set(ids)))

    def test_plausibilitaet_meldet_nur_den_bekannten_august_ruecksschritt(self):
        """Die Plausibilitaetspruefung soll leer sein - bis auf einen Fall.

        logs/monthly.log haelt fest, dass der monatliche Export fuer August
        2026 mit "RUECKSCHRITT" abgebrochen wurde: die JSONL-Quellen waren zu
        diesem Zeitpunkt bereits abgeschnitten, projects/2026-08.json wurde
        trotzdem mit dem verkuerzten Stand (40 Zeilen, 4049.94 $) geschrieben,
        waehrend die Monatsdatei 2026-08.json beim alten, vollstaendigen Stand
        (31 Tage, 4739.12 $) blieb. Die Kreuzpruefung meldet genau diese eine
        bekannte Abweichung. Jede weitere oder andere Meldung ist ein neuer,
        bisher unbekannter Befund und soll den Test scheitern lassen.
        """
        dataset = loader.load_directory(self.directory)
        result = sources.check_extras(self.extras, dataset["days"])
        self.assertEqual(
            len(result["issues"]), 1,
            "Erwartet wird ausschliesslich der dokumentierte August-"
            "Ruecksschritt aus logs/monthly.log, keine weitere Abweichung.",
        )
        issue = result["issues"][0]
        self.assertEqual(
            {k: issue[k] for k in ("level", "scope", "key", "code")},
            {"level": "warn", "scope": "kreuzpruefung", "key": "2026-08",
             "code": "check.crosscheck.cost_mismatch"})
        # Die Rohsummen sind Gleitkommasummen; der alte Text rundete ueber
        # f"{...:.2f}". Der Vergleich rundet jetzt an derselben Stelle.
        self.assertAlmostEqual(issue["params"]["projectSum"], 4049.94, places=2)
        self.assertAlmostEqual(issue["params"]["monthlySum"], 4739.12, places=2)


if __name__ == "__main__":
    unittest.main()

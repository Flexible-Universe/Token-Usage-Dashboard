"""Prueft den Generator fuer Beispieldaten und den ganzen Lesepfad darauf."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import BASE_DIR, require_real_data  # noqa: F401  - setzt sys.path

import insights
import loader
import metrics
import sources

GENERATOR = BASE_DIR / "tools" / "make-sample-data.py"


def _erzeuge(ziel: Path) -> None:
    """Ruft den Generator auf. Ein Fehlschlag ist ein Fehlschlag des Tests."""
    subprocess.run(
        [sys.executable, str(GENERATOR), "--out", str(ziel),
         "--today", "2026-09-10"],
        check=True, capture_output=True, text=True,
    )


class GeneratorTests(unittest.TestCase):
    def test_erzeugt_fuenf_monatsdateien_und_alle_zusatzquellen(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sample-data"
            _erzeuge(out)
            monate = sorted(p.name for p in out.glob("20*-*.json"))
            self.assertEqual(
                monate,
                ["2026-05.json", "2026-06.json", "2026-07.json",
                 "2026-08.json", "2026-09.json"],
            )
            self.assertTrue(list((out / "projects").glob("*.json")))
            self.assertTrue(list((out / "blocks").glob("*.json")))
            self.assertTrue(list((out / "sessions").glob("*.json")))
            self.assertTrue(list((out / "rtk").glob("*.json")))


class RauchtestTests(unittest.TestCase):
    """Schickt die erzeugten Beispieldaten durch den ganzen Lesepfad.

    Der erste Test dieses Projekts, der bei jedem laeuft und nicht nur
    synthetische Einzelfaelle prueft: Generator, loader, sources, metrics und
    insights in einem Durchgang.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "sample-data"
        _erzeuge(cls.out)
        cls.dataset = loader.load_directory(cls.out)
        cls.extras = sources.load_extras(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_alle_dateien_werden_angenommen(self):
        self.assertTrue(self.dataset["files"])
        self.assertTrue(all(f["accepted"] for f in self.dataset["files"]))
        self.assertEqual(self.dataset["errors"], [])
        self.assertEqual(self.extras["errors"], [])

    def test_plausibilitaet_ist_ohne_befund(self):
        health = loader.check_plausibility(self.dataset)
        self.assertEqual(health["issues"], [])
        self.assertTrue(health["ok"])

    def test_kreuzpruefung_der_zusatzquellen_ist_ohne_befund(self):
        result = sources.check_extras(self.extras, self.dataset["days"])
        self.assertEqual(result["issues"], [])

    def test_kennzahlen_sind_belegt(self):
        result = metrics.compute_metrics(self.dataset["days"])
        self.assertGreater(result["summary"]["daysWithData"], 0)
        self.assertGreater(result["summary"]["totalCost"], 0)
        self.assertEqual(len(result["months"]), 5)
        self.assertTrue(result["models"])

    def test_fehlende_kalendertage_sind_luecken(self):
        serie = metrics.compute_metrics(self.dataset["days"])["dailySeries"]
        self.assertIn(None, serie["cost"],
                      "Der Generator muss Kalendertage auslassen, sonst "
                      "prueft die Vorfuehrung die Luecken-Regel nicht.")

    def test_beide_monatsschemata_kommen_vor(self):
        schemata = {s for f in self.dataset["files"] for s in f["schemas"]}
        self.assertGreater(len(schemata), 1, f"Nur ein Schema: {schemata}")

    def test_leerlaufbloecke_und_deduplizierung(self):
        rows = self.extras["blocks"]["rows"]
        self.assertTrue(any(r["isGap"] for r in rows))
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)),
                         "Bloecke muessen ueber id dedupliziert werden.")

    def test_kennzahlen_der_zusatzquellen_sind_belegt(self):
        self.assertTrue(insights.project_insights(
            self.extras["projects"]["rows"])["table"])
        self.assertTrue(insights.session_insights(
            self.extras["sessions"]["rows"])["kpis"])
        self.assertTrue(insights.block_insights(
            self.extras["blocks"]["rows"])["kpis"])
        self.assertTrue(insights.rtk_insights(
            self.extras["rtk"]["rows"])["kpis"])

    def test_rtk_reicht_weiter_zurueck_als_die_uebrigen_quellen(self):
        rtk_erster = min(r["date"] for r in self.extras["rtk"]["rows"])
        proj_erster = min(r["date"] for r in self.extras["projects"]["rows"])
        self.assertLess(rtk_erster, proj_erster)


class SchemaAbgleichTests(unittest.TestCase):
    """Vergleicht die Schluesselmengen der Beispieldaten mit den echten.

    Die Gegenprobe gegen einen zu braven Generator: Beispieldaten, die
    Felder der echten Quelle nicht kennen, erzeugen eine falsche Sicherheit.
    Faellt der Abgleich aus, weil TOKEN_DASHBOARD_REAL_DATA nicht gesetzt
    ist, wird das gemeldet - ein uebersprungener Pruefschritt darf nicht wie
    eine bestandene Gegenprobe aussehen.
    """

    @classmethod
    def setUpClass(cls):
        cls.echt = require_real_data()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "sample-data"
        _erzeuge(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _tagesschluessel(self, verzeichnis: Path) -> set[str]:
        schluessel: set[str] = set()
        for datei in sorted(verzeichnis.glob("20*-*.json")):
            payload = json.loads(datei.read_text(encoding="utf-8"))
            for tag in payload["daily"]:
                schluessel |= set(tag)
        return schluessel

    def test_monatsdateien_kennen_alle_echten_felder(self):
        fehlend = self._tagesschluessel(self.echt) - self._tagesschluessel(self.out)
        self.assertEqual(
            fehlend, set(),
            f"Der Generator kennt diese Felder der echten Quelle nicht: "
            f"{sorted(fehlend)}",
        )

    def test_zusatzquellen_kennen_alle_echten_felder(self):
        echt = sources.load_extras(self.echt)
        beispiel = sources.load_extras(self.out)
        for quelle in ("projects", "sessions", "blocks", "rtk"):
            with self.subTest(quelle=quelle):
                echte = {k for r in echt[quelle]["rows"] for k in r}
                unsere = {k for r in beispiel[quelle]["rows"] for k in r}
                self.assertEqual(
                    echte - unsere, set(),
                    f"{quelle}: fehlende Felder {sorted(echte - unsere)}",
                )


if __name__ == "__main__":
    unittest.main()

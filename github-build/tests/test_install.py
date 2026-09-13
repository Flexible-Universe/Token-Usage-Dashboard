"""Prueft install.sh ueber --dry-run und die Argumentbehandlung.

Das Skript richtet ein Datenverzeichnis ein und greift mit
``--with-launchagents`` in launchd ein. Beides laesst sich in einem Testlauf
nicht folgenlos ausfuehren, deshalb pruefen diese Tests ausschliesslich
``--dry-run``: was das Skript ankuendigt, und dass es dabei nichts anlegt.
Die vier Bereiche, in denen ein Fehler teuer waere, sind damit abgedeckt:
Optionsfehler, Platzhalterersetzung, der Umgang mit einer bestehenden
config.toml und die Beschraenkung auf macOS.
"""

from __future__ import annotations

import os
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import BASE_DIR  # noqa: F401  - setzt sys.path

SKRIPT = BASE_DIR / "install.sh"
IST_MACOS = platform.system() == "Darwin"


def lauf(*args, cwd=None):
    """Ruft install.sh auf und gibt das CompletedProcess zurueck."""
    return subprocess.run(
        ["bash", str(SKRIPT), *args],
        cwd=str(cwd or BASE_DIR),
        capture_output=True,
        text=True,
    )


class OptionenTests(unittest.TestCase):
    def test_skript_ist_ausfuehrbar_und_syntaktisch_heil(self):
        self.assertTrue(SKRIPT.is_file(), "install.sh fehlt")
        self.assertTrue(os.access(SKRIPT, os.X_OK), "install.sh ist nicht ausfuehrbar")
        fertig = subprocess.run(["bash", "-n", str(SKRIPT)], capture_output=True, text=True)
        self.assertEqual(fertig.returncode, 0, fertig.stderr)

    def test_hilfe_nennt_die_optionen(self):
        fertig = lauf("--help")
        self.assertEqual(fertig.returncode, 0, fertig.stderr)
        for option in ("--with-launchagents", "--label-prefix", "--data-dir",
                       "--force", "--dry-run"):
            self.assertIn(option, fertig.stdout)

    def test_unbekannte_option_bricht_ab(self):
        fertig = lauf("--gibtesnicht")
        self.assertNotEqual(fertig.returncode, 0)
        self.assertIn("--gibtesnicht", fertig.stdout + fertig.stderr)

    def test_option_ohne_wert_bricht_ab(self):
        fertig = lauf("--data-dir")
        self.assertNotEqual(fertig.returncode, 0)


class TrockenlaufTests(unittest.TestCase):
    """``--dry-run`` darf ankuendigen, aber nichts anlegen."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ziel = Path(self._tmp.name) / "daten"

    def tearDown(self):
        self._tmp.cleanup()

    def test_legt_nichts_an(self):
        fertig = lauf("--dry-run", "--data-dir", str(self.ziel))
        self.assertEqual(fertig.returncode, 0, fertig.stderr)
        self.assertFalse(self.ziel.exists(), "--dry-run hat das Verzeichnis angelegt")

    def test_nennt_die_fuenf_skripte_und_das_bin_verzeichnis(self):
        fertig = lauf("--dry-run", "--data-dir", str(self.ziel))
        for name in ("ccusage-export.sh", "rtk-export.sh", "ccusage-check.py",
                     "ccusage-merge.py", "rtk-merge.py"):
            self.assertIn(name, fertig.stdout)
        self.assertIn("bin", fertig.stdout)

    def test_ruehrt_bestehende_config_nicht_an(self):
        """Die config.toml des Repositories darf der Lauf nicht veraendern."""
        config = BASE_DIR / "config.toml"
        vorher = config.read_bytes() if config.exists() else None
        fertig = lauf("--dry-run", "--data-dir", str(self.ziel))
        self.assertEqual(fertig.returncode, 0, fertig.stderr)
        nachher = config.read_bytes() if config.exists() else None
        self.assertEqual(vorher, nachher)

    def test_meldet_bestehende_config_statt_sie_zu_ueberschreiben(self):
        """Kein stiller Fallback: eine vorhandene config.toml wird genannt."""
        config = BASE_DIR / "config.toml"
        if not config.exists():
            self.skipTest("Im Arbeitsbaum liegt keine config.toml.")
        fertig = lauf("--dry-run", "--data-dir", str(self.ziel))
        self.assertIn("config.toml", fertig.stdout)
        self.assertRegex(fertig.stdout, r"(?i)bleibt|vorhanden|unveraendert")


class LaunchAgentsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ziel = Path(self._tmp.name) / "daten"

    def tearDown(self):
        self._tmp.cleanup()

    @unittest.skipUnless(IST_MACOS, "launchd gibt es nur auf macOS.")
    def test_trockenlauf_setzt_die_platzhalter_ein(self):
        fertig = lauf("--with-launchagents", "--dry-run",
                      "--data-dir", str(self.ziel),
                      "--label-prefix", "com.testfall")
        self.assertEqual(fertig.returncode, 0, fertig.stderr)
        for job in ("ccusage-daily", "ccusage-weekly", "ccusage-monthly", "rtk-daily"):
            self.assertIn(f"com.testfall.{job}", fertig.stdout)
        self.assertNotIn("__SCRIPT_DIR__", fertig.stdout)
        self.assertNotIn("__DATA_DIR__", fertig.stdout)
        self.assertNotIn("__LABEL_PREFIX__", fertig.stdout)

    @unittest.skipIf(IST_MACOS, "Der Abbruch greift nur ausserhalb von macOS.")
    def test_bricht_ausserhalb_von_macos_ab(self):
        fertig = lauf("--with-launchagents", "--dry-run", "--data-dir", str(self.ziel))
        self.assertEqual(fertig.returncode, 2)
        self.assertIn("macOS", fertig.stdout + fertig.stderr)

    def test_label_praefix_ohne_launchagents_ist_ein_fehler(self):
        """Sonst glaubt der Aufrufer, er haette die Jobs eingerichtet."""
        fertig = lauf("--dry-run", "--label-prefix", "com.testfall",
                      "--data-dir", str(self.ziel))
        self.assertNotEqual(fertig.returncode, 0)
        self.assertIn("--with-launchagents", fertig.stdout + fertig.stderr)


if __name__ == "__main__":
    unittest.main()

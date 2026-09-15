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
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import BASE_DIR  # noqa: F401  - setzt sys.path

SKRIPT = BASE_DIR / "install.sh"
IST_MACOS = platform.system() == "Darwin"


def lauf(*args, cwd=None, eingabe=None, env=None):
    """Ruft install.sh auf und gibt das CompletedProcess zurueck."""
    return subprocess.run(
        ["/bin/bash", str(SKRIPT), *args],
        cwd=str(cwd or BASE_DIR),
        capture_output=True,
        text=True,
        input=eingabe,
        env=env,
    )


def umgebung_ohne_live_werkzeuge(bin_verzeichnis: Path, home: Path) -> dict[str, str]:
    """Baut einen echten Werkzeugpfad, der nur ccusage und rtk auslaesst."""
    bin_verzeichnis.mkdir()
    for name in ("python3", "dirname", "uname", "id", "mkdir", "cp", "chmod", "cmp", "sed"):
        quelle = shutil.which(name)
        if quelle is None:
            raise unittest.SkipTest(f"{name} fehlt in der Testumgebung")
        (bin_verzeichnis / name).symlink_to(quelle)
    env = os.environ.copy()
    env["PATH"] = str(bin_verzeichnis)
    env["HOME"] = str(home)
    return env


def umgebung_mit_ccusage(bin_verzeichnis: Path) -> dict[str, str]:
    """Macht die Live-Werkzeug-Pruefung unabhaengig vom Testrechner."""
    bin_verzeichnis.mkdir()
    (bin_verzeichnis / "ccusage").symlink_to(shutil.which("true") or "/usr/bin/true")
    env = os.environ.copy()
    env["PATH"] = f"{bin_verzeichnis}{os.pathsep}{env.get('PATH', '')}"
    return env


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
                       "--force", "--dry-run", "--demo"):
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
        self.env = umgebung_mit_ccusage(Path(self._tmp.name) / "bin")

    def tearDown(self):
        self._tmp.cleanup()

    def test_legt_nichts_an(self):
        fertig = lauf("--dry-run", "--data-dir", str(self.ziel), env=self.env)
        self.assertEqual(fertig.returncode, 0, fertig.stderr)
        self.assertFalse(self.ziel.exists(), "--dry-run hat das Verzeichnis angelegt")

    def test_nennt_die_fuenf_skripte_und_das_bin_verzeichnis(self):
        fertig = lauf("--dry-run", "--data-dir", str(self.ziel), env=self.env)
        for name in ("ccusage-export.sh", "rtk-export.sh", "ccusage-check.py",
                     "ccusage-merge.py", "rtk-merge.py"):
            self.assertIn(name, fertig.stdout)
        self.assertIn("bin", fertig.stdout)

    def test_ruehrt_bestehende_config_nicht_an(self):
        """Die config.toml des Repositories darf der Lauf nicht veraendern."""
        config = BASE_DIR / "config.toml"
        vorher = config.read_bytes() if config.exists() else None
        fertig = lauf("--dry-run", "--data-dir", str(self.ziel), env=self.env)
        self.assertEqual(fertig.returncode, 0, fertig.stderr)
        nachher = config.read_bytes() if config.exists() else None
        self.assertEqual(vorher, nachher)

    def test_meldet_bestehende_config_statt_sie_zu_ueberschreiben(self):
        """Kein stiller Fallback: eine vorhandene config.toml wird genannt."""
        config = BASE_DIR / "config.toml"
        if not config.exists():
            self.skipTest("Im Arbeitsbaum liegt keine config.toml.")
        fertig = lauf("--dry-run", "--data-dir", str(self.ziel), env=self.env)
        self.assertIn("config.toml", fertig.stdout)
        self.assertRegex(fertig.stdout, r"(?i)bleibt|vorhanden|unveraendert")


class FehlendeLiveWerkzeugeTests(unittest.TestCase):
    """Ohne beide Datenlieferanten darf kein Live-Setup vorgetaeuscht werden."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.basis = Path(self._tmp.name)
        self.ziel = self.basis / "daten"
        self.env = umgebung_ohne_live_werkzeuge(self.basis / "bin", self.basis / "home")

    def tearDown(self):
        self._tmp.cleanup()

    def test_abbruch_nach_auswahl_legt_nichts_an(self):
        fertig = lauf("--data-dir", str(self.ziel), eingabe="a\n", env=self.env)

        self.assertNotEqual(fertig.returncode, 0)
        self.assertIn("mindestens eines", fertig.stdout + fertig.stderr)
        self.assertIn("Live-Daten", fertig.stdout + fertig.stderr)
        self.assertFalse(self.ziel.exists())

    def test_demo_auswahl_setzt_den_trockenlauf_fort(self):
        fertig = lauf("--dry-run", "--data-dir", str(self.ziel),
                      eingabe="d\n", env=self.env)

        self.assertEqual(fertig.returncode, 0, fertig.stderr)
        self.assertIn("Demo-Modus", fertig.stdout)
        self.assertIn("Demo-Daten", fertig.stdout)
        self.assertFalse(self.ziel.exists())

    def test_demo_option_erzeugt_beispieldaten_ohne_eingabe(self):
        fertig = lauf("--demo", "--data-dir", str(self.ziel),
                      eingabe="", env=self.env)

        self.assertEqual(fertig.returncode, 0, fertig.stderr)
        self.assertTrue(list(self.ziel.glob("????-??.json")))
        self.assertTrue(list((self.ziel / "rtk").glob("????-??.json")))

    def test_demo_modus_ueberschreibt_keine_monatsdaten(self):
        self.ziel.mkdir()
        vorhanden = self.ziel / "2026-09.json"
        vorhanden.write_text("nicht ueberschreiben", encoding="utf-8")

        fertig = lauf("--demo", "--data-dir", str(self.ziel), env=self.env)

        self.assertNotEqual(fertig.returncode, 0)
        self.assertEqual(vorhanden.read_text(encoding="utf-8"), "nicht ueberschreiben")

    def test_demo_modus_ueberschreibt_keine_rtk_daten(self):
        rtk = self.ziel / "rtk"
        rtk.mkdir(parents=True)
        vorhanden = rtk / "2026-09.json"
        vorhanden.write_text("nicht ueberschreiben", encoding="utf-8")

        fertig = lauf("--demo", "--data-dir", str(self.ziel), env=self.env)

        self.assertNotEqual(fertig.returncode, 0)
        self.assertEqual(vorhanden.read_text(encoding="utf-8"), "nicht ueberschreiben")

    def test_ende_der_eingabe_bricht_mit_hinweis_ab(self):
        fertig = lauf("--data-dir", str(self.ziel), eingabe="", env=self.env)

        self.assertNotEqual(fertig.returncode, 0)
        self.assertIn("--demo", fertig.stdout + fertig.stderr)
        self.assertFalse(self.ziel.exists())

    def test_demo_ueberspringt_launchagents_auch_ausserhalb_von_macos(self):
        uname = self.basis / "bin" / "uname"
        uname.unlink()
        uname.write_text("#!/bin/sh\nprintf 'Linux\\n'\n", encoding="utf-8")
        uname.chmod(0o755)

        fertig = lauf("--demo", "--with-launchagents", "--dry-run",
                      "--data-dir", str(self.ziel), eingabe="", env=self.env)

        self.assertEqual(fertig.returncode, 0, fertig.stderr)
        self.assertIn("launchd-Jobs werden im Demo-Modus uebersprungen", fertig.stdout)


class LaunchAgentsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ziel = Path(self._tmp.name) / "daten"
        self.env = umgebung_mit_ccusage(Path(self._tmp.name) / "bin")

    def tearDown(self):
        self._tmp.cleanup()

    @unittest.skipUnless(IST_MACOS, "launchd gibt es nur auf macOS.")
    def test_trockenlauf_setzt_die_platzhalter_ein(self):
        fertig = lauf("--with-launchagents", "--dry-run",
                      "--data-dir", str(self.ziel),
                      "--label-prefix", "com.testfall", env=self.env)
        self.assertEqual(fertig.returncode, 0, fertig.stderr)
        for job in ("ccusage-daily", "ccusage-weekly", "ccusage-monthly", "rtk-daily"):
            self.assertIn(f"com.testfall.{job}", fertig.stdout)
        self.assertNotIn("__SCRIPT_DIR__", fertig.stdout)
        self.assertNotIn("__DATA_DIR__", fertig.stdout)
        self.assertNotIn("__LABEL_PREFIX__", fertig.stdout)

    @unittest.skipIf(IST_MACOS, "Der Abbruch greift nur ausserhalb von macOS.")
    def test_bricht_ausserhalb_von_macos_ab(self):
        fertig = lauf("--with-launchagents", "--dry-run", "--data-dir", str(self.ziel),
                      env=self.env)
        self.assertEqual(fertig.returncode, 2)
        self.assertIn("macOS", fertig.stdout + fertig.stderr)

    def test_label_praefix_ohne_launchagents_ist_ein_fehler(self):
        """Sonst glaubt der Aufrufer, er haette die Jobs eingerichtet."""
        fertig = lauf("--dry-run", "--label-prefix", "com.testfall",
                      "--data-dir", str(self.ziel), env=self.env)
        self.assertNotEqual(fertig.returncode, 0)
        self.assertIn("--with-launchagents", fertig.stdout + fertig.stderr)


if __name__ == "__main__":
    unittest.main()

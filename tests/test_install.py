"""Tests for install.py, the installer for macOS, Linux and Windows.

Real scheduler changes cannot be made in a test run without consequences.
The subprocess tests therefore stay away from jobs or use --dry-run; the
in-process tests replace install.run_command, the single gate to launchctl,
systemctl, crontab and schtasks, and check the files that would be loaded.
"""

from __future__ import annotations

import importlib.util
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from tests.helpers import BASE_DIR, make_stub, minimal_path

SCRIPT = BASE_DIR / "install.py"
IS_MACOS = sys.platform == "darwin"

RTK_OK = ("import sys\n"
          "print('rtk 0.51.0' if sys.argv[1:] == ['--version'] else '{\"summary\": {}}')\n")
RTK_NO_JSON = "print('rtk: Rust Type Kit')\n"
CCUSAGE_STUB = "import sys\nprint('20.0.16' if sys.argv[1:] == ['--version'] else '')\n"
NODE_STUB = "print('v22.14.0')\n"


def bare_env(home: Path) -> dict[str, str]:
    """No ccusage, no rtk, nothing from the host's tool directories."""
    env = {"PATH": minimal_path(), "HOME": str(home), "USERPROFILE": str(home),
           "LOCALAPPDATA": str(home / "AppData" / "Local"),
           "XDG_DATA_HOME": str(home / ".local" / "share"),
           "XDG_CONFIG_HOME": str(home / ".config"),
           "CCUSAGE_SEARCH_DIRS": "", "RTK_SEARCH_DIRS": ""}
    if os.name == "nt":
        env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
    return env


def run(*args, env, stdin=""):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=str(BASE_DIR),
                          capture_output=True, text=True, input=stdin, env=env)


class TempHome(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.data = self.home / "data"
        self.env = bare_env(self.home)

    def with_ccusage(self, body=CCUSAGE_STUB):
        # The node stub sits beside ccusage, where the export job finds it.
        make_stub(self.home / "tools", "node", NODE_STUB)
        self.env["CCUSAGE_BIN"] = str(make_stub(self.home / "tools", "ccusage", body))

    def with_rtk(self, body=RTK_OK):
        self.env["RTK_BIN"] = str(make_stub(self.home / "tools", "rtk", body))


class OptionTests(TempHome):
    def test_launchers_exist(self):
        self.assertTrue(os.access(BASE_DIR / "install.sh", os.X_OK) or os.name == "nt")
        self.assertIn(b"install.py", (BASE_DIR / "install.sh").read_bytes())
        self.assertIn(b"install.py", (BASE_DIR / "install.cmd").read_bytes())
        self.assertIn(b"\r\n", (BASE_DIR / "install.cmd").read_bytes())

    @unittest.skipIf(os.name == "nt", "POSIX shell starter")
    def test_shell_starter_passes_arguments_on(self):
        result = subprocess.run(["/bin/sh", str(BASE_DIR / "install.sh"), "--help"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--with-jobs", result.stdout)

    def test_help_names_the_options(self):
        result = run("--help", env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ("--with-jobs", "--with-launchagents", "--no-jobs", "--remove-jobs",
                       "--scheduler", "--label-prefix", "--data-dir", "--force",
                       "--dry-run", "--demo"):
            self.assertIn(option, result.stdout)

    def test_unknown_option_aborts(self):
        result = run("--gibtesnicht", env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--gibtesnicht", result.stderr)

    def test_option_without_value_aborts(self):
        self.assertNotEqual(run("--data-dir", env=self.env).returncode, 0)

    def test_label_prefix_without_jobs_is_an_error(self):
        # Otherwise the caller believes the jobs were set up.
        self.with_ccusage()
        result = run("--dry-run", "--label-prefix", "com.testfall",
                     "--data-dir", str(self.data), env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--with-jobs", result.stderr)

    def test_app_dir_only_for_a_release(self):
        result = run("--app-dir", str(self.home / "app"), "--dry-run", env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Release", result.stderr)


class DryRunTests(TempHome):
    """--dry-run may announce, but must not create anything."""

    def setUp(self):
        super().setUp()
        self.with_ccusage()

    def test_creates_nothing(self):
        result = run("--dry-run", "--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.data.exists())

    def test_names_the_export_scripts_and_bin(self):
        result = run("--dry-run", "--data-dir", str(self.data), env=self.env)
        for name in ("ccusage-export.py", "rtk-export.py", "exportlib.py", "ccusage-check.py",
                     "ccusage-merge.py", "rtk-merge.py", "export-status.py"):
            self.assertIn(name, result.stdout)
        self.assertIn("bin", result.stdout)
        self.assertIn("status", result.stdout)

    def test_leaves_the_repository_config_alone(self):
        config = BASE_DIR / "config.toml"
        before = config.read_bytes() if config.exists() else None
        result = run("--dry-run", "--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, config.read_bytes() if config.exists() else None)

    def test_reports_an_existing_config_instead_of_overwriting_it(self):
        if not (BASE_DIR / "config.toml").exists():
            self.skipTest("Im Arbeitsbaum liegt keine config.toml.")
        result = run("--dry-run", "--data-dir", str(self.data), env=self.env)
        self.assertIn("config.toml", result.stdout)
        self.assertIn("bleibt unveraendert", result.stdout)

    @unittest.skipUnless(IS_MACOS, "launchd only exists on macOS")
    def test_jobs_are_announced_with_pinned_paths(self):
        self.with_rtk()
        result = run("--with-jobs", "--dry-run", "--data-dir", str(self.data),
                     "--label-prefix", "com.testfall", env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        for job in ("ccusage-daily", "ccusage-weekly", "ccusage-monthly", "rtk-daily"):
            self.assertIn(f"com.testfall.{job}", result.stdout)
        self.assertIn("--ccusage-bin", result.stdout)
        self.assertIn("--rtk-bin", result.stdout)

    def test_foreign_scheduler_aborts(self):
        foreign = "launchd" if not IS_MACOS else "schtasks"
        result = run("--with-jobs", "--scheduler", foreign, "--dry-run",
                     "--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 2)


class InstallTests(TempHome):
    def setUp(self):
        super().setUp()
        self.with_ccusage()

    def test_normal_install_creates_directories_and_copies(self):
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.data / "status").is_dir())
        self.assertTrue((self.data / "bin" / "ccusage-export.py").is_file())
        self.assertTrue((self.data / "bin" / "exportlib.py").is_file())

    def test_differing_script_stays_without_force(self):
        run("--data-dir", str(self.data), env=self.env)
        copy = self.data / "bin" / "ccusage-check.py"
        copy.write_text("# local edit\n", encoding="utf-8")
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertIn("weicht von der Quelle ab", result.stdout)
        self.assertEqual(copy.read_text(encoding="utf-8"), "# local edit\n")
        run("--data-dir", str(self.data), "--force", env=self.env)
        self.assertNotEqual(copy.read_text(encoding="utf-8"), "# local edit\n")

    def test_obsolete_shell_scripts_are_named(self):
        (self.data / "bin").mkdir(parents=True)
        (self.data / "bin" / "ccusage-export.sh").write_text("", encoding="utf-8")
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertIn("Veraltete Exportskripte", result.stdout)
        self.assertTrue((self.data / "bin" / "ccusage-export.sh").exists())

    def test_first_export_fills_the_data_directory(self):
        from tests.test_export_ccusage import STUB
        # The version probe must not reach the export stub's call log.
        probe = "import sys\nif sys.argv[1:] == ['--version']:\n    print('20.0.16')\n    sys.exit(0)\n"
        make_stub(self.home / "good", "node", NODE_STUB)
        self.env["CCUSAGE_BIN"] = str(make_stub(self.home / "good", "ccusage", probe + STUB))
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Erster Export", result.stdout)
        self.assertTrue(list(self.data.glob("????-??.json")))
        self.assertTrue(list((self.data / "sessions").glob("*.json")))

    def test_failed_first_export_is_a_note_not_an_abort(self):
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Erster Export ccusage daily fehlgeschlagen", result.stdout)

    def test_first_export_can_be_skipped(self):
        result = run("--data-dir", str(self.data), "--no-first-export", env=self.env)
        self.assertNotIn("Erster Export", result.stdout)
        self.assertFalse((self.data / "status" / "daily.last.json").exists())

    def test_copied_export_script_runs_from_bin(self):
        run("--data-dir", str(self.data), env=self.env)
        result = subprocess.run([sys.executable, str(self.data / "bin" / "ccusage-export.py"),
                                 "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class MissingLiveToolsTests(TempHome):
    """Without both data suppliers no live setup may be pretended."""

    def test_abort_after_choice_creates_nothing(self):
        result = run("--data-dir", str(self.data), stdin="a\n", env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mindestens eines", result.stdout + result.stderr)
        self.assertIn("Live-Daten", result.stdout + result.stderr)
        self.assertFalse(self.data.exists())

    def test_demo_choice_continues_the_dry_run(self):
        result = run("--dry-run", "--data-dir", str(self.data), stdin="d\n", env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Demo-Modus", result.stdout)
        self.assertIn("Demo-Daten", result.stdout)
        self.assertFalse(self.data.exists())

    def test_demo_option_creates_sample_data_without_input(self):
        result = run("--demo", "--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(list(self.data.glob("????-??.json")))
        self.assertTrue(list((self.data / "rtk").glob("????-??.json")))

    def test_demo_creates_no_status_directory(self):
        # a missing status/ is what makes the dashboard report status_missing
        result = run("--demo", "--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.data / "status").exists())

    def test_demo_does_not_overwrite_monthly_data(self):
        self.data.mkdir()
        existing = self.data / "2026-09.json"
        existing.write_text("nicht ueberschreiben", encoding="utf-8")
        result = run("--demo", "--data-dir", str(self.data), env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(existing.read_text(encoding="utf-8"), "nicht ueberschreiben")

    def test_demo_does_not_overwrite_rtk_data(self):
        (self.data / "rtk").mkdir(parents=True)
        existing = self.data / "rtk" / "2026-09.json"
        existing.write_text("nicht ueberschreiben", encoding="utf-8")
        result = run("--demo", "--data-dir", str(self.data), env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(existing.read_text(encoding="utf-8"), "nicht ueberschreiben")

    def test_end_of_input_aborts_with_a_hint(self):
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--demo", result.stdout + result.stderr)
        self.assertFalse(self.data.exists())

    def test_demo_skips_jobs(self):
        result = run("--demo", "--with-jobs", "--dry-run", "--data-dir", str(self.data),
                     env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("im Demo-Modus uebersprungen", result.stdout)

    def test_missing_ccusage_names_the_install_command(self):
        result = run("--demo", "--dry-run", "--data-dir", str(self.data), env=self.env)
        self.assertIn("npm install -g ccusage", result.stdout)


class RtkTests(TempHome):
    """rtk/ and the rtk job exist only when a working rtk was found."""

    def setUp(self):
        super().setUp()
        self.with_ccusage()

    def test_without_rtk_no_rtk_directory_and_a_note(self):
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.data / "rtk").exists())
        self.assertTrue((self.data / "status").is_dir())
        self.assertIn("rtk-daily", result.stdout)
        self.assertIn("nicht eingerichtet", result.stdout)

    def test_dry_run_without_rtk_does_not_announce_rtk(self):
        result = run("--dry-run", "--data-dir", str(self.data), env=self.env)
        self.assertNotIn(f"anlegen: {self.data / 'rtk'}", result.stdout)
        self.assertIn(f"anlegen: {self.data / 'logs'}", result.stdout)

    def test_rtk_without_json_counts_as_missing(self):
        self.with_rtk(RTK_NO_JSON)
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.data / "rtk").exists())
        self.assertIn("kein JSON", result.stdout)

    def test_working_rtk_creates_rtk_directory(self):
        self.with_rtk()
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.data / "rtk").is_dir())

    def test_rtk_in_a_fixed_directory_is_found(self):
        stub = make_stub(self.home / "fixed", "rtk", RTK_OK)
        self.env["RTK_SEARCH_DIRS"] = str(stub.parent)
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.data / "rtk").is_dir())

    def test_rtk_on_the_shell_path_is_found_and_pinned(self):
        # The job gets the found path as --rtk-bin, so the scheduler's own
        # PATH no longer matters.
        stub = make_stub(self.home / "shellbin", "rtk", RTK_OK)
        self.env["PATH"] = str(stub.parent) + os.pathsep + self.env["PATH"]
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.data / "rtk").is_dir())

    def test_empty_rtk_directory_gets_a_cleanup_note(self):
        (self.data / "rtk").mkdir(parents=True)
        result = run("--data-dir", str(self.data), env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.data / "rtk").is_dir(), "nothing may be deleted")
        self.assertIn("von Hand", result.stdout)


def load_installer():
    spec = importlib.util.spec_from_file_location("installer_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses look the module up by name while the class is created.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SchedulerTests(TempHome):
    """The scheduler files, with every scheduler command recorded instead of run."""

    def setUp(self):
        super().setUp()
        self.with_ccusage()
        self.with_rtk()
        self.installer = load_installer()
        self.commands: list[tuple[list[str], str | None]] = []
        self.crontab = ""
        self.crontab_broken = False

        def fake(cmd, input_text=None):
            self.commands.append((cmd, input_text))
            if cmd[:2] == ["crontab", "-l"]:
                if self.crontab_broken:
                    return subprocess.CompletedProcess(cmd, 1, "", "permission denied")
                if not self.crontab:
                    return subprocess.CompletedProcess(cmd, 1, "", "crontab: no crontab for u")
                return subprocess.CompletedProcess(cmd, 0, self.crontab, "")
            if cmd[:2] == ["crontab", "-"]:
                self.crontab = input_text
            if cmd[:2] == ["launchctl", "list"]:
                return subprocess.CompletedProcess(cmd, 1, "", "")
            if cmd[-2:] == ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"]:
                return subprocess.run(cmd, capture_output=True, text=True)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        patcher = mock.patch.object(self.installer, "run_command", side_effect=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict(os.environ, self.env)
        env.start()
        self.addCleanup(env.stop)

    def main(self, *args) -> tuple[int, str]:
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = self.installer.main([*args, "--data-dir", str(self.data)])
        return code, buffer.getvalue()

    def called(self, *prefix) -> list[list[str]]:
        return [cmd for cmd, _ in self.commands if cmd[:len(prefix)] == list(prefix)]

    @unittest.skipUnless(IS_MACOS, "launchd only exists on macOS")
    def test_launchd_writes_and_loads_four_agents(self):
        code, output = self.main("--with-jobs", "--label-prefix", "com.testfall")
        self.assertEqual(code, 0, output)
        agents = self.home / "Library" / "LaunchAgents"
        weekly = plistlib.loads((agents / "com.testfall.ccusage-weekly.plist").read_bytes())
        self.assertEqual(weekly["Label"], "com.testfall.ccusage-weekly")
        self.assertEqual(weekly["StartCalendarInterval"], {"Hour": 4, "Minute": 30, "Weekday": 0})
        args = weekly["ProgramArguments"]
        self.assertEqual(args[1:3], [str(self.data / "bin" / "ccusage-export.py"), "weekly"])
        self.assertEqual(args[args.index("--ccusage-bin") + 1], os.environ["CCUSAGE_BIN"])
        rtk = plistlib.loads((agents / "com.testfall.rtk-daily.plist").read_bytes())
        self.assertIn("--rtk-bin", rtk["ProgramArguments"])
        monthly = plistlib.loads((agents / "com.testfall.ccusage-monthly.plist").read_bytes())
        self.assertEqual(monthly["StartCalendarInterval"], {"Hour": 5, "Minute": 0, "Day": 1})
        self.assertEqual(len(self.called("launchctl", "load")), 4)

    @unittest.skipUnless(IS_MACOS, "launchd only exists on macOS")
    def test_launchd_remove_jobs_unloads_and_deletes(self):
        self.main("--with-jobs", "--label-prefix", "com.testfall")
        code, _ = self.main("--remove-jobs", "--label-prefix", "com.testfall")
        self.assertEqual(code, 0)
        self.assertEqual(list((self.home / "Library" / "LaunchAgents").glob("*.plist")), [])
        self.assertEqual(len(self.called("launchctl", "unload")), 4)
        self.assertTrue((self.data / "bin").is_dir(), "data stays")

    def test_systemd_writes_persistent_timers_and_enables_them(self):
        code, output = self.main("--with-jobs", "--scheduler", "systemd")
        self.assertEqual(code, 0, output)
        units = self.home / ".config" / "systemd" / "user"
        timer = (units / "token-usage-dashboard-ccusage-weekly.timer").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=Sun *-*-* 04:30:00", timer)
        self.assertIn("Persistent=true", timer)
        monthly = (units / "token-usage-dashboard-ccusage-monthly.timer").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-01 05:00:00", monthly)
        service = (units / "token-usage-dashboard-ccusage-daily.service").read_text(encoding="utf-8")
        self.assertIn('"daily" "--data-dir"', service)
        self.assertIn("Type=oneshot", service)
        self.assertTrue(self.called("systemctl", "--user", "daemon-reload"))
        enable = self.called("systemctl", "--user", "enable", "--now")
        self.assertEqual(len(enable), 1)
        self.assertEqual(len(enable[0]) - 4, 4, "four timers in one call")

    def test_systemd_working_directory_is_not_quoted(self):
        # systemd takes WorkingDirectory verbatim; a quote makes it relative.
        self.data = self.home / "my data"
        self.main("--with-jobs", "--scheduler", "systemd")
        service = (self.home / ".config" / "systemd" / "user"
                   / "token-usage-dashboard-ccusage-daily.service").read_text(encoding="utf-8")
        self.assertIn(f"WorkingDirectory={self.data}\n", service)
        self.assertIn(f"StandardOutput=append:{self.data}/logs/", service)

    def test_systemd_prefix_with_a_dot_keeps_four_units(self):
        self.main("--with-jobs", "--scheduler", "systemd", "--label-prefix", "com.example")
        timers = sorted(p.name for p in (self.home / ".config" / "systemd" / "user").glob("*.timer"))
        self.assertEqual(timers, ["com.example-ccusage-daily.timer", "com.example-ccusage-monthly.timer",
                                  "com.example-ccusage-weekly.timer", "com.example-rtk-daily.timer"])

    def test_unreadable_crontab_is_never_replaced(self):
        self.crontab_broken = True
        code, _ = self.main("--with-jobs", "--scheduler", "cron")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.called("crontab", "-"), [])

    def test_remove_without_our_block_leaves_crontab_alone(self):
        self.crontab = "15 * * * * /usr/bin/true\n"
        self.main("--remove-jobs", "--scheduler", "cron")
        self.assertEqual(self.called("crontab", "-"), [])

    def test_systemd_quoting_escapes_specifiers(self):
        quote = self.installer._systemd_quote
        self.assertEqual(quote('/a b/%h/$X/"q"\\'), '"/a b/%%h/$$X/\\"q\\"\\\\"')

    def test_cron_block_is_idempotent_and_keeps_foreign_lines(self):
        self.crontab = "MAILTO=\"\"\n15 * * * * /usr/bin/true\n"
        self.main("--with-jobs", "--scheduler", "cron")
        self.main("--with-jobs", "--scheduler", "cron")
        lines = self.crontab.splitlines()
        self.assertEqual(lines[:2], ['MAILTO=""', "15 * * * * /usr/bin/true"])
        self.assertEqual(sum("Token-Usage-Dashboard" in line and ">>>" in line for line in lines), 1)
        jobs = [line for line in lines if "export.py" in line]
        self.assertEqual(len(jobs), 4)
        weekly = next(line for line in jobs if " weekly " in line)
        self.assertTrue(weekly.startswith("30 4 * * 0 "))
        monthly = next(line for line in jobs if " monthly " in line)
        self.assertTrue(monthly.startswith("0 5 1 * * "))
        self.main("--remove-jobs", "--scheduler", "cron")
        self.assertEqual(self.crontab, 'MAILTO=""\n15 * * * * /usr/bin/true\n')

    def test_cron_escapes_percent(self):
        self.data = self.home / "da%ta"
        self.main("--with-jobs", "--scheduler", "cron")
        self.assertIn("da\\%ta", self.crontab)
        self.assertNotRegex(self.crontab.replace("\\%", ""), "%")

    def test_schtasks_xml(self):
        ctx = self.installer.Context(Path(r"C:\Daten"), [r"C:\Py\pythonw.exe"],
                                     r"C:\npm\ccusage.cmd", None, "Token-Usage-Dashboard",
                                     False, self.installer.Output())
        scheduler = self.installer.Schtasks(ctx)
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        for name, expected in (("ccusage-daily", "ScheduleByDay"),
                               ("ccusage-weekly", "ScheduleByWeek"),
                               ("ccusage-monthly", "ScheduleByMonth")):
            job = self.installer._job(name)
            text = scheduler.render(job)
            root = ET.fromstring(text.split("\n", 1)[1])
            trigger = root.find("t:Triggers/t:CalendarTrigger", ns)
            self.assertIsNotNone(trigger.find(f"t:{expected}", ns), name)
            self.assertEqual(root.find("t:Settings/t:StartWhenAvailable", ns).text, "true")
            self.assertEqual(root.find("t:Actions/t:Exec/t:Command", ns).text, r"C:\Py\pythonw.exe")
            arguments = root.find("t:Actions/t:Exec/t:Arguments", ns).text
            self.assertIn("--ccusage-bin", arguments)
        self.assertEqual(scheduler.ident(self.installer._job("rtk-daily")),
                         r"\Token-Usage-Dashboard\rtk-daily")
        weekly = ET.fromstring(scheduler.render(self.installer._job("ccusage-weekly")).split("\n", 1)[1])
        self.assertIsNotNone(weekly.find("t:Triggers/t:CalendarTrigger/t:ScheduleByWeek/"
                                         "t:DaysOfWeek/t:Sunday", ns))

    def test_without_rtk_no_rtk_job(self):
        os.environ.pop("RTK_BIN")
        code, output = self.main("--with-jobs", "--scheduler", "cron")
        self.assertEqual(code, 0, output)
        self.assertNotIn("rtk-export.py", self.crontab)
        self.assertIn("ccusage-export.py", self.crontab)


class VersionTableTests(TempHome):
    def install(self, *args):
        return run("--data-dir", str(self.data), *args, env=self.env)

    def assertAborted(self, result):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(result.stderr.startswith("Fehler: "), result.stderr)
        self.assertEqual(result.stderr.count("Installation abgebrochen"), 1)
        self.assertIn("Komponente", result.stdout)
        self.assertFalse(self.data.exists())

    def test_all_fit(self):
        self.with_ccusage()
        self.with_rtk()
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Komponente", result.stdout)
        self.assertNotIn("zu alt", result.stdout)
        self.assertNotIn("fehlt", result.stdout)

    def test_old_ccusage_aborts_after_table(self):
        self.with_ccusage("print('19.0.3')\n")
        self.with_rtk()
        result = self.install()
        self.assertAborted(result)
        passes_not, passes = result.stderr.split("  Passt:")
        self.assertIn("ccusage", passes_not)
        self.assertIn("Python", passes)

    def test_node_missing_aborts(self):
        self.with_ccusage()
        (self.home / "tools" / "node").unlink()
        empty = self.home / "empty"
        empty.mkdir()
        self.env["PATH"] = str(empty)
        result = self.install()
        self.assertAborted(result)
        self.assertIn("Node.js", result.stderr)

    def test_unreadable_ccusage_aborts(self):
        self.with_ccusage("pass\n")
        self.assertAborted(self.install())

    def test_old_rtk_aborts(self):
        self.with_ccusage()
        self.with_rtk("import sys\nprint('rtk 0.6.0' if sys.argv[1:] == ['--version'] "
                      "else '{\"summary\": {}}')\n")
        self.assertAborted(self.install())

    def test_missing_rtk_does_not_block(self):
        self.with_ccusage()
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"rtk\s+nein\s+0\.7\.1\s+-\s+fehlt")

    def test_missing_ccusage_does_not_block(self):
        self.with_rtk()
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout, r"ccusage\s.*fehlt")
        self.assertRegex(result.stdout, r"Node\.js\s.*nicht noetig")

    def test_demo_skips_old_ccusage(self):
        self.with_ccusage("print('19.0.3')\n")
        result = self.install("--demo")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dry_run_aborts_too(self):
        self.with_ccusage("print('19.0.3')\n")
        self.assertAborted(self.install("--dry-run"))


class VersionCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inst = load_installer()

    def rows(self, versions, *, ccusage="/c/bin/ccusage", rtk="/r/rtk", demo=False,
             platform="linux", rtk_ok=True, node="/c/bin/node"):
        """Evaluate with every process start replaced; versions maps command stem to output."""
        calls = []

        def fake_read(cmd, env):
            calls.append((cmd, env))
            return versions.get(os.path.basename(cmd[0]).split(".")[0])

        env = {"PATH": "/usr/local/bin"}
        with mock.patch.object(self.inst, "read_version", side_effect=fake_read), \
                mock.patch.object(self.inst, "probe_rtk", return_value=rtk_ok), \
                mock.patch.object(self.inst.shutil, "which", return_value=node):
            rows = self.inst.evaluate(ccusage, rtk, env, demo, platform=platform,
                                      python=(3, 13, 1), mac="15.3")
        self.calls = calls
        return {row.component: row for row in rows}

    GOOD = {"node": "v22.14.0", "ccusage": "20.0.18", "rtk": "rtk 0.51.0"}

    def test_parse_version(self):
        parse = self.inst.parse_version
        self.assertEqual(parse("v22.14.0"), (22, 14, 0))
        self.assertEqual(parse("ccusage 20.0.18"), (20, 0, 18))
        self.assertEqual(parse("rtk 0.51.0"), (0, 51, 0))
        self.assertEqual(parse("0.51.1-rc.512"), (0, 51, 1))
        self.assertEqual(parse("22"), (22, 0, 0))
        self.assertIsNone(parse(""))
        self.assertIsNone(parse("no number here"))

    def test_boundaries(self):
        rows = self.rows({**self.GOOD, "ccusage": "20.0.15"})
        self.assertEqual(rows["ccusage"].result, "zu alt")
        rows = self.rows({**self.GOOD, "ccusage": "20.0.16"})
        self.assertEqual(rows["ccusage"].result, "passt")
        rows = self.rows({**self.GOOD, "node": "22.0.0"})
        self.assertEqual(rows["Node.js"].result, "passt")

    def test_no_upper_bound(self):
        rows = self.rows({**self.GOOD, "node": "v99.0.0"})
        self.assertEqual(rows["Node.js"].result, "passt")

    def test_minimum_texts(self):
        rows = self.rows(self.GOOD, platform="macos")
        self.assertEqual([rows[c].minimum for c in ("Python", "macOS", "Node.js", "ccusage", "rtk")],
                         ["3.11", "14", "22", "20.0.16", "0.7.1"])

    def blocking(self, rows):
        return [row.component for row in self.inst.blocking(list(rows.values()))]

    def test_all_pass(self):
        self.assertEqual(self.blocking(self.rows(self.GOOD, platform="macos")), [])

    def test_rtk_missing_continues(self):
        rows = self.rows(self.GOOD, rtk=None)
        self.assertEqual(rows["rtk"].result, "fehlt")
        self.assertEqual(self.blocking(rows), [])

    def test_ccusage_missing_rtk_ok_continues(self):
        rows = self.rows(self.GOOD, ccusage=None)
        self.assertEqual(rows["ccusage"].result, "fehlt")
        self.assertEqual(rows["Node.js"].result, "nicht noetig")
        self.assertEqual(self.blocking(rows), [])

    def test_rtk_too_old_blocks(self):
        rows = self.rows({**self.GOOD, "rtk": "rtk 0.7.0"})
        self.assertEqual(self.blocking(rows), ["rtk"])

    def test_ccusage_unreadable_blocks(self):
        rows = self.rows({**self.GOOD, "ccusage": None})
        self.assertEqual(rows["ccusage"].result, "nicht lesbar")
        self.assertEqual(self.blocking(rows), ["ccusage"])

    def test_no_number_is_unreadable(self):
        rows = self.rows({**self.GOOD, "ccusage": "garbage"})
        self.assertEqual(rows["ccusage"].result, "nicht lesbar")

    def test_node_missing_with_ccusage_blocks(self):
        rows = self.rows(self.GOOD, node=None)
        self.assertEqual(rows["Node.js"].result, "fehlt")
        self.assertEqual(self.blocking(rows), ["Node.js"])

    def test_demo_old_node_continues(self):
        rows = self.rows({**self.GOOD, "node": "v20.1.0", "ccusage": "19.0.0"}, demo=True)
        self.assertEqual({c: r.result for c, r in rows.items() if c != "Python"},
                         {"Node.js": "nicht noetig", "ccusage": "nicht noetig",
                          "rtk": "nicht noetig"})
        self.assertEqual(rows["Python"].result, "passt")
        self.assertEqual(self.blocking(rows), [])

    def test_other_program_rtk_continues(self):
        rows = self.rows(self.GOOD, rtk_ok=False)
        self.assertEqual(rows["rtk"].result, "anderes Programm")
        self.assertEqual(self.blocking(rows), [])

    def test_macos_row_only_on_macos(self):
        self.assertNotIn("macOS", self.rows(self.GOOD, platform="linux"))
        self.assertEqual(self.rows(self.GOOD, platform="macos")["macOS"].result, "passt")
        rows = self.rows(self.GOOD, platform="macos", ccusage=None)
        self.assertEqual(rows["macOS"].result, "nicht noetig")

    def test_node_beside_ccusage_wins(self):
        with mock.patch.object(self.inst.shutil, "which") as which:
            which.side_effect = lambda name, path=None: (
                "/c/bin/node" if path == "/c/bin" else "/usr/local/bin/node")
            with mock.patch.object(self.inst, "read_version", return_value="v22.1.0") as read, \
                    mock.patch.object(self.inst, "probe_rtk", return_value=True):
                self.inst.evaluate("/c/bin/ccusage", None, {"PATH": "/usr/local/bin"}, False,
                                   platform="linux", python=(3, 13, 1), mac=None)
        called = [c.args[0][0] for c in read.call_args_list]
        self.assertIn("/c/bin/node", called)
        self.assertNotIn("/usr/local/bin/node", called)

    def test_node_falls_back_to_given_path_not_os_environ(self):
        seen = []

        def which(name, path=None):
            seen.append(path)
            return None

        with mock.patch.object(self.inst.shutil, "which", side_effect=which), \
                mock.patch.object(self.inst, "read_version", return_value="20.0.18"):
            self.inst.evaluate("/c/bin/ccusage", None, {"PATH": "/given"}, False,
                               platform="linux", python=(3, 13, 1), mac=None)
        self.assertEqual(seen, ["/c/bin", "/given"])

    def test_ccusage_called_with_its_directory_first_in_path(self):
        self.rows(self.GOOD)
        env = next(e for cmd, e in self.calls if cmd[0] == "/c/bin/ccusage")
        self.assertEqual(env["PATH"].split(os.pathsep)[0], "/c/bin")
        self.assertIn("/usr/local/bin", env["PATH"].split(os.pathsep))

    def test_read_version_gate(self):
        def done(out="", err="", code=0):
            return subprocess.CompletedProcess([], code, out.encode(), err.encode())

        with mock.patch.object(self.inst.subprocess, "run", return_value=done("v1.2.3\n")) as run:
            self.assertEqual(self.inst.read_version(["x", "--version"], {}).strip(), "v1.2.3")
            self.assertEqual(run.call_args.kwargs["timeout"], 10)
        with mock.patch.object(self.inst.subprocess, "run", return_value=done("", "9.9\n")):
            self.assertEqual(self.inst.read_version(["x"], {}).strip(), "9.9")
        with mock.patch.object(self.inst.subprocess, "run", return_value=done("1.0", "", 1)):
            self.assertIsNone(self.inst.read_version(["x"], {}))
        for error in (OSError("no"), subprocess.TimeoutExpired("x", 10)):
            with mock.patch.object(self.inst.subprocess, "run", side_effect=error):
                self.assertIsNone(self.inst.read_version(["x"], {}))
        with mock.patch.object(self.inst.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, b"\xff\xfe", b"")):
            self.assertIsNone(self.inst.read_version(["x"], {}))

    def bad_rows(self):
        return list(self.rows({**self.GOOD, "node": "20.11.1", "ccusage": "19.0.3"},
                              platform="macos").values())

    def test_render_table_ascii_and_aligned(self):
        text = self.inst.render_table(self.bad_rows())
        text.encode("ascii")
        lines = text.splitlines()
        self.assertEqual(len(lines), 2 + 5)
        header = lines[0]
        for word in ("Pflicht", "Mindestens", "Gefunden", "Ergebnis"):
            column = header.index(word)
            for line in lines[2:]:
                self.assertEqual(line[column - 2:column], "  ")
                self.assertNotEqual(line[column], " ")
        self.assertIn("zu alt", text)
        self.assertIn("20.0.16", text)

    def test_render_failure_names_every_blocking_row(self):
        text = self.inst.render_failure(self.bad_rows())
        text.encode("ascii")
        self.assertIn("Zwei Komponenten passen nicht. Installation abgebrochen.", text)
        for needle in ("Node.js", "gefunden 20.11.1", "gebraucht ab 22",
                       "ccusage", "gefunden 19.0.3", "gebraucht ab 20.0.16",
                       "npm install -g ccusage@latest", "https://nodejs.org",
                       "Passt:", "Python 3.13.1", "macOS 15.3", "rtk 0.51.0"):
            self.assertIn(needle, text)
        self.assertLess(text.index("Passt nicht:"), text.index("Passt:"))
        self.assertFalse(text.startswith("Fehler"))


if __name__ == "__main__":
    unittest.main()

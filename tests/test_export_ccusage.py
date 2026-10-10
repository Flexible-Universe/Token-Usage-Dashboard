"""Tests for export/ccusage-export.py, run with a stub ccusage."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from tests.helpers import BASE_DIR, make_stub, minimal_path

SCRIPT = BASE_DIR / "export" / "ccusage-export.py"

# Answers depend on the arguments, because ccusage-check.py rejects an export
# without records and the script would otherwise abort before "ok". Every
# call is appended to calls.log next to the stub.
STUB = """import os, sys
from pathlib import Path
args = " ".join(sys.argv[1:])
with open(Path(__file__).with_name("calls.log"), "a", encoding="utf-8") as fh:
    fh.write(args + "\\n")
if os.environ.get("STUB_FAIL"):
    sys.exit(1)
if args.startswith("claude daily"):
    print('{"projects": {"p": [{"date": "2026-10-01", "totalCost": 1}]}}')
elif args.startswith("claude session"):
    print('{"sessions": [{"sessionId": "s1", "totalCost": 1}]}')
elif args.startswith("blocks"):
    print('{"blocks": [{"id": "b1", "totalCost": 1}]}')
elif args.startswith("daily"):
    print('{"daily": [{"date": "2026-10-01", "totalCost": 1}]}')
else:
    sys.exit(1)
"""


def scheduler_env(root: Path, **extra) -> dict:
    """The sparse environment of a scheduler, plus what the test sets."""
    env = {"PATH": minimal_path(), "HOME": str(root), "USERPROFILE": str(root),
           "CCUSAGE_SEARCH_DIRS": "", "RTK_SEARCH_DIRS": ""}
    if os.name == "nt":
        env["SystemRoot"] = os.environ.get("SystemRoot", r"C:\Windows")
    env.update(extra)
    return env


class CcusageExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.status = self.data / "status"
        self.stub = make_stub(self.root / "stubbin", "ccusage", STUB)

    def run_script(self, *args, ccusage_bin=None, **extra_env):
        env = scheduler_env(self.root, CCUSAGE_DATA_DIR=str(self.data),
                            CCUSAGE_BIN=str(ccusage_bin or self.stub), **extra_env)
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                              capture_output=True, text=True)

    def read(self, name):
        return json.loads((self.status / name).read_text(encoding="utf-8"))

    def calls(self):
        return (self.root / "stubbin" / "calls.log").read_text(encoding="utf-8").splitlines()

    def test_daily_success_writes_last_and_ok(self):
        result = self.run_script("daily")
        self.assertEqual(result.returncode, 0, result.stderr)
        last = self.read("daily.last.json")
        self.assertEqual(last, self.read("daily.ok.json"))
        self.assertEqual(last["job"], "daily")
        self.assertEqual(last["exitCode"], 0)
        self.assertTrue(last["targets"])
        for entry in last["targets"]:
            self.assertIn(entry["result"], ("ok", "frozen"))
        month = date.today().strftime("%Y-%m")
        files = [entry["file"] for entry in last["targets"]]
        # Names are relative to the data directory, never prefixed with its name.
        self.assertIn(f"{month}.json", files)
        self.assertIn(f"projects/{month}.json", files)
        self.assertTrue((self.data / f"{month}.json").is_file())
        self.assertIn("OK", (self.data / "logs" / "daily.log").read_text(encoding="utf-8"))

    def test_daily_failure_writes_only_last(self):
        result = self.run_script("daily", STUB_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.status / "daily.ok.json").exists())
        last = self.read("daily.last.json")
        self.assertEqual(last["exitCode"], result.returncode)
        self.assertTrue(last["targets"])
        for entry in last["targets"]:
            self.assertEqual(entry["result"], "failed")

    def test_weekly_records_lookback_days(self):
        result = self.run_script("weekly", CCUSAGE_LOOKBACK_DAYS="9")
        self.assertEqual(result.returncode, 0, result.stderr)
        last = self.read("weekly.last.json")
        self.assertEqual(last["lookbackDays"], 9)
        files = sorted(entry["file"] for entry in last["targets"])
        self.assertEqual(len(files), 2)
        self.assertRegex(files[0], r"^blocks/\d{4}-W\d{2}\.json$")
        self.assertRegex(files[1], r"^sessions/\d{4}-W\d{2}\.json$")
        self.assertTrue((self.status / "weekly.ok.json").exists())

    def test_options_replace_the_environment_variables(self):
        # cmd.exe and PowerShell cannot prefix a command with variables, so
        # the dashboard's remedy command uses the options.
        other = self.root / "other"
        env = scheduler_env(self.root, CCUSAGE_BIN=str(self.stub))
        result = subprocess.run([sys.executable, str(SCRIPT), "weekly",
                                 "--data-dir", str(other), "--lookback-days", "33"],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        last = json.loads((other / "status" / "weekly.last.json").read_text(encoding="utf-8"))
        self.assertEqual(last["lookbackDays"], 33)

    def test_weekly_merges_into_existing_file(self):
        self.assertEqual(self.run_script("weekly").returncode, 0)
        blocks = next((self.data / "blocks").glob("*.json"))
        payload = json.loads(blocks.read_text(encoding="utf-8"))
        payload["blocks"].append({"id": "old", "totalCost": 2})
        blocks.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.run_script("weekly").returncode, 0)
        ids = {b["id"] for b in json.loads(blocks.read_text(encoding="utf-8"))["blocks"]}
        self.assertEqual(ids, {"b1", "old"})

    def test_strict_regression_keeps_the_existing_file(self):
        month = date.today().strftime("%Y-%m")
        target = self.data / f"{month}.json"
        target.parent.mkdir(parents=True)
        bigger = {"daily": [{"date": f"{month}-0{i}", "totalCost": 5} for i in range(1, 4)]}
        target.write_text(json.dumps(bigger), encoding="utf-8")
        result = self.run_script("daily")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), bigger)
        results = {e["file"]: e["result"] for e in self.read("daily.last.json")["targets"]}
        self.assertEqual(results[f"{month}.json"], "aborted")

    def test_monthly_regression_counts_as_frozen(self):
        prev = date.today().replace(day=1) - timedelta(days=1)
        target = self.data / f"{prev:%Y-%m}.json"
        target.parent.mkdir(parents=True)
        bigger = {"daily": [{"date": f"{prev:%Y-%m}-0{i}", "totalCost": 5} for i in range(1, 4)]}
        target.write_text(json.dumps(bigger), encoding="utf-8")
        result = self.run_script("monthly")
        self.assertEqual(result.returncode, 0, result.stderr)
        results = {e["file"]: e["result"] for e in self.read("monthly.last.json")["targets"]}
        self.assertEqual(results[f"{prev:%Y-%m}.json"], "frozen")
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), bigger)

    def test_missing_ccusage_writes_last_with_empty_targets(self):
        dead = self.root / "not-there"
        result = self.run_script("daily", ccusage_bin=dead)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CCUSAGE_BIN", result.stderr)
        last = self.read("daily.last.json")
        self.assertNotEqual(last["exitCode"], 0)
        self.assertEqual(last["targets"], [])
        self.assertFalse((self.status / "daily.ok.json").exists())

    def test_ccusage_is_found_in_a_fixed_directory(self):
        # The scheduler's PATH does not reach nvm or npm; the fixed list does.
        result = self.run_script("daily", ccusage_bin=self.root / "not-there",
                                 CCUSAGE_SEARCH_DIRS=str(self.stub.parent))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_mode_writes_no_status(self):
        result = self.run_script("hourly")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.status.exists() and any(self.status.iterdir()))

    def test_no_temporary_files_are_left_behind(self):
        self.run_script("daily", STUB_FAIL="1")
        self.run_script("weekly")
        leftovers = [p for p in self.data.rglob("*")
                     if p.is_file() and not p.name.endswith((".json", ".log"))]
        self.assertEqual(leftovers, [])


def load_script():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("ccusage_export", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CcusageExportInProcessTests(unittest.TestCase):
    """Cases that need a failure no stub can produce."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.stub = make_stub(self.root / "stubbin", "ccusage", STUB)
        self.module = load_script()

    def run_main(self, *args, today=None):
        env = scheduler_env(self.root, CCUSAGE_BIN=str(self.stub))
        env["PATH"] = os.environ.get("PATH", "")
        with mock.patch.dict(os.environ, env, clear=False):
            return self.module.main([*args, "--data-dir", str(self.data)], today=today)

    def test_failed_final_replace_is_reported_as_failed(self):
        real_replace = os.replace

        def refuse_targets(src, dst):
            if str(dst).endswith(".json") and "status" not in Path(dst).parts:
                raise OSError("refused")
            return real_replace(src, dst)

        with mock.patch.object(self.module.os, "replace", side_effect=refuse_targets):
            code = self.run_main("daily")
        self.assertNotEqual(code, 0)
        status = self.data / "status"
        self.assertFalse((status / "daily.ok.json").exists())
        last = json.loads((status / "daily.last.json").read_text(encoding="utf-8"))
        self.assertNotEqual(last["exitCode"], 0)
        self.assertTrue(last["targets"])
        for entry in last["targets"]:
            self.assertEqual(entry["result"], "failed")
        month = date.today().strftime("%Y-%m")
        self.assertFalse((self.data / f"{month}.json").exists())

    def test_first_days_of_a_month_also_export_the_previous_month(self):
        code = self.run_main("daily", today=date(2026, 3, 2))
        self.assertEqual(code, 0)
        calls = (self.root / "stubbin" / "calls.log").read_text(encoding="utf-8")
        self.assertIn("daily --json --by-agent -s 2026-03-01", calls)
        self.assertIn("daily --json --by-agent -s 2026-02-01 -u 2026-02-28", calls)
        self.assertIn("claude daily --json -i -s 20260201 -u 20260228", calls)

    def test_later_days_export_only_the_current_month(self):
        self.run_main("daily", today=date(2026, 3, 4))
        calls = (self.root / "stubbin" / "calls.log").read_text(encoding="utf-8")
        self.assertNotIn("2026-02", calls)

    def test_weekly_names_the_iso_week_and_reaches_back(self):
        # 2027-01-01 belongs to ISO week 2026-W53.
        self.run_main("weekly", "--lookback-days", "14", today=date(2027, 1, 1))
        self.assertTrue((self.data / "blocks" / "2026-W53.json").is_file())
        calls = (self.root / "stubbin" / "calls.log").read_text(encoding="utf-8")
        self.assertIn("blocks --json -s 20261218", calls)

    def test_monthly_freezes_the_previous_month_across_a_year(self):
        self.run_main("monthly", today=date(2027, 1, 1))
        calls = (self.root / "stubbin" / "calls.log").read_text(encoding="utf-8")
        self.assertIn("daily --json --by-agent -s 2026-12-01 -u 2026-12-31", calls)


if __name__ == "__main__":
    unittest.main()

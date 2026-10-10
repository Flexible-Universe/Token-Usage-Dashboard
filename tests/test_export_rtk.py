"""Tests for export/rtk-export.py and the status files it writes."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers import BASE_DIR, make_stub
from tests.test_export_ccusage import scheduler_env

SCRIPT = BASE_DIR / "export" / "rtk-export.py"

GOOD_STUB = """import sys
if sys.argv[1:] == ["gain", "--all", "--format", "json"]:
    print('{"daily": [{"date": "2026-10-01", "saved_tokens": 5}]}')
else:
    print('{"summary": {}}')
"""
NO_JSON_STUB = "print('rtk: Rust Type Kit')\n"
NO_DAILY_STUB = "print('{\"summary\": {}}')\n"


class RtkExportStatusTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / "data"

    def run_script(self, rtk_bin: Path, *args, **extra):
        env = scheduler_env(self.root, RTK_DATA_DIR=str(self.data),
                            RTK_BIN=str(rtk_bin), **extra)
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env,
                              capture_output=True, text=True)

    def stub(self, body: str) -> Path:
        return make_stub(self.root / "stubbin", "rtk", body)

    def status(self, name: str) -> dict:
        return json.loads((self.data / "status" / name).read_text(encoding="utf-8"))

    def test_good_run_writes_last_and_ok(self):
        result = self.run_script(self.stub(GOOD_STUB))
        self.assertEqual(result.returncode, 0, result.stderr)
        last = self.status("rtk.last.json")
        self.assertEqual(last, self.status("rtk.ok.json"))
        self.assertEqual(last["job"], "rtk")
        self.assertEqual(last["exitCode"], 0)
        self.assertEqual(last["targets"], [{"file": "rtk/", "result": "ok"}])
        self.assertNotIn("lookbackDays", last)

    def test_no_json_writes_only_last_with_failed_target(self):
        result = self.run_script(self.stub(NO_JSON_STUB))
        self.assertNotEqual(result.returncode, 0)
        last = self.status("rtk.last.json")
        self.assertEqual(last["exitCode"], result.returncode)
        self.assertEqual(last["targets"], [{"file": "rtk/", "result": "failed"}])
        self.assertFalse((self.data / "status" / "rtk.ok.json").exists())

    def test_missing_rtk_writes_last_with_empty_targets(self):
        result = self.run_script(self.root / "not-there")
        self.assertNotEqual(result.returncode, 0)
        last = self.status("rtk.last.json")
        self.assertNotEqual(last["exitCode"], 0)
        self.assertEqual(last["targets"], [])
        self.assertFalse((self.data / "status" / "rtk.ok.json").exists())
        # a host without rtk must not start to expect rtk data
        self.assertFalse((self.data / "rtk").exists())

    def test_failed_probe_does_not_create_rtk_directory(self):
        self.run_script(self.stub(NO_JSON_STUB))
        self.assertFalse((self.data / "rtk").exists())

    def test_output_without_daily_is_rejected_and_leaves_nothing(self):
        result = self.run_script(self.stub(NO_DAILY_STUB))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list((self.data / "rtk").iterdir()), [])

    def test_good_run_creates_rtk_directory(self):
        self.run_script(self.stub(GOOD_STUB))
        self.assertTrue(list((self.data / "rtk").glob("????-??.json")))
        self.assertEqual([p.name for p in (self.data / "rtk").iterdir()], ["2026-10.json"])

    def test_rtk_is_found_in_a_fixed_directory(self):
        stub = self.stub(GOOD_STUB)
        result = self.run_script(self.root / "not-there", RTK_SEARCH_DIRS=str(stub.parent))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_data_dir_option(self):
        other = self.root / "other"
        result = self.run_script(self.stub(GOOD_STUB), "--data-dir", str(other))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((other / "status" / "rtk.ok.json").is_file())


if __name__ == "__main__":
    unittest.main()

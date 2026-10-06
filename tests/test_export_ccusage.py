"""Tests for export/ccusage-export.sh status files, run with a stub ccusage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from tests.helpers import BASE_DIR

SCRIPT = BASE_DIR / "export" / "ccusage-export.sh"

# Answers depend on the arguments, because ccusage-check.py rejects an export
# without records and the script would otherwise abort before "ok".
STUB = """#!/bin/bash
[[ -n "${STUB_FAIL:-}" ]] && exit 1
case "$*" in
    "claude daily"*) echo '{"projects": {"p": [{"date": "2026-10-01", "totalCost": 1}]}}' ;;
    "claude session"*) echo '{"sessions": [{"sessionId": "s1", "totalCost": 1}]}' ;;
    blocks*) echo '{"blocks": [{"id": "b1", "totalCost": 1}]}' ;;
    daily*) echo '{"daily": [{"date": "2026-10-01", "totalCost": 1}]}' ;;
    *) exit 1 ;;
esac
"""


@unittest.skipUnless(sys.platform == "darwin", "export script uses BSD date")
class CcusageExportStatusTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.status = self.data / "status"
        self.stub = self.root / "ccusage-stub"
        self.stub.write_text(STUB)
        self.stub.chmod(0o755)

    def run_script(self, *args, ccusage_bin=None, **extra_env):
        env = {
            "CCUSAGE_DATA_DIR": str(self.data),
            "HOME": str(self.root),
            "PATH": "/usr/bin:/bin",
            "CCUSAGE_BIN": str(ccusage_bin or self.stub),
            **extra_env,
        }
        return subprocess.run(["/bin/bash", str(SCRIPT), *args], env=env,
                              capture_output=True, text=True)

    def read(self, name):
        return json.loads((self.status / name).read_text())

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

    def test_missing_ccusage_writes_last_with_empty_targets(self):
        for fixed in ("/opt/homebrew/bin/ccusage", "/usr/local/bin/ccusage"):
            if os.path.exists(fixed):
                self.skipTest(f"{fixed} exists and is always found by find_ccusage")
        dead = self.root / "not-executable"
        dead.write_text("")
        dead.chmod(0o644)
        result = self.run_script("daily", ccusage_bin=dead)
        self.assertNotEqual(result.returncode, 0)
        last = self.read("daily.last.json")
        self.assertNotEqual(last["exitCode"], 0)
        self.assertEqual(last["targets"], [])
        self.assertFalse((self.status / "daily.ok.json").exists())

    def test_failed_final_move_is_reported_as_failed(self):
        # The script prepends the ccusage directory to PATH, so a mv placed
        # next to the stub shadows the real one and refuses to write targets.
        bindir = self.root / "bin"
        bindir.mkdir()
        stub = bindir / "ccusage"
        stub.write_text(STUB)
        stub.chmod(0o755)
        shim = bindir / "mv"
        shim.write_text('#!/bin/bash\n'
                        'for last; do :; done\n'
                        '[[ "$last" == *.json ]] && exit 1\n'
                        'exec /bin/mv "$@"\n')
        shim.chmod(0o755)
        result = self.run_script("daily", ccusage_bin=stub)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.status / "daily.ok.json").exists())
        last = self.read("daily.last.json")
        self.assertNotEqual(last["exitCode"], 0)
        self.assertTrue(last["targets"])
        for entry in last["targets"]:
            self.assertEqual(entry["result"], "failed")
        month = date.today().strftime("%Y-%m")
        self.assertFalse((self.data / f"{month}.json").exists())

    def test_invalid_mode_writes_no_status(self):
        result = self.run_script("hourly")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.status.exists() and any(self.status.iterdir()))


if __name__ == "__main__":
    unittest.main()

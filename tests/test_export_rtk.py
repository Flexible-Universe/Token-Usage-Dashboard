"""Tests for the status files written by export/rtk-export.sh."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers import BASE_DIR

SCRIPT = BASE_DIR / "export" / "rtk-export.sh"

GOOD_STUB = """#!/bin/bash
if [[ "$*" == "gain --all --format json" ]]; then
    echo '{"daily": [{"date": "2026-10-01", "saved_tokens": 5}]}'
else
    echo '{"summary": {}}'
fi
"""
NO_JSON_STUB = "#!/bin/bash\necho 'rtk: Rust Type Kit'\n"


@unittest.skipUnless(sys.platform == "darwin", "export scripts target macOS")
class RtkExportStatusTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / "data"

    def run_script(self, rtk_bin: Path):
        env = {
            "RTK_DATA_DIR": str(self.data),
            "HOME": str(self.root),
            "PATH": "/usr/bin:/bin",
            "RTK_BIN": str(rtk_bin),
            # No fixed search directories, so a real rtk on the host stays invisible.
            "RTK_SEARCH_DIRS": "",
        }
        return subprocess.run(["/bin/bash", str(SCRIPT)], env=env,
                              capture_output=True, text=True)

    def stub(self, body: str, mode: int = 0o755) -> Path:
        path = self.root / "rtk-stub"
        path.write_text(body, encoding="utf-8")
        path.chmod(mode)
        return path

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
        result = self.run_script(self.stub("", mode=0o644))
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

    def test_good_run_creates_rtk_directory(self):
        self.run_script(self.stub(GOOD_STUB))
        self.assertTrue(list((self.data / "rtk").glob("????-??.json")))


if __name__ == "__main__":
    unittest.main()

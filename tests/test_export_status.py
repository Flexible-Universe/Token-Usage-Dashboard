"""Tests for export/export-status.py, run as a subprocess like the shell scripts do."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import BASE_DIR

SCRIPT = BASE_DIR / "export" / "export-status.py"
START = "2026-10-05T02:30:00Z"
END = "2026-10-05T02:30:41Z"


def run(status_dir, *extra, job="daily", started=START, finished=END, exit_code="0"):
    args = [sys.executable, str(SCRIPT), "--dir", str(status_dir), "--job", job,
            "--started", started, "--finished", finished, "--exit-code", exit_code]
    return subprocess.run([*args, *extra], capture_output=True, text=True)


class ExportStatusTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "status"

    def names(self):
        return sorted(p.name for p in self.dir.iterdir()) if self.dir.exists() else []

    def read(self, name):
        return json.loads((self.dir / name).read_text(encoding="utf-8"))

    def test_success_writes_last_and_identical_ok(self):
        done = run(self.dir, "--target", "blocks/a.json=ok", "--target", "sessions/b.json=frozen")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.names(), ["daily.last.json", "daily.ok.json"])
        self.assertEqual((self.dir / "daily.last.json").read_bytes(),
                         (self.dir / "daily.ok.json").read_bytes())
        self.assertEqual(self.read("daily.last.json"), {
            "schema": 1, "job": "daily", "startedAt": START, "finishedAt": END,
            "exitCode": 0,
            "targets": [{"file": "blocks/a.json", "result": "ok"},
                        {"file": "sessions/b.json", "result": "frozen"}]})

    def test_failure_leaves_existing_ok_untouched(self):
        self.assertEqual(run(self.dir).returncode, 0)
        old = (self.dir / "daily.ok.json").read_bytes()
        done = run(self.dir, "--target", "x.json=failed", exit_code="3",
                   finished="2026-10-06T02:30:41Z")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.dir / "daily.ok.json").read_bytes(), old)
        last = self.read("daily.last.json")
        self.assertEqual(last["exitCode"], 3)
        self.assertEqual(last["targets"], [{"file": "x.json", "result": "failed"}])

    def test_failure_without_ok_writes_only_last(self):
        self.assertEqual(run(self.dir, exit_code="1").returncode, 0)
        self.assertEqual(self.names(), ["daily.last.json"])

    def test_empty_targets_is_empty_list(self):
        run(self.dir)
        self.assertEqual(self.read("daily.last.json")["targets"], [])

    def test_weekly_requires_lookback_days(self):
        done = run(self.dir, job="weekly")
        self.assertEqual(done.returncode, 2)
        self.assertTrue(done.stderr)
        self.assertEqual(self.names(), [])

    def test_weekly_with_lookback_days(self):
        self.assertEqual(run(self.dir, "--lookback-days", "14", job="weekly").returncode, 0)
        self.assertEqual(self.read("weekly.ok.json")["lookbackDays"], 14)

    def test_lookback_days_forbidden_for_other_jobs(self):
        for job in ("daily", "monthly", "rtk"):
            with self.subTest(job=job):
                done = run(self.dir, "--lookback-days", "14", job=job)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(self.names(), [])

    def test_daily_has_no_lookback_field(self):
        run(self.dir)
        self.assertNotIn("lookbackDays", self.read("daily.last.json"))

    def test_invalid_input_exits_2_and_writes_nothing(self):
        cases = {
            "job": dict(job="yearly"),
            "started": dict(started="2026-10-05 02:30:00"),
            "started offset": dict(started="2026-10-05T02:30:00+00:00"),
            "finished impossible date": dict(finished="2026-13-45T02:30:00Z"),
            "exit code": dict(exit_code="abc"),
            "lookback zero": dict(job="weekly", extra=("--lookback-days", "0")),
            "lookback text": dict(job="weekly", extra=("--lookback-days", "x")),
            "bad result": dict(extra=("--target", "a.json=done")),
            "no separator": dict(extra=("--target", "a.json")),
            "empty file": dict(extra=("--target", "=ok")),
        }
        for label, case in cases.items():
            with self.subTest(label):
                extra = case.pop("extra", ())
                done = run(self.dir, *extra, **case)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertTrue(done.stderr)
                self.assertEqual(self.names(), [])

    def test_missing_required_argument_exits_2(self):
        done = subprocess.run([sys.executable, str(SCRIPT), "--dir", str(self.dir),
                               "--job", "daily"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertFalse(self.dir.exists())

    def test_target_splits_at_last_equals_sign(self):
        run(self.dir, "--target", "a=b.json=ok")
        self.assertEqual(self.read("daily.last.json")["targets"],
                         [{"file": "a=b.json", "result": "ok"}])

    def test_error_leaves_existing_directory_unchanged(self):
        run(self.dir)
        before = {n: (self.dir / n).read_bytes() for n in self.names()}
        self.assertEqual(run(self.dir, "--target", "a=bogus").returncode, 2)
        self.assertEqual({n: (self.dir / n).read_bytes() for n in self.names()}, before)

    def test_no_temp_files_remain(self):
        run(self.dir)
        run(self.dir, exit_code="1")
        self.assertTrue(all(n.endswith((".last.json", ".ok.json")) for n in self.names()))

    def test_no_temp_file_after_write_failure(self):
        # A directory in place of the target makes os.replace fail after the temp file exists.
        self.dir.mkdir()
        (self.dir / "daily.last.json").mkdir()
        done = run(self.dir)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.names(), ["daily.last.json"])


if __name__ == "__main__":
    unittest.main()

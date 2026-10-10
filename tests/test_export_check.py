"""Tests for sources.load_status and sources.check_export_status."""

from __future__ import annotations

import json
import os
import shutil
import time
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.helpers import BASE_DIR  # noqa: F401 - sets sys.path

import sources

# 12:00 UTC keeps the UTC and the local calendar day equal on common
# test machines, which the monthly rule depends on.
NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)
STAMP = "%Y-%m-%dT%H:%M:%SZ"
BERLIN_SUMMER = timezone(timedelta(hours=2))


def pin_timezone(test: unittest.TestCase, name: str = "Europe/Berlin") -> None:
    """Fixes the process time zone, which the local-date rules depend on."""
    previous = os.environ.get("TZ")

    def restore():
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()

    os.environ["TZ"] = name
    time.tzset()
    test.addCleanup(restore)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(STAMP)


def record(job, finished, exit_code=0, lookback=None, targets=None):
    """A valid status record whose run finished at ``finished``."""
    data = {
        "schema": 1, "job": job,
        "startedAt": stamp(finished - timedelta(seconds=30)),
        "finishedAt": stamp(finished),
        "exitCode": exit_code,
        "targets": [] if targets is None else targets,
    }
    if lookback is not None:
        data["lookbackDays"] = lookback
    return data


def ok_record(job, finished, lookback=None):
    if job == "weekly" and lookback is None:
        lookback = 14
    return record(job, finished, 0, lookback)


def write(directory: Path, name: str, data) -> None:
    target = directory / "status"
    target.mkdir(exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data)
    (target / name).write_text(text, encoding="utf-8")


def write_ok(directory: Path, job: str, finished: datetime, lookback=None) -> None:
    data = ok_record(job, finished, lookback)
    write(directory, f"{job}.ok.json", data)
    write(directory, f"{job}.last.json", data)


def evaluate(directory: Path, now=NOW, rtk_present=None):
    status = sources.load_status(directory)
    if rtk_present is not None:
        status["rtkPresent"] = rtk_present
    return sources.check_export_status(status, now)


def codes(issues):
    return [(i["code"], i["key"]) for i in issues]


class LoadStatusTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def reject(self, name, data, rule, **params):
        # Subtests share one directory; start each from an empty status/.
        shutil.rmtree(self.dir / "status", ignore_errors=True)
        write(self.dir, name, data)
        status = sources.load_status(self.dir)
        self.assertEqual(len(status["errors"]), 1, status["errors"])
        error = status["errors"][0]
        self.assertEqual(error["code"], "source.status.bad_file." + rule)
        self.assertIn(error["code"], sources.MESSAGE_CODES)
        self.assertEqual(error["file"], name)
        # Raw values only: the backend ships no sentence of its own.
        self.assertEqual(error["params"], {"file": name, **params})
        job, kind = name.split(".")[:2]
        self.assertIsNone(status["jobs"][job][kind])

    def test_missing_directory_is_no_error(self):
        status = sources.load_status(self.dir)
        self.assertFalse(status["present"])
        self.assertFalse(status["rtkPresent"])
        self.assertEqual(status["errors"], [])
        for job in ("daily", "weekly", "monthly", "rtk"):
            self.assertEqual(status["jobs"][job], {"last": None, "ok": None})

    def test_rtk_present_follows_rtk_directory(self):
        (self.dir / "rtk").mkdir()
        self.assertTrue(sources.load_status(self.dir)["rtkPresent"])

    def test_valid_files_are_read(self):
        finished = NOW - timedelta(hours=2)
        write_ok(self.dir, "weekly", finished, lookback=20)
        write(self.dir, "daily.last.json", record(
            "daily", finished, 1,
            targets=[{"file": "2026-10.json", "result": "failed"}]))
        status = sources.load_status(self.dir)
        self.assertTrue(status["present"])
        self.assertEqual(status["errors"], [])
        weekly = status["jobs"]["weekly"]
        self.assertEqual(weekly["ok"]["finishedAt"], stamp(finished))
        self.assertEqual(weekly["ok"]["lookbackDays"], 20)
        self.assertIsNotNone(weekly["last"])
        daily = status["jobs"]["daily"]
        self.assertIsNone(daily["ok"])
        self.assertEqual(daily["last"]["exitCode"], 1)
        self.assertEqual(daily["last"]["targets"],
                         [{"file": "2026-10.json", "result": "failed"}])

    def test_unrelated_files_are_ignored(self):
        write(self.dir, "notes.json", "not json")
        write(self.dir, "daily.tmp.json", "not json")
        status = sources.load_status(self.dir)
        self.assertEqual(status["errors"], [])

    def test_invalid_json(self):
        self.reject("daily.ok.json", "{not json", "not_json")

    def test_invalid_utf8_is_not_json(self):
        shutil.rmtree(self.dir / "status", ignore_errors=True)
        (self.dir / "status").mkdir()
        (self.dir / "status" / "daily.ok.json").write_bytes(b"\xff\xfe{")
        status = sources.load_status(self.dir)
        self.assertEqual([e["code"] for e in status["errors"]],
                         ["source.status.bad_file.not_json"])

    def test_top_level_must_be_an_object(self):
        self.reject("daily.ok.json", [1, 2], "not_object")

    def test_schema_must_be_one(self):
        data = ok_record("daily", NOW)
        data["schema"] = 2
        self.reject("daily.ok.json", data, "schema")

    def test_job_must_match_file_name(self):
        self.reject("daily.ok.json", ok_record("rtk", NOW), "job_mismatch",
                    job="daily")

    def test_timestamp_form(self):
        data = ok_record("daily", NOW)
        data["finishedAt"] = "2026-10-15 12:00:00"
        self.reject("daily.ok.json", data, "timestamp", field="finishedAt")

    def test_timestamp_without_z_is_rejected(self):
        data = ok_record("daily", NOW)
        data["startedAt"] = "2026-10-15T12:00:00+00:00"
        self.reject("daily.ok.json", data, "timestamp", field="startedAt")

    def test_exit_code_must_be_integer(self):
        for bad in ("0", 1.5, None, True):
            with self.subTest(bad=bad):
                data = ok_record("daily", NOW)
                data["exitCode"] = bad
                self.reject("daily.ok.json", data, "exit_code")

    def test_targets_must_be_a_list(self):
        data = ok_record("daily", NOW)
        data["targets"] = {"file": "a", "result": "ok"}
        self.reject("daily.ok.json", data, "targets")

    def test_target_needs_valid_result(self):
        # Unhashable values must be rejected, not crash the set lookup.
        for bad in ("weird", [], {}, None, 1):
            with self.subTest(bad=bad):
                data = ok_record("daily", NOW)
                data["targets"] = [{"file": "a.json", "result": bad}]
                self.reject("daily.ok.json", data, "target_entry")

    def test_target_needs_file(self):
        data = ok_record("daily", NOW)
        data["targets"] = [{"result": "ok"}]
        self.reject("daily.ok.json", data, "target_entry")

    def test_weekly_requires_lookback_days(self):
        data = ok_record("weekly", NOW)
        del data["lookbackDays"]
        self.reject("weekly.ok.json", data, "lookback")

    def test_weekly_lookback_days_must_be_positive_integer(self):
        for bad in (0, -3, 7.5, "14", True):
            with self.subTest(bad=bad):
                data = ok_record("weekly", NOW)
                data["lookbackDays"] = bad
                self.reject("weekly.ok.json", data, "lookback")

    def test_other_jobs_must_not_carry_lookback_days(self):
        for job in ("daily", "monthly", "rtk"):
            with self.subTest(job=job):
                data = ok_record(job, NOW)
                data["lookbackDays"] = 14
                self.reject(f"{job}.last.json", data, "lookback_not_allowed",
                            job=job)

    def test_rejected_file_does_not_hide_the_other(self):
        write(self.dir, "daily.last.json", record("daily", NOW))
        write(self.dir, "daily.ok.json", "{")
        status = sources.load_status(self.dir)
        self.assertEqual(len(status["errors"]), 1)
        self.assertIsNotNone(status["jobs"]["daily"]["last"])
        self.assertIsNone(status["jobs"]["daily"]["ok"])

    def test_load_extras_carries_status_errors(self):
        write(self.dir, "daily.ok.json", "{")
        extras = sources.load_extras(self.dir)
        self.assertIn("jobs", extras["status"])
        errors = [e for e in extras["errors"] if e["source"] == "status"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["code"], "source.status.bad_file.not_json")


class StatusMissingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_only_status_missing_and_three_unknown_jobs(self):
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues), [("check.export.status_missing", "status")])
        self.assertEqual(issues[0]["level"], "info")
        self.assertEqual(issues[0]["scope"], "export")
        self.assertEqual(issues[0]["params"], {})
        self.assertEqual([e["job"] for e in exports],
                         ["daily", "weekly", "monthly"])
        for entry in exports:
            self.assertEqual(entry, {
                "job": entry["job"], "lastSuccess": None, "lastAttempt": None,
                "lastExitCode": None, "state": "unknown", "cause": None,
                "ageHours": None})

    def test_four_jobs_with_rtk_directory(self):
        (self.dir / "rtk").mkdir()
        issues, exports = evaluate(self.dir)
        self.assertEqual(len(issues), 1)
        self.assertEqual([e["job"] for e in exports],
                         ["daily", "weekly", "monthly", "rtk"])
        self.assertTrue(all(e["state"] == "unknown" for e in exports))


class NeverLoggedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_one_missing_job_is_reported_alone(self):
        fresh = NOW - timedelta(hours=1)
        write_ok(self.dir, "daily", fresh)
        write_ok(self.dir, "weekly", fresh)
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues), [("check.export.never_logged", "monthly")])
        self.assertEqual(issues[0]["level"], "info")
        self.assertEqual(issues[0]["params"], {"job": "monthly"})
        states = {e["job"]: e["state"] for e in exports}
        self.assertEqual(states, {"daily": "ok", "weekly": "ok",
                                  "monthly": "unknown"})

    def test_rtk_never_logged_only_with_rtk_directory(self):
        fresh = NOW - timedelta(hours=1)
        for job in ("daily", "weekly", "monthly"):
            write_ok(self.dir, job, fresh)
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(issues, [])
        self.assertEqual([e["job"] for e in exports],
                         ["daily", "weekly", "monthly"])
        issues, exports = evaluate(self.dir, rtk_present=True)
        self.assertEqual(codes(issues), [("check.export.never_logged", "rtk")])
        self.assertEqual(exports[-1]["job"], "rtk")
        self.assertEqual(exports[-1]["state"], "unknown")


class ThresholdTests(unittest.TestCase):
    def setUp(self):
        pin_timezone(self)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.fresh = NOW - timedelta(hours=1)

    def seed(self, **overrides):
        """All jobs fresh, except those given as ``job=finished``."""
        for job in ("daily", "weekly", "monthly", "rtk"):
            write_ok(self.dir, job, overrides.get(job, self.fresh))

    def run_eval(self):
        (self.dir / "rtk").mkdir(exist_ok=True)
        return evaluate(self.dir)

    def entry(self, exports, job):
        return next(e for e in exports if e["job"] == job)

    def test_daily_and_rtk_exactly_36_hours_is_fine(self):
        for job in ("daily", "rtk"):
            with self.subTest(job=job):
                self.seed(**{job: NOW - timedelta(hours=36)})
                issues, exports = self.run_eval()
                self.assertEqual(issues, [])
                self.assertEqual(self.entry(exports, job)["state"], "ok")

    def test_daily_and_rtk_just_over_36_hours_warns(self):
        for job in ("daily", "rtk"):
            with self.subTest(job=job):
                last = NOW - timedelta(hours=36, seconds=1)
                self.seed(**{job: last})
                issues, exports = self.run_eval()
                self.assertEqual(codes(issues), [("check.export.overdue", job)])
                self.assertEqual(issues[0]["level"], "warn")
                self.assertEqual(issues[0]["scope"], "export")
                params = issues[0]["params"]
                self.assertEqual(params["job"], job)
                self.assertEqual(params["lastSuccess"], stamp(last))
                self.assertAlmostEqual(params["ageHours"], 36.0, places=1)
                self.assertEqual(self.entry(exports, job)["state"], "warn")

    def test_just_under_36_hours_is_fine(self):
        self.seed(daily=NOW - timedelta(hours=35, minutes=59))
        issues, _ = self.run_eval()
        self.assertEqual(issues, [])

    def test_weekly_exactly_eight_days_is_fine(self):
        self.seed(weekly=NOW - timedelta(days=8))
        issues, exports = self.run_eval()
        self.assertEqual(issues, [])
        self.assertEqual(self.entry(exports, "weekly")["state"], "ok")

    def test_weekly_over_eight_days_warns_only(self):
        last = NOW - timedelta(days=8, seconds=1)
        self.seed(weekly=last)
        issues, exports = self.run_eval()
        self.assertEqual(codes(issues), [("check.export.overdue", "weekly")])
        self.assertEqual(issues[0]["level"], "warn")
        self.assertEqual(self.entry(exports, "weekly")["state"], "warn")

    def test_weekly_exactly_lookback_days_still_warns_only(self):
        self.seed(weekly=NOW - timedelta(days=14))
        issues, _ = self.run_eval()
        self.assertEqual(codes(issues), [("check.export.overdue", "weekly")])

    def test_weekly_gap_risk_starts_at_local_midnight(self):
        # ccusage-export.py exports from the local date "today - lookback",
        # so a run on 2026-10-04 still covers a success on 2026-09-20.
        success = datetime(2026, 9, 20, 4, 31, tzinfo=BERLIN_SUMMER)
        for job in ("daily", "monthly"):
            write_ok(self.dir, job, success + timedelta(days=14))
        write_ok(self.dir, "weekly", success)
        before = datetime(2026, 10, 4, 23, 59, 59, tzinfo=BERLIN_SUMMER)
        issues, _ = evaluate(self.dir, now=before, rtk_present=False)
        self.assertEqual(codes(issues), [("check.export.overdue", "weekly")])
        midnight = datetime(2026, 10, 5, 0, 0, 0, tzinfo=BERLIN_SUMMER)
        issues, _ = evaluate(self.dir, now=midnight, rtk_present=False)
        self.assertEqual(codes(issues), [("check.export.gap_risk", "weekly")])
        # Elapsed time is only 14 days and some hours; the suggestion must
        # still reach back to the success date.
        self.assertGreaterEqual(issues[0]["params"]["suggestedLookback"], 15)

    def test_weekly_fourteen_days_by_hours_is_no_gap_on_the_same_date(self):
        # NOW is 14:00 local; 14 days and a second earlier is still the
        # local date 14 days back, which the next run covers.
        self.seed(weekly=NOW - timedelta(days=14, seconds=1))
        issues, _ = self.run_eval()
        self.assertEqual(codes(issues), [("check.export.overdue", "weekly")])

    def test_weekly_over_lookback_is_gap_risk_and_replaces_overdue(self):
        # 23:59:59 local on 2026-09-30, 15 local dates before NOW.
        last = datetime(2026, 9, 30, 23, 59, 59, tzinfo=BERLIN_SUMMER)
        self.seed(weekly=last)
        issues, exports = self.run_eval()
        self.assertEqual(codes(issues), [("check.export.gap_risk", "weekly")])
        issue = issues[0]
        self.assertEqual(issue["level"], "error")
        self.assertEqual(issue["scope"], "export")
        self.assertEqual(issue["params"]["job"], "weekly")
        self.assertEqual(issue["params"]["lastSuccess"], stamp(last))
        self.assertEqual(issue["params"]["lookbackDays"], 14)
        self.assertAlmostEqual(issue["params"]["ageDays"], 14.6, places=1)
        self.assertEqual(issue["params"]["suggestedLookback"], 16)
        self.assertEqual(self.entry(exports, "weekly")["state"], "error")

    def test_suggested_lookback_is_ceil_plus_one(self):
        # 16 days exactly -> 17; 16 days and a second -> 18
        for delta, expected in ((timedelta(days=16), 17),
                                (timedelta(days=16, seconds=1), 18),
                                (timedelta(days=15, hours=23), 17)):
            with self.subTest(delta=delta):
                self.seed(weekly=NOW - delta)
                issues, _ = self.run_eval()
                self.assertEqual(issues[0]["params"]["suggestedLookback"],
                                 expected)

    def test_lookback_days_from_status_file_moves_the_error_threshold(self):
        write_ok(self.dir, "daily", self.fresh)
        write_ok(self.dir, "monthly", self.fresh)
        write_ok(self.dir, "weekly",
                 datetime(2026, 9, 25, 0, 0, 0, tzinfo=BERLIN_SUMMER),
                 lookback=20)
        issues, _ = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues), [("check.export.overdue", "weekly")])
        write_ok(self.dir, "weekly",
                 datetime(2026, 9, 24, 23, 59, 59, tzinfo=BERLIN_SUMMER),
                 lookback=20)
        issues, _ = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues), [("check.export.gap_risk", "weekly")])
        self.assertEqual(issues[0]["params"]["lookbackDays"], 20)
        self.assertEqual(issues[0]["params"]["suggestedLookback"], 22)

    def test_monthly_on_the_first_is_fine_without_success(self):
        now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        for job in ("daily", "weekly"):
            write_ok(self.dir, job, now - timedelta(hours=1))
        write_ok(self.dir, "monthly", datetime(2026, 9, 1, 5, 0,
                                               tzinfo=timezone.utc))
        issues, exports = evaluate(self.dir, now=now, rtk_present=False)
        self.assertEqual(issues, [])
        self.assertEqual(self.entry(exports, "monthly")["state"], "ok")

    def test_monthly_on_the_second_without_success_this_month_warns(self):
        now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
        for job in ("daily", "weekly"):
            write_ok(self.dir, job, now - timedelta(hours=1))
        last = datetime(2026, 9, 1, 5, 0, tzinfo=timezone.utc)
        write_ok(self.dir, "monthly", last)
        issues, exports = evaluate(self.dir, now=now, rtk_present=False)
        self.assertEqual(codes(issues), [("check.export.overdue", "monthly")])
        self.assertEqual(issues[0]["level"], "warn")
        self.assertEqual(issues[0]["params"]["lastSuccess"], stamp(last))
        self.assertEqual(self.entry(exports, "monthly")["state"], "warn")

    def test_monthly_on_the_second_with_success_on_the_first_is_fine(self):
        now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
        for job in ("daily", "weekly"):
            write_ok(self.dir, job, now - timedelta(hours=1))
        write_ok(self.dir, "monthly", datetime(2026, 10, 1, 12, 0,
                                               tzinfo=timezone.utc))
        issues, _ = evaluate(self.dir, now=now, rtk_present=False)
        self.assertEqual(issues, [])

    def test_monthly_never_reaches_error(self):
        now = datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc)
        for job in ("daily", "weekly"):
            write_ok(self.dir, job, now - timedelta(hours=1))
        write_ok(self.dir, "monthly", datetime(2026, 6, 1, 5, 0,
                                               tzinfo=timezone.utc))
        issues, _ = evaluate(self.dir, now=now, rtk_present=False)
        self.assertEqual([i["level"] for i in issues], ["warn"])


class LastAttemptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.fresh = NOW - timedelta(hours=1)
        for job in ("weekly", "monthly"):
            write_ok(self.dir, job, self.fresh)

    def test_failed_attempt_newer_than_success_warns_with_files(self):
        success = NOW - timedelta(hours=20)
        attempt = NOW - timedelta(hours=2)
        write(self.dir, "daily.ok.json", ok_record("daily", success))
        write(self.dir, "daily.last.json", record(
            "daily", attempt, 1, targets=[
                {"file": "2026-10.json", "result": "failed"},
                {"file": "projects/2026-10.json", "result": "ok"},
                {"file": "blocks/x.json", "result": "aborted"},
                {"file": "y.json", "result": "frozen"}]))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues), [("check.export.last_failed", "daily")])
        issue = issues[0]
        self.assertEqual(issue["level"], "warn")
        self.assertEqual(issue["params"], {
            "job": "daily", "lastAttempt": stamp(attempt), "exitCode": 1,
            "files": ["2026-10.json", "blocks/x.json"]})
        entry = exports[0]
        self.assertEqual(entry["state"], "warn")
        self.assertEqual(entry["lastSuccess"], stamp(success))
        self.assertEqual(entry["lastAttempt"], stamp(attempt))
        self.assertEqual(entry["lastExitCode"], 1)
        self.assertAlmostEqual(entry["ageHours"], 20.0, places=1)

    def test_old_failure_before_a_success_is_ignored(self):
        write(self.dir, "daily.ok.json", ok_record("daily", self.fresh))
        write(self.dir, "daily.last.json", record(
            "daily", self.fresh - timedelta(hours=5), 1))
        issues, _ = evaluate(self.dir, rtk_present=False)
        self.assertEqual(issues, [])

    def test_last_without_ok_warns_and_has_no_age(self):
        attempt = NOW - timedelta(hours=3)
        write(self.dir, "daily.last.json", record("daily", attempt, 2))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues),
                         [("check.export.last_failed_no_targets", "daily")])
        self.assertEqual(issues[0]["params"], {
            "job": "daily", "lastAttempt": stamp(attempt), "exitCode": 2})
        self.assertEqual(exports[0]["cause"], "never_succeeded")
        entry = exports[0]
        self.assertEqual(entry["state"], "warn")
        self.assertIsNone(entry["lastSuccess"])
        self.assertIsNone(entry["ageHours"])
        self.assertEqual(entry["lastAttempt"], stamp(attempt))
        self.assertEqual(entry["lastExitCode"], 2)

    def test_failed_run_after_all_targets_names_no_target(self):
        attempt = NOW - timedelta(hours=2)
        write(self.dir, "daily.ok.json",
              ok_record("daily", NOW - timedelta(hours=20)))
        write(self.dir, "daily.last.json", record(
            "daily", attempt, 1, targets=[
                {"file": "2026-10.json", "result": "ok"},
                {"file": "2026-09.json", "result": "frozen"}]))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues),
                         [("check.export.last_failed_after_targets", "daily")])
        self.assertEqual(issues[0]["level"], "warn")
        self.assertEqual(issues[0]["params"], {
            "job": "daily", "lastAttempt": stamp(attempt), "exitCode": 1})
        self.assertEqual(exports[0]["cause"], "last_failed")

    def test_run_aborted_before_any_target_without_ok(self):
        write(self.dir, "daily.last.json",
              record("daily", NOW - timedelta(hours=2), 1, targets=[]))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues),
                         [("check.export.last_failed_no_targets", "daily")])
        self.assertEqual(exports[0]["cause"], "never_succeeded")

    def test_successful_last_without_ok_is_success_unrecorded(self):
        attempt = NOW - timedelta(hours=3)
        write(self.dir, "daily.last.json", record(
            "daily", attempt, 0,
            targets=[{"file": "2026-10.json", "result": "ok"}]))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues),
                         [("check.export.success_unrecorded", "daily")])
        self.assertEqual(issues[0]["level"], "warn")
        self.assertEqual(issues[0]["params"],
                         {"job": "daily", "lastAttempt": stamp(attempt)})
        entry = exports[0]
        self.assertEqual(entry["state"], "warn")
        self.assertEqual(entry["cause"], "success_unrecorded")
        self.assertIsNone(entry["lastSuccess"])
        self.assertIsNone(entry["ageHours"])
        self.assertEqual(entry["lastExitCode"], 0)

    def test_successful_last_newer_than_ok_is_success_unrecorded(self):
        write(self.dir, "daily.ok.json",
              ok_record("daily", NOW - timedelta(hours=40)))
        write(self.dir, "daily.last.json",
              record("daily", NOW - timedelta(hours=2), 0))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues),
                         [("check.export.overdue", "daily"),
                          ("check.export.success_unrecorded", "daily")])
        self.assertEqual(exports[0]["cause"], "success_unrecorded")
        self.assertAlmostEqual(exports[0]["ageHours"], 40.0, places=1)

    def test_rejected_ok_with_successful_last_is_success_unrecorded(self):
        write(self.dir, "daily.ok.json", "{")
        write(self.dir, "daily.last.json",
              record("daily", NOW - timedelta(hours=2), 0))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues),
                         [("check.export.success_unrecorded", "daily")])
        self.assertNotEqual(exports[0]["cause"], "never_succeeded")

    def test_last_failed_comes_in_addition_to_overdue(self):
        write(self.dir, "daily.ok.json",
              ok_record("daily", NOW - timedelta(hours=40)))
        write(self.dir, "daily.last.json",
              record("daily", NOW - timedelta(hours=2), 1))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues),
                         [("check.export.overdue", "daily"),
                          ("check.export.last_failed_no_targets", "daily")])
        self.assertEqual(exports[0]["state"], "warn")

    def test_error_state_wins_over_last_failed_warning(self):
        write(self.dir, "weekly.ok.json",
              ok_record("weekly", NOW - timedelta(days=20)))
        write(self.dir, "weekly.last.json",
              record("weekly", NOW - timedelta(days=1), 1, lookback=14))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual([c for c, key in codes(issues) if key == "weekly"],
                         ["check.export.gap_risk",
                          "check.export.last_failed_no_targets"])
        weekly = next(e for e in exports if e["job"] == "weekly")
        self.assertEqual(weekly["state"], "error")


class FutureTimestampTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_future_finish_warns_and_skips_age_rules(self):
        for job in ("weekly", "monthly"):
            write_ok(self.dir, job, NOW - timedelta(hours=1))
        future = NOW + timedelta(days=2)
        write_ok(self.dir, "daily", future)
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(codes(issues),
                         [("check.export.future_timestamp", "daily")])
        self.assertEqual(issues[0]["level"], "warn")
        self.assertEqual(issues[0]["params"],
                         {"job": "daily", "timestamp": stamp(future)})
        self.assertEqual(exports[0]["state"], "warn")

    def test_future_last_keeps_the_age_rules_on_a_past_ok(self):
        for job in ("daily", "monthly"):
            write_ok(self.dir, job, NOW - timedelta(hours=1))
        write(self.dir, "weekly.ok.json",
              ok_record("weekly", NOW - timedelta(days=20)))
        future = NOW + timedelta(hours=3)
        write(self.dir, "weekly.last.json",
              record("weekly", future, 0, lookback=14))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(sorted(c for c, _ in codes(issues)),
                         ["check.export.future_timestamp",
                          "check.export.gap_risk",
                          "check.export.success_unrecorded"])
        future_issue = next(i for i in issues
                            if i["code"] == "check.export.future_timestamp")
        self.assertEqual(future_issue["params"]["timestamp"], stamp(future))
        weekly = next(e for e in exports if e["job"] == "weekly")
        self.assertEqual(weekly["state"], "error")
        self.assertEqual(weekly["cause"], "gap_risk")

    def test_future_last_with_old_daily_ok_still_warns_overdue(self):
        for job in ("weekly", "monthly"):
            write_ok(self.dir, job, NOW - timedelta(hours=1))
        write(self.dir, "daily.ok.json",
              ok_record("daily", NOW - timedelta(hours=40)))
        write(self.dir, "daily.last.json",
              record("daily", NOW + timedelta(hours=1), 0))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(sorted(c for c, _ in codes(issues)),
                         ["check.export.future_timestamp",
                          "check.export.overdue",
                          "check.export.success_unrecorded"])
        self.assertEqual(exports[0]["cause"], "success_unrecorded")

    def test_both_in_future_yield_one_issue_with_the_latest_stamp(self):
        for job in ("weekly", "monthly"):
            write_ok(self.dir, job, NOW - timedelta(hours=1))
        write(self.dir, "daily.ok.json",
              ok_record("daily", NOW + timedelta(hours=1)))
        later = NOW + timedelta(hours=5)
        write(self.dir, "daily.last.json", record("daily", later, 1))
        issues, _ = evaluate(self.dir, rtk_present=False)
        future = [i for i in issues
                  if i["code"] == "check.export.future_timestamp"]
        self.assertEqual(len(future), 1)
        self.assertEqual(future[0]["params"]["timestamp"], stamp(later))

    def test_timestamp_equal_to_now_is_not_future(self):
        for job in ("daily", "weekly", "monthly"):
            write_ok(self.dir, job, NOW)
        issues, _ = evaluate(self.dir, rtk_present=False)
        self.assertEqual(issues, [])


class RtkPresenceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_stale_rtk_status_is_not_evaluated_without_rtk_directory(self):
        for job in ("daily", "weekly", "monthly"):
            write_ok(self.dir, job, NOW - timedelta(hours=1))
        write_ok(self.dir, "rtk", NOW - timedelta(days=10))
        issues, exports = evaluate(self.dir, rtk_present=False)
        self.assertEqual(issues, [])
        self.assertNotIn("rtk", [e["job"] for e in exports])

    def test_rtk_job_with_directory_is_evaluated(self):
        for job in ("daily", "weekly", "monthly"):
            write_ok(self.dir, job, NOW - timedelta(hours=1))
        write_ok(self.dir, "rtk", NOW - timedelta(days=10))
        issues, exports = evaluate(self.dir, rtk_present=True)
        self.assertEqual(codes(issues), [("check.export.overdue", "rtk")])
        self.assertEqual([e["job"] for e in exports],
                         ["daily", "weekly", "monthly", "rtk"])


class CauseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        for job in ("daily", "weekly", "monthly"):
            write_ok(self.dir, job, NOW - timedelta(hours=1))

    def cause(self, job):
        _, exports = evaluate(self.dir, rtk_present=False)
        return next(e for e in exports if e["job"] == job)["cause"]

    def test_ok_and_unknown_carry_no_cause(self):
        self.assertIsNone(self.cause("daily"))
        (self.dir / "status" / "daily.ok.json").unlink()
        (self.dir / "status" / "daily.last.json").unlink()
        self.assertIsNone(self.cause("daily"))

    def test_overdue(self):
        write_ok(self.dir, "daily", NOW - timedelta(hours=40))
        self.assertEqual(self.cause("daily"), "overdue")

    def test_future_timestamp(self):
        write_ok(self.dir, "daily", NOW + timedelta(days=2))
        self.assertEqual(self.cause("daily"), "future_timestamp")

    def test_last_failed(self):
        write(self.dir, "daily.ok.json",
              ok_record("daily", NOW - timedelta(hours=5)))
        write(self.dir, "daily.last.json",
              record("daily", NOW - timedelta(hours=2), 1))
        self.assertEqual(self.cause("daily"), "last_failed")

    def test_last_without_ok_is_never_succeeded(self):
        (self.dir / "status" / "daily.ok.json").unlink()
        write(self.dir, "daily.last.json",
              record("daily", NOW - timedelta(hours=2), 1))
        self.assertEqual(self.cause("daily"), "never_succeeded")

    def test_future_last_without_ok_is_never_succeeded(self):
        (self.dir / "status" / "daily.ok.json").unlink()
        write(self.dir, "daily.last.json",
              record("daily", NOW + timedelta(days=2), 1))
        self.assertEqual(self.cause("daily"), "never_succeeded")

    def test_gap_risk(self):
        write_ok(self.dir, "weekly", NOW - timedelta(days=20))
        self.assertEqual(self.cause("weekly"), "gap_risk")

    def test_cause_order_places_success_unrecorded(self):
        order = sources._CAUSE_ORDER
        self.assertEqual(order.index("success_unrecorded"),
                         order.index("last_failed") + 1)
        self.assertEqual(order.index("future_timestamp"),
                         order.index("success_unrecorded") + 1)

    def test_gap_risk_outranks_last_failed(self):
        write(self.dir, "weekly.ok.json",
              ok_record("weekly", NOW - timedelta(days=20)))
        write(self.dir, "weekly.last.json",
              record("weekly", NOW - timedelta(days=1), 1, lookback=14))
        self.assertEqual(self.cause("weekly"), "gap_risk")

    def test_last_failed_outranks_overdue(self):
        write(self.dir, "daily.ok.json",
              ok_record("daily", NOW - timedelta(hours=40)))
        write(self.dir, "daily.last.json",
              record("daily", NOW - timedelta(hours=2), 1))
        self.assertEqual(self.cause("daily"), "last_failed")


class PurityTests(unittest.TestCase):
    def test_evaluation_does_not_mutate_the_status(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_ok(directory, "daily", NOW - timedelta(hours=50))
            status = sources.load_status(directory)
            before = json.dumps(status, sort_keys=True)
            sources.check_export_status(status, NOW)
            self.assertEqual(json.dumps(status, sort_keys=True), before)


class CauseConstructionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_rtk_presence_comes_from_the_status(self):
        for job in ("daily", "weekly", "monthly"):
            write_ok(self.dir, job, NOW - timedelta(hours=1))
        status = sources.load_status(self.dir)
        status["rtkPresent"] = True
        _, exports = sources.check_export_status(status, NOW)
        self.assertEqual([e["job"] for e in exports],
                         ["daily", "weekly", "monthly", "rtk"])
        status["rtkPresent"] = False
        _, exports = sources.check_export_status(status, NOW)
        self.assertEqual([e["job"] for e in exports],
                         ["daily", "weekly", "monthly"])

    def test_cause_outside_the_order_raises_instead_of_none(self):
        write_ok(self.dir, "daily", NOW - timedelta(hours=40))
        status = sources.load_status(self.dir)
        reduced = tuple(c for c in sources._CAUSE_ORDER if c != "overdue")
        with mock.patch.object(sources, "_CAUSE_ORDER", reduced):
            with self.assertRaises(ValueError):
                sources.check_export_status(status, NOW)

    def test_unknown_rows_are_identical_in_both_branches(self):
        missing = sources.check_export_status(
            sources.load_status(self.dir), NOW)[1]
        (self.dir / "status").mkdir()
        never = sources.check_export_status(
            sources.load_status(self.dir), NOW)[1]
        self.assertEqual(missing, never)


if __name__ == "__main__":
    unittest.main()

# 06 Checks

The dashboard checks the data on every read and shows the result at the top
of the page. The point is not cosmetic: the data comes from several export
runs that can fail independently of each other. Without a cross-check, a
half-written run only surfaces when somebody doubts a number.

## Message levels

| Level | Meaning | Effect on `health.ok` |
|---|---|---|
| `error` | file unreadable or unusable, was rejected | sets it to `false` |
| `warn` | file was evaluated, but a sum does not add up | sets it to `false` |
| `info` | a check was skipped, no finding | **none** |

The special status of `info` is deliberate. An `info` message says "this
could not be checked" and must not pull the status area to "not in order" —
otherwise the reader gets used to red indicators. It stays visible all the
same.

## Message keys

Every message that reaches the browser carries `code` and `params` instead
of a finished sentence — the server does not know the active language.
`params` holds raw values: numbers as numbers, dates as ISO-8601. The
frontend looks the key up in the active catalogue (`static/i18n/de.js` or
`en.js`) and fills in the parameters.

| Key | Parameters | Level | Module |
|---|---|---|---|
| `source.file.unreadable` | `file`, `reason` | `error` | `loader.py`, `sources.py` |
| `source.monthly.daily_missing` | `file` | `error` | `loader.py` |
| `source.monthly.bad_date` | `file`, `index` | `error` | `loader.py` |
| `check.day.token_sum_mismatch` | `sum`, `total`, `delta` | `warn` | `loader.py` |
| `check.day.cost_sum_mismatch` | `breakdownCost`, `totalCost` | `warn` | `loader.py` |
| `check.file.field_mismatch` | `field`, `summed`, `total` | `warn` | `loader.py` |
| `check.file.cost_mismatch` | `summed`, `total` | `warn` | `loader.py` |
| `check.file.totals_missing` | — | `warn` | `loader.py` |
| `source.projects.not_an_object` | `file` | `error` | `sources.py` |
| `source.projects.entry_not_an_array` | `file`, `project` | `error` | `sources.py` |
| `source.projects.bad_date` | `file`, `project`, `index` | `error` | `sources.py` |
| `source.week.field_missing` | `file`, `field` | `error` | `sources.py` |
| `source.sessions.bad_entry` | `file`, `index` | `error` | `sources.py` |
| `source.blocks.bad_entry` | `file`, `index` | `error` | `sources.py` |
| `source.rtk.days_missing` | `file` | `error` | `sources.py` |
| `source.rtk.bad_date` | `file`, `index` | `error` | `sources.py` |
| `check.projects.cost_mismatch` | `summed`, `total` | `warn` | `sources.py` |
| `check.projects.token_mismatch` | `summed`, `total` | `warn` | `sources.py` |
| `check.projects.field_mismatch` | `field`, `summed`, `total` | `warn` | `sources.py` |
| `check.sessions.cost_mismatch` | `summed`, `total` | `warn` | `sources.py` |
| `check.block.token_mismatch` | `sum`, `total` | `warn` | `sources.py` |
| `check.weekrun.skipped` | `missingSessions`, `missingBlocks` | `info` | `sources.py` |
| `check.weekrun.cost_mismatch` | `blockSum`, `sessionSum` | `warn` | `sources.py` |
| `check.agents.cost_mismatch` | `summed`, `total` | `warn` | `sources.py` |
| `check.crosscheck.projects_days_missing` | `dates` | `warn` | `sources.py` |
| `check.crosscheck.monthly_days_missing` | `dates` | `warn` | `sources.py` |
| `check.crosscheck.skipped` | -- | `info` | `sources.py` |
| `check.crosscheck.cost_mismatch` | `projectSum`, `monthlySum`, `dates` | `warn` | `sources.py` |
| `check.rtk.month_mismatch` | `date`, `file`, `month` | `warn` | `sources.py` |
| `check.rtk.duplicate_date` | `date`, `files` | `warn` | `sources.py` |
| `source.status.bad_file.not_json` | `file` | `error` | `sources.py` |
| `source.status.bad_file.not_object` | `file` | `error` | `sources.py` |
| `source.status.bad_file.schema` | `file` | `error` | `sources.py` |
| `source.status.bad_file.job_mismatch` | `file`, `job` (expected, from the file name) | `error` | `sources.py` |
| `source.status.bad_file.timestamp` | `file`, `field` | `error` | `sources.py` |
| `source.status.bad_file.exit_code` | `file` | `error` | `sources.py` |
| `source.status.bad_file.targets` | `file` | `error` | `sources.py` |
| `source.status.bad_file.target_entry` | `file` | `error` | `sources.py` |
| `source.status.bad_file.lookback` | `file` | `error` | `sources.py` |
| `source.status.bad_file.lookback_not_allowed` | `file`, `job` | `error` | `sources.py` |
| `check.export.overdue` | `job`, `lastSuccess`, `ageHours` | `warn` | `sources.py` |
| `check.export.gap_risk` | `job`, `lastSuccess`, `ageDays`, `lookbackDays`, `suggestedLookback` | `error` | `sources.py` |
| `check.export.last_failed` | `job`, `lastAttempt`, `exitCode`, `files` | `warn` | `sources.py` |
| `check.export.last_failed_no_targets` | `job`, `lastAttempt`, `exitCode` | `warn` | `sources.py` |
| `check.export.last_failed_after_targets` | `job`, `lastAttempt`, `exitCode` | `warn` | `sources.py` |
| `check.export.success_unrecorded` | `job`, `lastAttempt` | `warn` | `sources.py` |
| `check.export.future_timestamp` | `job`, `timestamp` | `warn` | `sources.py` |
| `check.export.never_logged` | `job` | `info` | `sources.py` |
| `check.export.status_missing` | — | `info` | `sources.py` |

`source.file.unreadable` occurs in both modules: `loader.py` emits it for a
monthly file, `sources.py` for one of the extra sources. The two mismatch
keys with no `params` entry above (`check.file.totals_missing`) still carry
an empty `params: {}` object — the shape is always `{"code", "params"}`,
never a bare code.

`insights.coverage()` reports the range of an evaluation separately, as
`noteCode` / `noteParams` on the `coverage` block rather than as a `level`
message: `range.no_data` (no `params`), `range.empty` (`first`, `last`),
`range.partial` (`first`, `last`); `noteCode` is the empty string when the
requested period is fully covered.

The HTTP error payloads from `app.py` follow the same `{"code", "params"}`
shape but are not part of the status area: `http.path_unknown` (`path`),
`http.internal_error` (`reason`), `http.file_missing` (`file`),
`http.data_directory` (`reason` — the German exception text of
`DataDirectoryError`, which stays German by design).

Each generating module lists its own keys in a `MESSAGE_CODES` constant
(`loader.py`, `sources.py`, `insights.py`, `app.py`); `tests/test_i18n.py`
checks that every key in it exists in both catalogues and that every key
literally used in the module is listed.

## Checks on the monthly files (`loader.check_plausibility`)

**Per day, token sum.** `sumTokens` (sum of the four token fields) against
`totalTokens` from the file. That is the only reason the two fields are kept
apart.

**Per day, cost.** Sum of `modelBreakdowns[].cost` against `totalCost`.
Tolerance `COST_TOLERANCE = $0.01` for rounding differences.

**Per file.** Sum of all days against `totals`, field by field for the four
token fields and `totalTokens`, with the same tolerance for `totalCost`. If
`totals` is missing, the file cannot be checked — that counts as a finding
and is reported.

**Rejected files.** Every entry from `dataset["errors"]` is carried over as
an `error`.

The result also counts along: `filesFound`, `filesAccepted`, `filesRejected`,
`daysLoaded`, `tokenSumOk`, `tokenSumFailed`, `costSumOk`, `costSumFailed`.

## Checks on the extra sources (`sources.check_extras`)

**Project files against their `totals`.** Cost and all token fields.

**Session files against their `totals`.** Cost. Each file is checked before
sessions with the same `sessionId` are deduplicated across weekly files. The
deduplication is part of building the archive view; it does not change whether
an individual source file agrees with its own `totals`.

**Single block.** `tokenCounts` against `totalTokens`, gaps excluded.

**Blocks against sessions.** Both come from the same weekly run and must
arrive at the same amount. The comparison only happens for **identical week
coverage**: if the two sources cover different weeks, two different periods
would be pitted against each other and the message would be worthless.

If the comparison is dropped for that reason, it is reported as `info`.
Without that message the cross-check would fail silently, the status area
would stay green, and the reader would believe a cross-check had been done.
The case arises when the weekly run aborts after the blocks.

**`agents[]` against the daily value.** Sum of `agents[].totalCost` against
the day's `totalCost`.

**Projects against the monthly file.** Project files contain Claude only,
whereas monthly files can contain several agents. The comparison therefore
uses only the Claude share of the monthly file. It comes from `agents[]` when
available and otherwise from the existing model-prefix heuristic.

Coverage and cost are separate findings. Missing days are reported for either
source. Costs are compared per shared day, and a single monthly message lists
only the shared days whose costs differ. If a paid monthly row cannot be split
by agent, the cross-check is visibly skipped with level `info`.

**RTK.** This source has no `totals`, no cost and no second export run to put
anything up against. What is checked instead are the two promises that
`rtk-merge.py` can break when grouping by month and merging by `date`:

- Does every date belong to the month the file name says?
- Does every date occur only once?

## Checks on the export status (`sources.check_export_status`)

Unlike every check above, this one depends on the clock. It runs on every
request on a copy of the health, never inside the cached result (see
[chapter 3](03-backend.md)). The age is that of the last success, from
`<job>.ok.json`, at the moment of the request.

| Job | Runs | `warn` when the last success is older than | `error` when older than |
|---|---|---|---|
| `daily` | daily at 04:00 | 36 hours | — |
| `rtk` | daily at 04:15 | 36 hours | — |
| `weekly` | Sundays at 04:30 | 8 days | the local date is more than `lookbackDays` (from `weekly.ok.json`) days after the local date of the last success |
| `monthly` | on the 1st at 05:00 | on the 2nd of a month or later, when the last success lies before the 1st of the current month | — |

The monthly rule uses the local calendar of the machine, because launchd
starts the job in local time. The `weekly` rule is two-staged: from 8 days up
to `lookbackDays` the next regular run still bridges the gap, so there is only
the `check.export.overdue` warning; beyond it the next run no longer reaches
the missing stretch and `check.export.gap_risk` replaces the warning. The
error threshold counts local calendar dates, not hours: `ccusage-export.sh`
exports from the local date "today minus `lookbackDays`", so a success on
date S is still covered by any run up to date S + `lookbackDays`, and the
error appears from local midnight of S + `lookbackDays` + 1. The other
thresholds work differently: the `daily` rule and the weekly `overdue`
warning compare elapsed time, and the monthly rule uses the local calendar
as described above. The parameter `ageDays` stays the elapsed time in
days; `suggestedLookback` is that age rounded up, plus 1, which always
reaches back to the date of the last success;
the status area shows the call
`CCUSAGE_DATA_DIR="<data>" CCUSAGE_LOOKBACK_DAYS=<n> "<data>/bin/ccusage-export.sh" weekly`.

Further findings, independent of the age:

- `check.export.success_unrecorded` (`warn`, cause `success_unrecorded`)
  when the last attempt ended with exit code 0 but there is no valid `ok`
  file or it is older than `last`. Both files are written with the same
  content in one step, so the success record was lost; `last` is not taken
  as a success, the age rules keep running on the older `ok` if there is
  one.
- `check.export.last_failed` (`warn`) when the last attempt has an exit code
  other than 0 and is either newer than the last success or has no valid `ok`
  file beside it (a missing `ok` with exit code 0 is `success_unrecorded`,
  not this). The code states what the targets show: `check.export.last_failed`
  with `files` when targets ended `aborted` or `failed`;
  `check.export.last_failed_no_targets` when the run stopped before reaching
  any target; `check.export.last_failed_after_targets` when every target was
  written or frozen and the run failed afterwards. All three have the cause
  `last_failed`, or `never_succeeded` when there is no success at all.
- `check.export.future_timestamp` (`warn`) when a timestamp lies in the
  future, one message per job with the latest such timestamp. Only a last
  success in the future suspends the age rules of that job, because its age
  is then meaningless; a future `last` beside a past `ok` leaves the age
  rules on that `ok` in force, so `gap_risk` and `overdue` still appear.
- `check.export.never_logged` (`info`) when `status/` exists but has no file
  for the job.
- `check.export.status_missing` (`info`) when `status/` does not exist at all.
  One message replaces the per-job ones, and every job has state `unknown`.
  `install.sh --demo` deliberately does not create `status/`, so the demo
  shows exactly this message ("Export: kein Status"): demo data have no
  exports to monitor.
- The `rtk` job is only evaluated when `rtk/` exists.
- A broken status file gives `source.status.bad_file.<rule>` and counts as
  absent.

`info` messages do not set `health.ok` to `false`, so a fresh installation
stays green until a job is actually late.

## The status area

Shows a summary (files found, accepted, rejected, days loaded, sum checks
passed) and below it the message list with level, area, key and text.

Areas: `day`, `file`, `projects`, `sessions`, `block`, `wochenlauf` (weekly
run), `agents`, `kreuzpruefung` (cross-check), `rtk`, `export`.

## What to do about a message

| Key | Likely cause | What to do |
|---|---|---|
| `source.file.unreadable` (file unreadable) | export aborted, JSON incomplete | look at `logs/<run>.log`, repeat the run |
| `check.file.totals_missing` (field `totals` missing) | older file, or a source without `totals` | normal for `blocks/` and `rtk/`, otherwise check |
| `check.day.token_sum_mismatch` (token sum differs) | `ccusage` exported inconsistently | re-export the month |
| `check.crosscheck.projects_days_missing` | project export started after old JSONL source data had expired | the gap is historical; restore it from a backup if one exists |
| `check.crosscheck.monthly_days_missing` | monthly export is incomplete | repeat the `daily` run |
| `check.crosscheck.cost_mismatch` | Claude costs differ on days present in both exports | repeat the `daily` run; for an old partial day, restore from a backup if possible |
| `check.crosscheck.skipped` | monthly costs cannot be split into Claude and other agents | re-export the month with model or agent breakdowns |
| `check.weekrun.skipped` (cross-check skipped, `info`) | weekly run aborted after the blocks | look at `logs/weekly.log`, repeat the weekly run |
| `check.rtk.duplicate_date` (date occurs more than once) | `rtk-merge.py` wrote two monthly files with the same day | look at the affected file, repeat the rtk run |
| `check.export.overdue` | a run did not happen or failed repeatedly; the machine was off | look at `logs/<job>.log`; trigger the run by hand |
| `check.export.gap_risk` | the weekly run failed for longer than its lookback | run the call shown in the status area, with the suggested lookback, before the roughly 31 days of source history run out |
| `check.export.last_failed` | the last run ended with an exit code other than 0 | look at `logs/<job>.log`; the listed files were not updated |
| `check.export.last_failed_no_targets` | the run stopped before any export, e.g. `ccusage` or `rtk` not found | look at `logs/<job>.log`; repeat the run |
| `check.export.last_failed_after_targets` | every target was written, a later step such as the log rotation failed | look at `logs/<job>.log`; the data files are current |
| `check.export.success_unrecorded` | the run succeeded (exit code 0), but `<job>.ok.json` is missing, damaged or older than `<job>.last.json` | look at `logs/<job>.log`; repeat the run |
| `check.export.future_timestamp` | the clock ran ahead, or the status file was edited | check the system clock; repeat the run |
| `check.export.never_logged` | the job has not run since `status/` exists | wait for the next run or trigger it by hand |
| `check.export.status_missing` | installation predates the status files, or demo mode | existing installations: `./install.sh --force`, see [chapter 7](07-installation.md) |
| `source.status.bad_file.<rule>` | status file damaged or hand-edited | repeat the run; it rewrites the file |

Every run can be triggered by hand, see [chapter 7](07-installation.md).

## Checks skipped in the test run

`SchemaAbgleichTests` in `tests/test_sample_data.py` holds the sample data
against the fields of the real export files. That comparison needs a real
data directory and is skipped without the environment variable
`TOKEN_DASHBOARD_REAL_DATA` — as are `ReferenceValueTests`,
`FilteredReferenceTests` and `RealDataReferenceTests`. `unittest` only names
the reason with `-v`; without this paragraph, a reader takes a cross-check
that never ran for one that passed.

To switch them on:

```bash
TOKEN_DASHBOARD_REAL_DATA="$HOME/Library/Application Support/Claude-Code-Usage" \
  python3 -m unittest discover -s tests -t .
```

`tests/test_install.py` checks `install.sh` through `--dry-run` only — a real
run would create directories and interfere with launchd. Two tests in it are
platform-bound and skip each other: the dry run with `--with-launchagents`
only runs on macOS, the check of the abort outside macOS only elsewhere. On a
single machine one of the two is therefore always skipped; only macOS and CI
together cover both cases.

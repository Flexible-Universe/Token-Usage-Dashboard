# 08 Development

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

Always from the project root, because that is where the modules lie on the
search path. There are currently 230 tests with five skips: four skipped
real-data test classes and one platform-specific installation check. With the
project's real data directory named in `TOKEN_DASHBOARD_REAL_DATA`, the real
files add data-driven reference cases and the result is 251 tests with only
the platform-specific check skipped.

| File | Covers |
|---|---|
| `tests/test_loader.py` | configuration, reading, normalizing, plausibility |
| `tests/test_metrics.py` | metrics and the reference values against real files |
| `tests/test_sources.py` | the four extra sources and `check_extras` |
| `tests/test_insights.py` | metrics of the extra sources, coverage |
| `tests/test_app.py` | routing, API, static files, start |
| `tests/test_frontend.py` | browser filter flow through dependency-free Node tests |
| `tests/test_i18n.py` | catalogue parity and message code completeness |
| `tests/helpers.py` | test data and temporary directories |

### Reference tests

`ReferenceValueTests` and `FilteredReferenceTests` in `test_metrics.py`, and
`RealDataReferenceTests` in `test_insights.py`, compute against the real
files. If the directory is missing they are skipped — the run is green then,
but covers less.

The directory is named by the environment variable
`TOKEN_DASHBOARD_REAL_DATA`, which `tests/helpers.py` reads into
`REAL_DATA_DIR` — **not** by `config.toml`. Without the variable these tests
skip themselves, and the skip note says so.

They deliberately check against the `totals` of the source file rather than
against hard-coded amounts. A hard-coded amount would have to be updated
after every export and would be wrong by the second time.

These tests are the acceptance criterion for the separation between
`metrics.py` and `insights.py` having held. They must pass unchanged after
every change.

## Conventions

**Language.** All visible texts run through the language catalogues under
`static/i18n/` (German and English), never as a literal in the code — see
chapter 4 for the switcher and chapter 6 for the message keys the backend
emits instead of sentences. Number and date format follow the language;
German rendering uses a decimal comma and a thousands point, dates as
TT.MM.JJJJ. Costs stay US dollars in both languages. The documentation is in
English. Code comments and docstrings are English for new and changed lines
as of 12.09.2026; the pre-existing German comments are not translated
retroactively.

**No umlauts in source code and comments.** Use `ue`, `ae`, `oe`, `ss`
instead. This holds for Python, JavaScript, Markdown in this repository and
commit messages. It is the existing convention and it is carried forward.

**No third-party packages.** No `pip install`, no venv, no
`requirements.txt`. Anyone needing a function the standard library does not
have writes it, or drops the function.

**Comments give reasons, they do not describe.** The existing code comments
exactly where a decision would otherwise look like a mistake — why the
savings rate comes from sums and not from daily rates, why a skipped
cross-check is reported, why `_local_date` exists. A comment repeating what
the line already says does not belong.

**Timestamps stay ISO-8601 UTC in the backend.** The conversion to local time
happens in the frontend. The only exception is the derived field `date`, on
which the period filter works.

**Missing directories are not an error, broken files are.** A file that
exists but is unusable is rejected and reported, never silently skipped.

**Missing calendar days stay gaps.** Anyone building a new time series builds
it on `metrics._calendar_labels` or `insights._calendar_axis` respectively and
enters `null` on missing days.

## How changes are made

The project has grown specification-driven so far: first a design that records
the question and the decision, then a plan with individually checkable tasks,
then the implementation task by task, tests first.

Designs and plans are kept outside the repository.

For a new feature this order has proven itself:

1. **Design.** What does the source really deliver? Which fields mean
   something other than their name suggests? Which number would be tempting
   but unfounded? The RTK design is a good example: it explains at length why
   there is **no** monetary value.
2. **Plan.** Tasks that can be finished and tested one at a time.
3. **Test first.** The test describes the expected behaviour before it
   exists.
4. **Implementation.** One task, one commit.
5. **Full test run** after every task.

## Adding a new data source

Using the fourth source (`rtk/`) as the example, traceable commit by commit:

1. `sources.py`: write `load_<source>`, search the directory with
   `find_source_files`, normalize the rows, report broken ones. Add it to
   `load_extras`.
2. `sources.check_extras`: add the checks. If there is no `totals` and no
   second export run, work out which promises the export script can break.
3. `insights.py`: `<source>_insights` with KPIs, a time series and
   `coverage`. If the source does not support a model filter, pass
   `modelFilterSupported: false`.
4. `app.py`: add the endpoint and add the source to `DataStore.SUBDIRS`, so
   that the fingerprint picks it up.
5. `static/`: tab in `TABS`, tab button, panel, load and draw function.
6. Tests in `test_sources.py`, `test_insights.py`, `test_app.py`.
7. Update `README.md` and this documentation.

Step 4 is easily forgotten: without the entry in `SUBDIRS`, the `DataStore`
notices nothing about changed files of the new source.

## What is deliberately not done

| Idea | Why not |
|---|---|
| A monetary value for the rtk savings | There is no list price in the dashboard, only an empirical usage ratio. The multiplication would look serious and have no basis |
| An rtk breakdown per command | Only available as an ASCII table. A parser for it breaks silently as soon as rtk changes its layout |
| Storing weekly and monthly rtk aggregates | Derivable from the daily data. Two truths for the same number is one too many |
| Reconstructing project paths from the key | The source replaces `/` with `-`; a hyphen inside a directory name is afterwards indistinguishable from the path separator. It is shortened, not guessed |
| Trend extrapolation instead of the daily mean | The projection is meant to stay comprehensible |
| Third-party packages for charts or the server | The dashboard should start on any machine with Python |

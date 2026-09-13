# 03 Backend

## `app.py` — server and routing

### Start

`main()` runs in a fixed order and aborts with exit code 2 on any error:

1. `loader.load_config` reads `config.toml`. If the file is missing, it is
   created with default values and a note is printed.
2. `loader.resolve_data_directory` resolves `[data].directory`.
3. `loader.check_data_directory` checks that at least one file matching
   `YYYY-MM.json` lies there. If not: abort, naming the path that was checked
   and the `config.toml` it came from.
4. `build_server` binds the server.
5. Optionally a timer opens the browser after 0.7 seconds.

### `DataStore`

Holds the parsed result in memory and reloads on demand. The trigger is a
**fingerprint**: path, `st_mtime_ns` and size of all source files. If any of
that changes, everything is read again. The comparison is deliberately blunt
— with a handful of files, one `stat()` pass per request is cheaper than any
bookkeeping about what might have changed.

`get(force=True)` forces a reload; every endpoint accepts `reload=1` for
that.

On load, the findings of both sides are merged: `loader.check_plausibility`
for the monthly files, `sources.check_extras` for the extra sources, plus the
read errors of the extra sources as messages of level `error`. Every message
carries `code` and `params`, never a finished sentence — `params` holds raw
values, numbers as numbers and dates as ISO-8601, so the frontend can render
them in the active language.

One peculiarity: `health["ok"]` ignores messages of level `info`. An `info`
message names a check that was skipped and is not a finding. It must not pull
the status area to "not in order".

### Concurrency

`ThreadingHTTPServer` with `daemon_threads`. The `DataStore` protects itself
with a `threading.Lock` that encloses the fingerprint check and the reload
together. The handler is created as its own class per server instance
(`type("BoundHandler", …)`), so that `store` can be a class attribute without
two servers sharing the same memory.

### Static files

`_serve_static` resolves the target path and checks that it lies inside
`static/`. The comparison prevents `..` escapes.

### API

All responses are JSON with `Cache-Control: no-store`. Errors come back as
`{"code": "…", "params": {…}}` with a matching status code, never as a
finished sentence — the browser is the only side that knows the active
language. Keys: `http.path_unknown` (`{path}`), `http.internal_error`
(`{reason}`), `http.file_missing` (`{file}`), `http.data_directory` (`{reason}`, the German exception text of
`DataDirectoryError` — this one parameter stays German by design, only
whoever edits `config.toml` ever sees it). `HEAD` is mapped onto `GET`.

| Endpoint | Contents | `reload` | `from`/`to` | `models` |
|---|---|---|---|---|
| `GET /api/data` | raw data, file list, models, months, period, health | yes | — | — |
| `GET /api/metrics` | all metrics of the overview | yes | yes | yes |
| `GET /api/health` | the health block only | yes | — | — |
| `GET /api/projects` | metrics per project | yes | yes | yes |
| `GET /api/sessions` | metrics per session | yes | yes | yes |
| `GET /api/blocks` | metrics of the 5-hour blocks | yes | yes | — |
| `GET /api/rtk` | metrics of the rtk savings | yes | yes | — |

`/api/blocks` ignores `models`, because the source only reports `models[]`
per block without a cost split. `/api/rtk` ignores `models`, because the
source knows nothing about models. Both report this in the field
`modelFilterSupported: false`.

`models` accepts multiple occurrences and comma-separated lists
(`?models=a,b&models=c`) and is collapsed into a sorted, duplicate-free list.

## `loader.py` — configuration and monthly files

### Configuration

`config.toml` lies next to `app.py`.

```toml
[data]
directory = "~/Library/Application Support/Claude-Code-Usage"

[server]
host = "127.0.0.1"
port = 8000
open_browser = true
```

Missing keys fall back to the defaults **individually**, not the whole
section. An unusable port, or a section that is not a table, produces a
console note and is replaced. Broken TOML, by contrast, is a `ConfigError`
and ends the start.

Relative paths are resolved relative to `config.toml`, and `~` is expanded.

### Normalizing

`normalize_day` turns both schema variants into one uniform record. The
number conversion is deliberately forgiving: `_as_int` and `_as_float` return
zero instead of raising for `None`, for a boolean, or for nonsense. This is
not a silent fallback in the forbidden sense — the sum check catches it
afterwards and reports the discrepancy.

Derived fields per day:

| Field | Origin |
|---|---|
| `month`, `day` | from `date` |
| `sumTokens` | sum of the four token fields |
| `totalTokens` | taken from the file |
| `agents` | from `metadata.agents`, otherwise from the model prefixes |
| `agentBreakdowns` | from the file's `agents` field |
| `schema` | `"period"` or `"date"` |
| `sourceFile` | file name |

`sumTokens` and `totalTokens` are kept apart on purpose. Comparing them is
the plausibility check.

`agent_for_model` attributes models with the prefix `gpt-` to Codex, all
others to Claude.

### Rejecting

A file without readable JSON, or without a `daily` array, is rejected whole
and reported in `errors`. A single entry without a valid date is skipped and
likewise reported. Both carry `code` and `params`, never a sentence.

`loader.MESSAGE_CODES` (and the matching `sources.MESSAGE_CODES`,
`insights.MESSAGE_CODES`, `app.MESSAGE_CODES`) lists every key that module
can emit. `tests/test_i18n.py` checks both directions: every key in the
constant sits in every catalogue under `static/i18n/`, and every key literally
used in the module sits in the constant.

## `metrics.py` — metrics of the overview

Works on the normalized daily data only and knows nothing about the extra
sources.

`filter_days` filters by period and models. If a model filter is active, the
daily values are **rebuilt** from the matching `modelBreakdowns`; without a
model filter the original values from the file stay untouched. The
distinction matters: the original values are the billed truth, the rebuilt
ones a subset of it.

The individual metrics are covered in [chapter 5](05-metrics.md).
`compute_metrics` calls them all and returns an object with `filter`,
`summary`, `months`, `cumulativeByMonth`, `dailySeries`, `stackedByModel`,
`models`, `pareto`, `timeline`, `topDays` and `projection`.

## `sources.py` — extra sources

Four loaders, one pattern: find files, read JSON, normalize rows, report
broken rows, return sorted.

`load_projects`, `load_sessions`, `load_blocks`, `load_rtk`, bundled in
`load_extras`. Missing directories are not an error.

Weekly files run through the shared scaffold `_load_week_files`. The order
follows the file name, and later files overwrite earlier content —
deduplicated by `sessionId` or `id` respectively, exactly as in the export
script.

**Timestamps stay ISO-8601 UTC.** Only the derived field `date` is built in
local time via `_local_date`, because that is what the period filter works
on, while the table shows the time in local time anyway. Without the
conversion, a session falls into the UTC day even though the UI displays the
neighbouring day. The weekly files do not cover exactly one calendar week;
filtering therefore goes by the timestamp inside the record, not by the file
name.

`agent_split` splits cost and tokens per day between Claude and Codex. If the
day carries the `agents` field, that is used (`source: "agents"`), otherwise
the model heuristic applies (`source: "heuristik"`). This keeps the whole
history displayable. The parameter `prefer_agents=False` forces the
heuristic; `app.py` uses that when a model filter is active, because
`filter_days` only recomputes `modelBreakdowns` and `agentBreakdowns` would
stay unfiltered.

`check_extras` checks the extra sources, see [chapter 6](06-checks.md).

## `insights.py` — metrics of the extra sources

`project_insights`, `session_insights`, `block_insights`, `rtk_insights` and
`agent_series`.

Every evaluation returns a `coverage` block that compares the requested
period with the one actually present and, where needed, supplies `noteCode`
and `noteParams` instead of a ready-worded sentence — the frontend builds the
note from the catalogue. That lets the user interface distinguish "no cost in
this period" from "this source does not exist for this period yet".

`_calendar_axis` reuses `metrics._calendar_labels`, so that both sides apply
the same rule for calendar gaps instead of duplicating it.

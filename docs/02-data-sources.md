# 02 Data sources and export

## Who produces the data

Two tools deliver the raw data, both outside this repository:

- **`ccusage`** reads the JSONL logs of Claude Code under `~/.claude` and
  emits daily, project, session and block data as JSON.
- **`rtk`** ("Rust Token Killer") is a proxy in front of developer tools. It
  filters command output and records how many tokens therefore never reached
  a model. `rtk gain --all --format json` prints that statistic.

Two shell scripts call these tools and write the results as JSON files into
the data directory. Four launchd jobs start the scripts. The dashboard only
ever sees the result.

## The data directory

Default path:

```
~/Library/Application Support/Claude-Code-Usage/
```

The path deliberately does **not** live under `~/Documents`. TCC privacy
protection applies there on macOS: a background process started by launchd
gets no access, and the export runs fail silently. `Application Support` is
free of that restriction.

```
Claude-Code-Usage/
  2026-05.json … 2026-09.json    daily data per month       <- required
  projects/YYYY-MM.json          daily data per project     <- optional
  blocks/YYYY-Www.json           5-hour billing blocks
  sessions/YYYY-Www.json         sessions
  rtk/YYYY-MM.json               token savings of the proxy
  bin/                           the export scripts
  logs/                          logs per run
```

Only the monthly files in the root directory are required. If one of the
subdirectories is missing, the dashboard still starts; the corresponding tab
then shows a coverage note instead of empty charts.

## The five kinds of file

### 1. `YYYY-MM.json` — daily data (required)

Produced with `ccusage daily --json --by-agent`.

```json
{
  "daily": [
    {
      "date": "2026-09-01",
      "inputTokens": 4108, "outputTokens": 1711502,
      "cacheCreationTokens": 11955005, "cacheReadTokens": 201389214,
      "totalTokens": 215059829, "totalCost": 189.86,
      "modelsUsed": ["claude-opus-5", "claude-sonnet-5"],
      "modelBreakdowns": [
        { "modelName": "claude-opus-5", "cost": 153.42,
          "inputTokens": 2830, "outputTokens": 1197729,
          "cacheCreationTokens": 6206481, "cacheReadTokens": 147598029 }
      ],
      "agent": "all",
      "agents": [ { "agent": "claude", "totalCost": 189.86, "totalTokens": 215059829 } ],
      "metadata": { "agents": ["claude", "codex"] }
    }
  ],
  "totals": { "inputTokens": 0, "outputTokens": 0, "cacheCreationTokens": 0,
              "cacheReadTokens": 0, "totalTokens": 0, "totalCost": 0.0 }
}
```

**Two schema variants.** Older files carry the day key as `date`, newer ones
as `period`. `loader.normalize_day` accepts both and records in the
normalized record, under `schema`, which variant the file used.

**`agent` versus `agents`.** The singular field `agent` has always been
`"all"` so far and is no use for splitting anything. The plural field
`agents`, present since 09/2026, does carry the split. The two are easy to
confuse.

**`totals` is optional, but wanted.** Without it the file sum cannot be
cross-checked, and the status area reports that.

### 2. `projects/YYYY-MM.json`

Produced with `ccusage claude daily --json -i`. One object `projects` whose
keys are the project path with `/` replaced by `-`
(`-home-devuser-projekte-beta-tool`), and per key an array of daily rows in
the same shape as above.

Because the source replaces `/` with `-`, a hyphen inside a directory name is
afterwards indistinguishable from the path separator. The way back is
therefore not guessed: `sources.assign_labels` merely strips the common
prefix of all keys and so yields a short label.

### 3. `blocks/YYYY-Www.json`

Produced with `ccusage blocks --json`. The 5-hour billing windows:

```json
{ "blocks": [ {
  "id": "...", "startTime": "…Z", "endTime": "…Z", "actualEndTime": "…Z",
  "isActive": false, "isGap": false, "entries": 412, "costUSD": 23.41,
  "totalTokens": 12345678,
  "tokenCounts": { "inputTokens": 0, "outputTokens": 0,
                   "cacheCreationInputTokens": 0, "cacheReadInputTokens": 0 },
  "models": ["claude-opus-5"],
  "burnRate": { "costPerHour": 0.0, "tokensPerMinute": 0.0 },
  "projection": { "totalCost": 0.0, "totalTokens": 0, "remainingMinutes": 0 }
} ] }
```

Two peculiarities: the token field names under `tokenCounts` differ from
those used everywhere else (`cacheCreationInputTokens` instead of
`cacheCreationTokens`), and blocks flagged `isGap` are idle time between two
windows. They count towards no sum and no mean. This is the only source
without a `totals` field.

### 4. `sessions/YYYY-Www.json`

Produced with `ccusage claude session --json`. Per session `sessionId`,
`projectPath`, `firstActivity`, `lastActivity` and the usual token and cost
fields.

### 5. `rtk/YYYY-MM.json`

From `rtk gain --all --format json`, regrouped by month:

```json
{ "days": [ { "date": "2026-09-01", "commands": 214,
              "input_tokens": 4200000, "output_tokens": 380000,
              "saved_tokens": 3820000, "savings_pct": 91.0,
              "total_time_ms": 51000, "avg_time_ms": 238 } ] }
```

**The field names mean something different here.** `input_tokens` is the raw
size of the command output *before* filtering, `output_tokens` is what rtk
passed on, and `saved_tokens` is the difference by rtk's own reckoning — by
its own reckoning, not as a subtraction: the three numbers do not add up
exactly. These tokens were never billed and cannot be offset against the
tokens of the other sources. The fields therefore keep their rtk names with
underscores instead of being renamed into the `camelCase` names of the other
sources: matching names would be a false trail.

This source reaches further back than `projects/`, `blocks/` and
`sessions/`. It has no `totals`.

## The export chain

### The scripts

`bin/ccusage-export.sh` with three modes:

| Call | What happens | When |
|---|---|---|
| `daily` | rewrite the current month and `projects/`; on the first three days of a month also the previous month | daily at 04:00 |
| `weekly` | archive `blocks/` and `sessions/` from a rolling 14-day window | Sundays at 04:30 |
| `monthly` | freeze the completed previous month | on the 1st at 05:00 |

`bin/rtk-export.sh` has no modes, and runs daily at 04:15. One run is enough:
there is no rolling window and nothing that would need archiving.

### Why the weekly run is mandatory

`blocks` and `sessions` come from the JSONL files under `~/.claude`, whose
history only reaches back about 31 days. If the weekly run fails for longer
than a month, that period is **irrecoverably lost**. Daily and project data,
by contrast, can be regenerated at any time.

### Three safety mechanisms

**Write atomically.** The export goes into a temporary file. Only after it
passes the check does an `mv` replace the target. An aborted run cannot
damage a good file.

**Catch regressions.** `bin/ccusage-check.py` compares the fresh export with
the existing file. If it contains less, that is a regression, judged
differently depending on the mode:

| Rule | Meaning | Used for |
|---|---|---|
| `strict` | a regression is an error, the file stays as it is | the current month, which can only grow |
| `merge` | the export is layered onto the existing file instead of replacing it | the rolling weekly window |
| `freeze` | a regression means: the archive is more complete than what `ccusage` can still produce today. The file stays, the run counts as successful | completed previous months |

A regression can be allowed deliberately with `CCUSAGE_ALLOW_SHRINK=1`.

**Merge instead of replace.** `bin/ccusage-merge.py` layers the fresh export
onto the existing file and deduplicates exactly as the dashboard does: blocks
by `id`, sessions by `sessionId`, the later export wins. `bin/rtk-merge.py`
does the same for the rtk days by `date` and additionally groups them by
month. Both recompute an existing `totals` from the merged rows — otherwise
the dashboard's plausibility check reports a discrepancy.

### Overlap heals missed runs

`CCUSAGE_LOOKBACK_DAYS` (default 14) sets how far back the weekly run
reaches. If one run fails, the next one catches up.

### Environment variables

| Variable | Script | Purpose |
|---|---|---|
| `CCUSAGE_DATA_DIR` | `ccusage-export.sh` | data directory |
| `RTK_DATA_DIR` | `rtk-export.sh` | data directory |
| `CCUSAGE_BIN` | `ccusage-export.sh` | path to the `ccusage` binary |
| `RTK_BIN` | `rtk-export.sh` | path to the `rtk` binary |
| `CCUSAGE_LOOKBACK_DAYS` | `ccusage-export.sh` | lookback of the weekly run, default 14 |
| `CCUSAGE_ALLOW_SHRINK` | `ccusage-export.sh` | allow a regression |

Two pitfalls that both scripts handle explicitly:

- launchd starts with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`. A `ccusage`
  installed via nvm is invisible there. Both scripts search the known
  locations for the binary and extend `PATH` by its directory, because
  `ccusage` carries the shebang `#!/usr/bin/env node`.
- The name `rtk` collides with `reachingforthejack/rtk` (Rust Type Kit).
  `rtk-export.sh` therefore first checks whether any JSON comes back at all.
  Without that check, the mix-up would only surface in the dashboard as an
  empty tab.

### Logs

One file per mode under `logs/`: `daily.log`, `weekly.log`, `monthly.log`,
`rtk.log`, each truncated to 2000 lines. Plus `launchd-*.out` and
`launchd-*.err`. A line `ABBRUCH` ("aborted") always means: the target file
was left unchanged.

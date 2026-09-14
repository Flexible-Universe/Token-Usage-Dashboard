# 01 Overview

## Purpose

The token usage dashboard evaluates the usage data of Claude Code and Codex:
cost, tokens, models, projects, sessions, billing blocks and the token
savings of the rtk proxy. It runs purely locally, sends nothing anywhere and
needs nothing beyond a Python installation.

## Scope: what the dashboard does not do

It collects no data. It starts no export runs. It never writes into the data
directory. It reads the JSON files lying there and computes metrics from
them. The separation is deliberate: a reader cannot break anything, and a
failed export shows up as a gap in the numbers instead of a half-written
file.

Who creates the files is covered in [chapter 2](02-data-sources.md).

## Technical basis

| Point | Decision |
|---|---|
| Language | Python 3.11 or newer |
| Dependencies | standard library only, no `pip`, no venv |
| Start | `python3 app.py` |
| Server | `http.server.ThreadingHTTPServer`, bound to `127.0.0.1` |
| Frontend | HTML, CSS, vanilla JavaScript, no build step |
| Charts | Chart.js 4.4.1, bundled under `static/vendor/`, with a text fallback if it fails to load |
| Tests | `unittest` from the standard library |

Doing without third-party packages is not an end in itself. It makes sure the
dashboard runs on any machine with Python, without anyone having to maintain
an environment, and that it still starts in five years.

## Building blocks

```
                data directory (outside the repository)
                YYYY-MM.json  projects/  blocks/  sessions/  rtk/
                                  |
                                  v
   loader.py  ------------->  sources.py          reading, normalizing,
   monthly files              extra sources       rejecting broken data
        |                          |
        v                          v
   metrics.py                 insights.py         metrics
   daily metrics              metrics per source
        \                          /
         \                        /
          ------> app.py <--------                DataStore, routing, JSON API
                     |
                     v
                 static/                          tabs, filters, charts
```

| File | Purpose |
|---|---|
| `app.py` | Entry point, HTTP server, routing, `DataStore` |
| `loader.py` | Configuration, reading monthly files, plausibility |
| `metrics.py` | Metrics from the daily data |
| `sources.py` | Extra sources `projects/`, `blocks/`, `sessions/`, `rtk/` |
| `insights.py` | Metrics for the extra sources |
| `static/index.html` | Skeleton of the user interface |
| `static/app.js` | All frontend logic |
| `static/style.css` | Styling |
| `tests/` | Test suite described in [chapter 8](08-development.md) |

## The separation between the two module pairs

`loader.py` and `metrics.py` are the older pair, `sources.py` and
`insights.py` the younger one. The separation is deliberately strict:

- `loader.py` reads the monthly files in the root directory and nothing else.
- `sources.py` reads the four subdirectories and nothing else, reusing the
  normalization helpers from `loader.py` instead of duplicating them.
- `metrics.py` knows nothing about the extra sources. It works on the
  normalized daily data only.
- `insights.py` reuses `metrics._calendar_labels`, so that both sides apply
  the same rule for calendar gaps.

The reference tests in `tests/test_metrics.py` check against the real monthly
files and are the acceptance criterion for this separation having held.

## Principles

**Missing calendar days are gaps.** A day without an entry does not mean
"spent zero dollars", it means "no data". Means, medians and the 7-day moving
average run over days with data only. Time series carry `null` on missing
days, so that Chart.js breaks the line instead of drawing a zero line.

**No silent fallback.** If the data directory is missing, or holds no monthly
file, the start aborts and names the path it checked. An unreadable file is
rejected and reported, not skipped. A missing subdirectory, by contrast, is
not an error: the extra sources are optional.

**No invented numbers.** Where a quantity cannot be derived cleanly, the
dashboard does not show it. That is why the RTK tab shows no monetary value,
and why `$ / 1 Mio. Output-Token` is explicitly labelled as an empirical
usage ratio rather than a list price.

**Estimates are marked as such.** The projection for the current month
carries the field `isEstimate` and is visibly flagged as an estimate in the
user interface.

# Contributing

Thank you for your interest in this project. This page sums up what a
contribution has to meet. The full list of conventions is in
[`CLAUDE.md`](CLAUDE.md).

## No CLA

There is no contributor license agreement. Contributions are made under
AGPL-3.0, the project's license.

## Development environment

Python 3.11 or newer, nothing else. No `pip install`, no venv, no third-party
packages: what the standard library does not have is either written or left
out.

```bash
python3 app.py                                  # start
python3 -m unittest discover -s tests -t .      # tests, from the root directory
```

## Workflow

One task, one commit. After every commit the full test run has to pass.
Commit messages are in English.

## Conventions

**No umlauts** in source code, comments and Markdown. Use `ue`, `ae`, `oe`,
`ss` instead.

**All visible texts in German.** Numbers with a decimal comma and a thousands
point, dates as TT.MM.JJJJ, costs in US dollars. The documentation is in
English.

**Missing calendar days are gaps, not zeros.** Means and medians run over
days with data only. Time series run over all calendar days and carry `null`
on missing days.

**No invented numbers.** Where a quantity cannot be derived cleanly, the
dashboard does not show it. Estimates are marked visibly.

**Ratios from sums, not as a mean of ratios.** Otherwise the value jumps with
the filter setting.

**No silent fallback.** Broken files are rejected and reported, never
silently skipped. A skipped check is reported too.

**Foreign text never through `innerHTML`.** Model names, project labels,
session IDs and message texts are set via `createElement` and `textContent`.

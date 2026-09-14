# 07 Installation on a fresh machine

There are two levels:

- **A — the dashboard only.** Display an existing data directory. Needs
  nothing but Python. Five minutes.
- **B — the full chain.** Additionally set up the export runs, so that the
  data directory fills itself. Needs Node.js and macOS.

## Requirements

| Level | Needs |
|---|---|
| A | Python 3.11 or newer |
| B | additionally Node.js with `ccusage`, optionally `rtk`, macOS with launchd |

Check:

```bash
python3 --version     # 3.11 or higher
```

No `pip install`, no venv, no `requirements.txt`. The dashboard uses the
standard library only.

## Level A — set up the dashboard

### 1. Get the repository

```bash
git clone https://github.com/Flexible-Universe/Token-Usage-Dashboard.git token-usage-dashboard
cd token-usage-dashboard
```

**Where the clone may live.** For level A, anywhere. For level B, not: launchd
calls the scripts and fails under `~/Documents`, `~/Desktop` and in
cloud-synchronized folders because of TCC. The reasoning is in
[`export/README.md`](../export/README.md) under "Where the clone may live".

### 2. Provide a data directory

The dashboard produces no data. It needs a directory with at least one file
matching `YYYY-MM.json`. Three ways to get one:

- Copy an existing directory from another machine.
- Set up the export chain (level B).
- Generate sample data to try things out. It is invented, but it covers every
  tab:

```bash
python3 tools/make-sample-data.py --out sample-data
```

- Or write a single file by hand:

```bash
mkdir -p ~/Library/Application\ Support/Claude-Code-Usage
cat > ~/Library/Application\ Support/Claude-Code-Usage/2026-09.json <<'JSON'
{
  "daily": [
    { "date": "2026-09-01",
      "inputTokens": 1000, "outputTokens": 5000,
      "cacheCreationTokens": 2000, "cacheReadTokens": 40000,
      "totalTokens": 48000, "totalCost": 1.23,
      "modelsUsed": ["claude-opus-5"],
      "modelBreakdowns": [
        { "modelName": "claude-opus-5", "cost": 1.23,
          "inputTokens": 1000, "outputTokens": 5000,
          "cacheCreationTokens": 2000, "cacheReadTokens": 40000 }
      ] }
  ],
  "totals": { "inputTokens": 1000, "outputTokens": 5000,
              "cacheCreationTokens": 2000, "cacheReadTokens": 40000,
              "totalTokens": 48000, "totalCost": 1.23 }
}
JSON
```

The subdirectories `projects/`, `blocks/`, `sessions/` and `rtk/` are
optional. Without them the dashboard still starts and the corresponding tabs
show a coverage note.

### 3. Adjust the configuration

`config.toml` lies next to `app.py` and is not under version control. If it is
missing, the first start creates it modelled on `config.example.toml` and
points out that the path should be checked. The preset path points at the
usual macOS data directory and rarely fits straight away:

```toml
[data]
directory = "~/Library/Application Support/Claude-Code-Usage"

[server]
host = "127.0.0.1"
port = 8000
open_browser = true
```

`~` is expanded. A relative path is resolved relative to `config.toml` — for
the sample data, `directory = "sample-data"` is therefore enough. Missing keys
fall back to the defaults individually.

On Linux or Windows, `~/Library/Application Support` makes no sense; there
`~/.local/share/claude-code-usage` or `%LOCALAPPDATA%` fits better. For the
dashboard itself the location is free — the reason for `Application Support`
only concerns the launchd runs on macOS (see level B).

### 4. Start

```bash
python3 app.py
```

Expected output:

```
Datenverzeichnis: /…/Claude-Code-Usage
Gefundene Monatsdateien: 5
Dashboard laeuft auf http://127.0.0.1:8000/
Beenden mit Strg+C
```

With `open_browser = true`, the browser opens by itself after a short delay.

### 5. Tests (recommended)

```bash
python3 -m unittest discover -s tests -t .
```

Expected: `OK`, currently 229 tests with five skips. Four real-data test
classes are skipped when no data directory is named, and one installation
check is platform-specific — the run is green even then, but covers less. The
skip note says so; a cross-check that never ran is never left unmentioned.

To have those reference tests run too, name the directory through the
environment variable `TOKEN_DASHBOARD_REAL_DATA` — not through `config.toml`:

```bash
TOKEN_DASHBOARD_REAL_DATA="$HOME/Library/Application Support/Claude-Code-Usage" \
  python3 -m unittest discover -s tests -t .
```

Expected for the project's reference directory: `OK`, currently 250 tests
with one optional check skipped. The real files add data-driven reference
cases and execute the reference test classes that are skipped without the
variable. If the directory is not suitable reference data, leave the variable
unset.

## Level B — set up the export chain (macOS)

### 0. The short route: `install.sh`

Steps 3 to 6 of this chapter are done by one call:

```bash
./install.sh --with-launchagents --label-prefix com.example
```

The script creates the data directory with its subdirectories, copies the five
export scripts to `<data>/bin`, creates `config.toml` from
`config.example.toml`, fills in the four launchd templates and loads them.
`--dry-run` shows beforehand what would happen, without changing anything.

What it does not overwrite: an existing `config.toml`, and scripts under
`<data>/bin` that differ from the repository. It reports both and leaves them
alone; `--force` brings the scripts up to date.

It does not install `ccusage` and `rtk` — that is what steps 1 and 2 are for.
The remaining sections describe the same route by hand; they are the
explanation of what `install.sh` does.

### 1. Install `ccusage`

```bash
npm install -g ccusage
ccusage --version
```

### 2. Install `rtk` (optional)

Only needed if the RTK tab should show data.

```bash
rtk --version     # must print "rtk X.Y.Z"
rtk gain          # must work
```

**Name collision.** There is a second tool called `rtk`
(`reachingforthejack/rtk`, Rust Type Kit). If `rtk gain` fails, the wrong one
is installed. `which rtk` shows which one is meant.

### 3. Create the data directory

```bash
DATA="$HOME/Library/Application Support/Claude-Code-Usage"
mkdir -p "$DATA"/{bin,logs,projects,blocks,sessions,rtk}
cp export/ccusage-export.sh export/rtk-export.sh export/ccusage-check.py \
   export/ccusage-merge.py export/rtk-merge.py "$DATA/bin/"
chmod +x "$DATA"/bin/*
```

The five export scripts live in the repository under `export/`:

| File | Purpose |
|---|---|
| `export/ccusage-export.sh` | export with the modes `daily`, `weekly`, `monthly` |
| `export/ccusage-check.py` | checks a fresh export against the existing file |
| `export/ccusage-merge.py` | layers an export onto an existing file |
| `export/rtk-export.sh` | export of the rtk savings |
| `export/rtk-merge.py` | merges rtk days into the monthly files |

The repository is the source, `<data>/bin` is where they run. The launchd jobs
call the copies under `bin/`, not the files in the repository: a work in
progress should not drag the nightly export down with it. Changes are
therefore always made in the repository and brought over with
`./install.sh --force`. How the scripts work, their environment variables and
the three regression rules are described in
[`export/README.md`](../export/README.md), and the shape of the files in
[chapter 2](02-data-sources.md).

### 4. Why `Application Support` and not `Documents`

On macOS, TCC privacy protection applies under `~/Documents`. A background
process started by launchd gets no access there, and the export runs fail
**silently**. `~/Library/Application Support` is free of that restriction. The
path is therefore not a matter of taste.

### 5. Test by hand

Before automating, run each run once on its own:

```bash
DATA="$HOME/Library/Application Support/Claude-Code-Usage"
CCUSAGE_DATA_DIR="$DATA" "$DATA/bin/ccusage-export.sh" daily
CCUSAGE_DATA_DIR="$DATA" "$DATA/bin/ccusage-export.sh" weekly
RTK_DATA_DIR="$DATA"     "$DATA/bin/rtk-export.sh"

tail -20 "$DATA/logs/daily.log"
```

A line `OK` names file, size and balance. A line `ABBRUCH` ("aborted") always
means: the target file was left unchanged.

If a script cannot find its binary, the matching variable helps:

```bash
CCUSAGE_BIN="$HOME/.nvm/versions/node/v22.0.0/bin/ccusage" …
RTK_BIN="/opt/homebrew/bin/rtk" …
```

### 6. Set up the launchd jobs

Four jobs under `~/Library/LaunchAgents/`. The templates live in the
repository under `export/launchd/`:

| Template | Call | Time |
|---|---|---|
| `ccusage-daily.plist.template` | `ccusage-export.sh daily` | daily at 04:00 |
| `rtk-daily.plist.template` | `rtk-export.sh` | daily at 04:15 |
| `ccusage-weekly.plist.template` | `ccusage-export.sh weekly` | Sundays at 04:30 |
| `ccusage-monthly.plist.template` | `ccusage-export.sh monthly` | on the 1st at 05:00 |

Every template carries three placeholders — `__SCRIPT_DIR__` for
`<data>/bin`, `__DATA_DIR__` for the data directory and `__LABEL_PREFIX__`
for the freely chosen prefix of the job labels, for example `com.example`.
They are replaced when the template is filled in; the finished file then
contains absolute paths only, because `~` is not expanded inside a `plist`.
The prefix must match the file name: launchd expects the file to be called
`<label>.plist`.

They are filled in and loaded by `./install.sh --with-launchagents`; the
command for the manual route is given in
[`export/README.md`](../export/README.md) under "Setting up launchd". Then
check:

```bash
LABEL_PREFIX="com.example"
launchctl list | grep ccusage

# trigger once immediately, without waiting for 04:00
launchctl kickstart -p "gui/$(id -u)/$LABEL_PREFIX.ccusage-daily"
```

Unload with
`launchctl bootout "gui/$(id -u)/$LABEL_PREFIX.ccusage-daily"`.

If the data directory is moved, the filled-in paths point nowhere. The four
`plist` files then have to be regenerated and loaded again:
`./install.sh --with-launchagents --data-dir <new path>` unloads the running
jobs, rewrites them and loads them again.

### 7. Make sure nothing is lost

**The weekly run is the critical one.** `blocks/` and `sessions/` come from
the JSONL files under `~/.claude`, whose history only reaches back about 31
days. If the weekly run fails for longer than a month, that period is
irrecoverably lost. Daily and project data, by contrast, can be regenerated
at any time.

The 14-day lookback catches a single missed run. Anyone switching the machine
off for longer should run the weekly run by hand afterwards.

## Failure modes

| Symptom | Cause | Remedy |
|---|---|---|
| `Das konfigurierte Datenverzeichnis existiert nicht` | path in `config.toml` wrong | correct the path; the message names the path that was checked |
| `liegt keine Datei im Muster YYYY-MM.json` | directory exists but is empty | run the export or copy files in |
| `Server konnte nicht auf 127.0.0.1:8000 starten` | port in use | change `port` in `config.toml` |
| charts empty, tables filled | Chart.js not loaded | the file ships with the repository under `static/vendor/`; if it is missing, the clone was incomplete. The note text is in the chart box |
| tab shows a coverage note | subdirectory missing, or does not cover the period | adjust the period or set up the export |
| RTK tab stays empty | wrong `rtk` installed, or the export never ran | check `rtk gain`, look at `logs/rtk.log` |
| status area reports discrepancies | see [chapter 6](06-checks.md) | the table of causes is there |
| export run fails under launchd but not by hand | `PATH` or TCC | look at `logs/launchd-*.err`, set `CCUSAGE_BIN`, do not put the data directory under `~/Documents` |

## Moving to another machine

1. Copy the entire data directory — it is the archive and the only
   irreplaceable part.
2. Clone the repository — not under `~/Documents` or `~/Desktop`.
3. Run `./install.sh --with-launchagents --data-dir <new path>`. That creates
   `config.toml`, rolls the export scripts out to `<data>/bin` and fills in
   the four launchd templates with the new absolute paths.
4. Run the tests.
5. Trigger every run once by hand and look at the logs.

The repository itself contains no data. The only thing that can be lost is the
data directory.

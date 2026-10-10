# 07 Installation on a fresh machine

The dashboard runs on macOS, Linux and Windows. There are two ways to get it
onto a machine:

- **The release package.** A ZIP per operating system, unpacked and
  installed with one call. Sets up the dashboard, the data directory and the
  nightly export jobs. This is the route for anyone who only wants to use
  the dashboard.
- **The repository clone.** For development, or for anyone who wants to see
  every step. Again two levels:
  - **A — the dashboard only.** Display an existing data directory. Needs
    nothing but Python. Five minutes.
  - **B — the full chain.** Additionally set up the export runs, so that the
    data directory fills itself. Needs Node.js.

## System requirements

The dashboard alone needs only Python and a browser. The export chain, which
fills the data directory, additionally needs Node.js and `ccusage`.
The installer checks these minimums (not the browser, not Claude Code) and
aborts if one is not met, see "The release package".

| Component | Required | Minimum | What for, and what is missing without it |
|---|---|---|---|
| Python | yes | 3.11 | dashboard, installer and export scripts; 3.11 brings `tomllib` for `config.toml` |
| Web browser | yes | Chrome/Edge 111, Firefox 113, Safari 16.2 | the interface; older browsers lose at least the row highlight in tables (`color-mix()`) |
| Claude Code and/or Codex | for live data | — | their local session logs are what `ccusage` evaluates; without them there is nothing to export |
| Node.js with `npm` | for live data | 22 | installs and starts `ccusage`; `ccusage` 20 declares no minimum of its own, 22 is the oldest maintained Node line |
| `ccusage` | for live data | 20.0.16 | all exports except RTK; the first version with `daily --by-agent`, which the monthly files need for the Claude/Codex split |
| `rtk` | no | 0.7.1 | the RTK tab; the first version whose `rtk gain --all --format json` carries the runtime fields. Without `rtk` the job `rtk-daily` and the directory `rtk/` are left out |
| Scheduler | no | — | the nightly exports: launchd (macOS), systemd user manager or cron (Linux), Task Scheduler (Windows); without one, `--no-jobs` and exports by hand |

Operating systems, as far as the export chain is concerned (the dashboard
alone runs wherever Python 3.11 runs):

| System | Minimum | Why |
|---|---|---|
| Windows | 10 or 11, x64 or ARM64 | Node.js 22; `ccusage` ships native binaries for x64 and ARM64 only |
| macOS | 14 Sonoma, Apple silicon or Intel | the native `ccusage` binaries are built for macOS 14.0 and refuse older versions |
| Linux | glibc 2.28, x64 or ARM64 | Node.js 22; the `ccusage` binary itself is statically linked |

`ccusage` 20 is a small Node launcher that starts a native binary from an
optional npm dependency. An `npm install` with optional dependencies switched
off (`--omit=optional`) leaves the binary out, and `ccusage` then reports
"native binary is not available".

Without Claude Code, `ccusage` and `rtk` the installer still runs: it offers
demo mode with sample data (see "Installer options").

Check:

```bash
python3 --version     # 3.11 or higher; on Windows: py -3 --version
node --version        # v22 or higher
ccusage --version     # 20.0.16 or higher
rtk --version         # 0.7.1 or higher, optional
```

No `pip install`, no venv, no `requirements.txt`. The dashboard and the
export chain use the standard library only.

Python on Windows comes from <https://www.python.org/downloads/windows/> or
`winget install Python.Python.3.13`; on macOS for example from Homebrew
(`brew install python`), on Linux from the package manager. The installer
names these sources itself when it finds no suitable Python.

**No administrator rights needed.** The installer writes only below the
user's own profile and asks for no elevation on any system. On Windows the
application goes to `%LOCALAPPDATA%\Programs`, the data to `%LOCALAPPDATA%`,
and the tasks are registered for the installing user with
`InteractiveToken` and `LeastPrivilege`, without a stored password. The
server listens on `127.0.0.1` on a port above 1024, so the Windows firewall
does not ask. What a standard account has to bring itself:

- Python installed for the current user only (python.org installer with
  "Install for all users" unticked, or `winget install --scope user
  Python.Python.3.13`).
- For the export chain a Node.js whose global `npm` directory is writable
  for the user. `npm install -g` against a Node installed for all machine
  users needs elevation; a per-user Node (for example via nvm-windows into
  the profile) avoids that.

Two things can still stop a standard account on Windows: a task folder
`\Token-Usage-Dashboard\` already created by another account, which
`schtasks` then refuses with "access denied", and policies such as AppLocker
or Intune that forbid the Task Scheduler or programs under `%LOCALAPPDATA%`.
In both cases `--no-jobs` installs the dashboard without jobs, and the
exports are started by hand.

## The release package

### 1. Unpack

Each release consists of three ZIP files, one per system:

```
token-usage-dashboard-<version>-macos.zip
token-usage-dashboard-<version>-linux.zip
token-usage-dashboard-<version>-windows.zip
```

Take the one for your system and unpack it anywhere, for example into
`Downloads`. It contains a single folder of the same name. The ZIP for
another system is refused by the installer with exit code 2.

### 2. Install

**macOS and Linux**, in a terminal inside the unpacked folder:

```bash
./install.sh
```

**Windows**: double-click `install.cmd` in the unpacked folder, or run it in
a terminal (`cmd.exe` or PowerShell):

```
install.cmd
```

When started by double-click, the window stays open at the end so the result
can be read.

Both starters only look for Python 3.11 or newer (`install.sh`: `python3`,
`python3.14` … `python3.11`, `python`; `install.cmd`: `py -3`, then `python`)
and pass every argument on to `install.py`, which does the actual work:

1. It checks the versions of Python, Node.js, `ccusage`, `rtk` and, on
   macOS, the system itself, and prints a table with one row per component:
   required or not, minimum, found version and result (`passt`, `zu alt`,
   `fehlt`, `nicht lesbar`). A version that cannot be read counts as not
   matching. If a needed component is missing or too old, the installer ends
   with exit code 2 before it writes anything; this holds for `--dry-run` and
   `--no-jobs` as well, but not for `--remove-jobs`. In demo mode only Python
   is checked. A missing `ccusage` does not block as long as `rtk` works, and
   the other way round. It also probes `rtk gain --format json` (see "Name
   collision" below). If it finds neither `ccusage` nor `rtk`, it stops
   before creating anything and offers to abort or to switch to demo mode.
2. It copies the application to the application directory:

   | Platform | Application directory |
   |---|---|
   | macOS | `~/Library/Application Support/Token-Usage-Dashboard` |
   | Linux | `${XDG_DATA_HOME:-~/.local/share}/token-usage-dashboard` |
   | Windows | `%LOCALAPPDATA%\Programs\Token-Usage-Dashboard` |

   `--app-dir` chooses another one. The unpacked folder can be deleted
   afterwards.
3. It creates the data directory with its subdirectories:

   | Platform | Data directory |
   |---|---|
   | macOS | `~/Library/Application Support/Claude-Code-Usage` |
   | Linux | `${XDG_DATA_HOME:-~/.local/share}/claude-code-usage` |
   | Windows | `%LOCALAPPDATA%\Claude-Code-Usage` |

   `--data-dir` chooses another one. `rtk/` is created only when a working
   `rtk` was found.
4. It copies the export scripts to `<data>/bin`, overwriting what is there:
   a release brings a consistent set.
5. It writes `config.toml` into the application directory, with the chosen
   data directory. An existing `config.toml` is kept; if it names another
   data directory, the installer says so.
6. It sets up the four export jobs with the system's scheduler (see
   "The export jobs" below). `--no-jobs` leaves them out.
7. It runs the exports once (`ccusage` daily and weekly, `rtk`), so the
   dashboard has data before the first night. A failure here is a note, not
   an abort; the scheduled job tries again. `--no-first-export` skips it.
8. It writes a start script: `start-dashboard.sh` on macOS and Linux with
   the interpreter it found, `start-dashboard.cmd` on Windows with the `py`
   launcher (`py -3`) when it is installed, so a Python upgrade does not
   break it. The Windows tasks use `pyw -3` for the same reason.

At the end it lists every note again and names the start script.

### 3. Start

```bash
"$HOME/Library/Application Support/Token-Usage-Dashboard/start-dashboard.sh"   # macOS
~/.local/share/token-usage-dashboard/start-dashboard.sh                        # Linux
```

On Windows double-click `start-dashboard.cmd` in
`%LOCALAPPDATA%\Programs\Token-Usage-Dashboard`. The browser opens by itself;
`Ctrl+C` in the window ends the server.

### Update, remove

An update is the same call from the newer package: the application and the
export scripts are replaced, `config.toml` and the data directory stay.

To remove the export jobs:

```bash
./install.sh --remove-jobs        # install.cmd --remove-jobs on Windows
```

If the jobs were created with `--label-prefix` or `--scheduler`, pass the same
values again. On Linux without `--scheduler`, both systemd timers and the cron
block are removed, whichever exists. Nothing in the data directory is ever deleted, neither by this
call nor by any other; the application directory and the data directory are
removed by hand if wanted.

## Installer options

The same options apply to `install.sh`, `install.cmd` and `install.py`, from
a release or from a clone:

| Option | Effect |
|---|---|
| `--with-jobs` | set up the export jobs; the default for a release, needed for a clone. `--with-launchagents` is the old name |
| `--no-jobs` | no export jobs |
| `--remove-jobs` | remove the export jobs and stop; data stays |
| `--scheduler auto\|launchd\|systemd\|cron\|schtasks` | which scheduler; `auto` picks launchd on macOS, the Task Scheduler on Windows, systemd on Linux when a user manager answers, cron otherwise |
| `--label-prefix NAME` | prefix of the job names, only together with jobs |
| `--data-dir PATH` | data directory instead of the platform default |
| `--app-dir PATH` | application directory, release only; from a clone the application stays where it is |
| `--force` | overwrite export scripts in `<data>/bin` that differ from the source (a release always does) |
| `--dry-run` | show what would happen, change nothing |
| `--demo` | demo mode with sample data, without `ccusage` or `rtk` |
| `--no-first-export` | skip the first export run at the end of the setup |

**Demo mode.** For live data, at least one of `ccusage` or a working `rtk`
must be installed. If the installer finds neither, it offers either to abort
or to activate demo mode; `--demo` chooses demo mode without asking. Demo
mode writes the generated sample data to the selected data directory and
skips the export jobs. The target must not contain existing dashboard data.
Demo mode deliberately creates no `status/`, so the demo shows the single
info message "Export: kein Status" (`check.export.status_missing`).

## The export jobs

Four jobs, in local time:

| Job | Call | Time |
|---|---|---|
| `ccusage-daily` | `ccusage-export.py daily` | daily at 04:00 |
| `rtk-daily` | `rtk-export.py` | daily at 04:15 |
| `ccusage-weekly` | `ccusage-export.py weekly` | Sundays at 04:30 |
| `ccusage-monthly` | `ccusage-export.py monthly` | on the 1st at 05:00 |

`rtk-daily` is set up only when a working `rtk` was found. Every job calls the
copy under `<data>/bin` with absolute paths: the interpreter, the script,
`--data-dir`, and `--ccusage-bin` or `--rtk-bin` with the path the installer
found. A scheduler starts with its own sparse `PATH`; pinning makes the job
decide exactly as the installer did. On Windows the jobs run under
`pythonw.exe`, so no console window opens at night.

| Scheduler | Where | Name | Check by hand |
|---|---|---|---|
| launchd (macOS) | `~/Library/LaunchAgents/<prefix>.<job>.plist` | prefix `com.<user>` | `launchctl list \| grep ccusage` |
| systemd (Linux) | `~/.config/systemd/user/<prefix>-<job>.service` and `.timer` | prefix `token-usage-dashboard` | `systemctl --user list-timers` |
| cron (Linux without systemd) | a block between two marker lines in the crontab | prefix `token-usage-dashboard` in the markers | `crontab -l` |
| Task Scheduler (Windows) | folder `\<prefix>\` | prefix `Token-Usage-Dashboard` | `schtasks /Query /TN "\Token-Usage-Dashboard\ccusage-daily"` |

Trigger a job once immediately, without waiting for 04:00:

```bash
launchctl kickstart -p "gui/$(id -u)/com.$(id -un).ccusage-daily"              # macOS
systemctl --user start token-usage-dashboard-ccusage-daily.service             # systemd
schtasks /Run /TN "\Token-Usage-Dashboard\ccusage-daily"                       # Windows
```

**Missed runs.** systemd catches up a start that was missed while the machine
was off (`Persistent=true`), and so does the Task Scheduler
(`StartWhenAvailable`). cron does not. systemd user timers and Windows tasks
run only while the user is logged in; on Linux `loginctl enable-linger`
lets the timers run without a login. Anyone switching the machine off for
longer should run the weekly run by hand afterwards (see "Make sure nothing
is lost").

Re-running the installer with jobs rewrites them: a loaded launchd job is
unloaded, rewritten and loaded again; systemd units and Windows tasks are
overwritten; the cron block is replaced, lines outside it stay.

## Level A — set up the dashboard from the repository

### 1. Get the repository

```bash
git clone https://github.com/Flexible-Universe/Token-Usage-Dashboard.git token-usage-dashboard
cd token-usage-dashboard
```

**Where the clone may live.** For level A, anywhere. For level B, the data
directory must not live in a folder that a sync client or the system guards:
on macOS not under `~/Documents`, `~/Desktop` or iCloud Drive (TCC), nowhere
in Dropbox, on Windows not in OneDrive. The reasoning is in
[`export/README.md`](../export/README.md) under "Where the data directory may
live".

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

- Or write a single file by hand (macOS path shown):

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

The subdirectories `projects/`, `blocks/`, `sessions/`, `rtk/` and `status/` are
optional (`rtk/` exists only when a working `rtk` is installed). Without them the dashboard still starts and the corresponding tabs
show a coverage note.

### 3. Adjust the configuration

`config.toml` lies next to `app.py` and is not under version control. If it is
missing, the first start creates it with the platform's default data
directory and points out that the path should be checked:

```toml
[data]
directory = "~/Library/Application Support/Claude-Code-Usage"

[server]
host = "127.0.0.1"
port = 8000
open_browser = true
```

That is the macOS form. On Linux the default is
`~/.local/share/claude-code-usage` (below `$XDG_DATA_HOME` when set), on
Windows the absolute path `%LOCALAPPDATA%\Claude-Code-Usage`, written as an
escaped TOML string (`"C:\\Users\\...\\Claude-Code-Usage"`). A Windows path
entered by hand needs doubled backslashes or single quotes
(`'C:\Users\...'`).

`~` is expanded. A relative path is resolved relative to `config.toml` — for
the sample data, `directory = "sample-data"` is therefore enough. Missing keys
fall back to the defaults individually.

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

Expected on macOS: `OK`, currently 462 tests with five skips. The four
real-data test classes (and the test of the Windows starter, which needs
Windows) are skipped when no data directory is named — the run
is green even then, but covers less. The skip note says so; a cross-check
that never ran is never left unmentioned. On Linux and Windows a few
installer tests that need launchd or a POSIX shell skip as well, see
[chapter 6](06-checks.md).

To have those reference tests run too, name the directory through the
environment variable `TOKEN_DASHBOARD_REAL_DATA` — not through `config.toml`:

```bash
TOKEN_DASHBOARD_REAL_DATA="$HOME/Library/Application Support/Claude-Code-Usage" \
  python3 -m unittest discover -s tests -t .
```

Expected for the project's reference directory on macOS: `OK`, currently 483
tests with one skip, the Windows starter test. The real files add data-driven reference cases and
execute the reference test classes that are skipped without the variable. If
the directory is not suitable reference data, leave the variable unset.

## Level B — set up the export chain from the repository

### 0. The short route: `install.sh` / `install.cmd`

Steps 3 to 6 of this chapter are done by one call:

```bash
./install.sh --with-jobs                  # macOS, Linux
install.cmd --with-jobs                   # Windows
```

From a clone the application stays where it is: `config.toml` is written
next to `app.py`, and no start script is created. Otherwise the installer
does what is described under "The release package": it creates the data
directory with its subdirectories, copies the seven export files
(`ccusage-export.py`, `rtk-export.py`, `exportlib.py`, `ccusage-check.py`,
`ccusage-merge.py`, `rtk-merge.py`, `export-status.py`) to `<data>/bin`,
creates `config.toml` and sets up the jobs. Without `--with-jobs` it does
everything but the jobs. `--dry-run` shows beforehand what would happen,
without changing anything.

`rtk/` and the `rtk-daily` job are set up only when a working `rtk` is found:
the installer looks in `RTK_BIN`, the fixed directories of its platform (see
[`export/README.md`](../export/README.md)) and then `PATH`, and requires
`rtk gain --format json` to return JSON. Otherwise it skips both and prints a
note; after installing `rtk`, run the installer again. An existing install
with an empty `rtk/` and an `rtk-daily` job is not cleaned up automatically:
the installer names the empty `rtk/`, the `status/rtk.*.json` files and the
job, and leaves their removal to you.

What it does not overwrite from a clone: an existing `config.toml`, and
scripts under `<data>/bin` that differ from the repository. It reports both
and leaves them alone; `--force` brings the scripts up to date.

**Existing installations from the Bash era need one run with `--force`.**
Earlier versions installed `ccusage-export.sh` and `rtk-export.sh` and launchd
templates that called them. Run

```bash
./install.sh --with-jobs --force
```

with the same `--label-prefix` as before, if one was given (the default is
`com.<user>`, as it was): the plists are rewritten in place and now call the
Python scripts. A different prefix would create a second set of jobs beside
the old ones. The old `.sh` copies in `<data>/bin` are reported as obsolete
and not deleted; they can be removed by hand. `--force` additionally
replaces helpers such as `ccusage-check.py` whose old copies differ from the
repository; without it they stay in place and are reported.

The installer does not install `ccusage` and `rtk` — that is what steps 1 and
2 are for. The remaining sections describe the same route by hand; they are
the explanation of what the installer does.

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
is installed. `which rtk` (`where rtk` on Windows) shows which one is meant.

### 3. Create the data directory

```bash
DATA="$HOME/Library/Application Support/Claude-Code-Usage"
mkdir -p "$DATA"/{bin,logs,projects,blocks,sessions}   # rtk/ is created by rtk-export.py after a successful probe
cp export/*.py "$DATA/bin/"
```

The seven export files live in the repository under `export/`:

| File | Purpose |
|---|---|
| `export/ccusage-export.py` | export with the modes `daily`, `weekly`, `monthly` |
| `export/rtk-export.py` | export of the rtk savings |
| `export/exportlib.py` | shared helpers of both |
| `export/ccusage-check.py` | checks a fresh export against the existing file |
| `export/ccusage-merge.py` | layers an export onto an existing file |
| `export/rtk-merge.py` | merges rtk days into the monthly files |
| `export/export-status.py` | writes the status files of a run |

The repository is the source, `<data>/bin` is where they run. The jobs call
the copies under `bin/`, not the files in the repository: a work in progress
should not drag the nightly export down with it. Changes are therefore always
made in the repository and brought over with `./install.sh --force`. How the
scripts work, their options and environment variables and the three
regression rules are described in [`export/README.md`](../export/README.md),
and the shape of the files in [chapter 2](02-data-sources.md).

### 4. Why `Application Support` and not `Documents`

On macOS, TCC privacy protection applies under `~/Documents`. A background
process started by launchd gets no access there, and the export runs fail
**silently**. `~/Library/Application Support` is free of that restriction. The
path is therefore not a matter of taste. On every system, a folder managed by
a sync client (Dropbox, OneDrive) is a poor place for the data directory; the
installer warns about it.

### 5. Test by hand

Before automating, run each run once on its own:

```bash
DATA="$HOME/Library/Application Support/Claude-Code-Usage"
python3 "$DATA/bin/ccusage-export.py" daily  --data-dir "$DATA"
python3 "$DATA/bin/ccusage-export.py" weekly --data-dir "$DATA"
python3 "$DATA/bin/rtk-export.py"            --data-dir "$DATA"

tail -20 "$DATA/logs/daily.log"
```

On Windows, in PowerShell:

```
$DATA = "$env:LOCALAPPDATA\Claude-Code-Usage"
py -3 "$DATA\bin\ccusage-export.py" daily --data-dir "$DATA"
Get-Content "$DATA\logs\daily.log" -Tail 20
```

A line `OK` names file, size and balance. A line `ABBRUCH` ("aborted") always
means: the target file was left unchanged.

If a script cannot find its binary, name it:

```bash
python3 "$DATA/bin/ccusage-export.py" daily --data-dir "$DATA" \
  --ccusage-bin "$HOME/.nvm/versions/node/v22.0.0/bin/ccusage"
python3 "$DATA/bin/rtk-export.py" --data-dir "$DATA" --rtk-bin /opt/homebrew/bin/rtk
```

The environment variables `CCUSAGE_BIN` and `RTK_BIN` do the same where the
shell allows a variable in front of the command.

### 6. Set up the jobs

Up to four jobs (`rtk-daily` only with a working `rtk`), with the times and
names listed under "The export jobs" above. The installer generates them;
there are no templates to fill in by hand any more. To see exactly what it
would write, without writing it:

```bash
./install.sh --with-jobs --dry-run
```

The dry run prints every file or task it would create together with the
complete call. Every call uses absolute paths only, because neither a plist
nor a unit file nor a scheduled task expands `~`.

If the data directory is moved, the paths in the jobs point nowhere.
`./install.sh --with-jobs --data-dir <new path>` rewrites them.

### 7. Make sure nothing is lost

**The weekly run is the critical one.** `blocks/` and `sessions/` come from
the JSONL files under `~/.claude`, whose history only reaches back about 31
days. If the weekly run fails for longer than a month, that period is
irrecoverably lost. Daily and project data, by contrast, can be regenerated
at any time.

The dashboard watches this: the header shows the state of every export job,
and a weekly success further back than its lookback (by local date) raises `check.export.gap_risk`
with the call that closes the gap, see [chapter 6](06-checks.md).

The 14-day lookback catches a single missed run. Anyone switching the machine
off for longer, above all with cron, should run the weekly run by hand
afterwards.

## Failure modes

| Symptom | Cause | Remedy |
|---|---|---|
| `Python 3.11 oder neuer wurde nicht gefunden` | no suitable Python for the starter | install Python 3.11+, see "System requirements" |
| version table with `zu alt`, `fehlt` or `nicht lesbar`, exit code 2 | a needed component is older than its minimum, missing or its version cannot be read | install or update the component named in the message, see "System requirements"; nothing was written yet |
| `Dieses Paket ist fuer …` | release ZIP for another system | take the ZIP for this system |
| `Das konfigurierte Datenverzeichnis existiert nicht` | path in `config.toml` wrong | correct the path; the message names the path that was checked |
| `liegt keine Datei im Muster YYYY-MM.json` | directory exists but is empty | run the export or copy files in |
| `Server konnte nicht auf 127.0.0.1:8000 starten` | port in use | change `port` in `config.toml` |
| charts empty, tables filled | Chart.js not loaded | the file ships with the repository under `static/vendor/`; if it is missing, the clone was incomplete. The note text is in the chart box |
| tab shows a coverage note | subdirectory missing, or does not cover the period | adjust the period or set up the export |
| RTK tab stays empty | wrong `rtk` installed, or the export never ran | check `rtk gain`, look at `logs/rtk.log` |
| status area reports discrepancies | see [chapter 6](06-checks.md) | the table of causes is there |
| export run fails as a job but not by hand | `ccusage` moved (for example after a Node upgrade), or a protected folder | look at `logs/<job>.log` and the scheduler logs in `logs/`; run the installer with jobs again so it pins the new path; do not put the data directory under `~/Documents` or in a synced folder |

## Moving to another machine

1. Copy the entire data directory — it is the archive and the only
   irreplaceable part.
2. Install the release package with `--data-dir <new path>`, or clone the
   repository and run `./install.sh --with-jobs --data-dir <new path>`
   (`install.cmd` on Windows). That creates `config.toml`, rolls the export
   scripts out to `<data>/bin` and sets up the jobs with the new absolute
   paths.
3. From a clone: run the tests.
4. Trigger every run once by hand and look at the logs.

The application contains no data. The only thing that can be lost is the
data directory.

# Export chain

The dashboard only reads files. The data directory is filled by the scripts in
this directory: they query `ccusage` and `rtk`, check the output and write it
atomically into the data directory. No step overwrites an existing file before
the new output has been checked.

## macOS ONLY

The date arithmetic in `ccusage-export.sh` uses the BSD form of `date`
(`date -v1d -v-1m`). On Linux the script aborts on the first date line.
Deliberately not ported: a reimplementation could not be verified without a
Linux machine, and an unverified reimplementation is worse than an honest
limitation.

## The scripts

| File | Purpose |
|---|---|
| `ccusage-export.sh` | Calls `ccusage` in three modes |
| `rtk-export.sh` | Calls `rtk gain`, one run per day is enough |
| `ccusage-check.py` | Checks a fresh export against the existing file |
| `ccusage-merge.py` | Layers an export onto an existing archive file |
| `rtk-merge.py` | Distributes the rtk export across monthly files and merges them |

The three modes of `ccusage-export.sh`:

- `ccusage-export.sh daily` rewrites the current month, plus, during the first
  three days of a month, the previous month once more. Affects `YYYY-MM.json`
  in the root directory and in `projects/`.
- `ccusage-export.sh weekly` archives blocks and sessions into
  `blocks/YYYY-Www.json` and `sessions/YYYY-Www.json`.
- `ccusage-export.sh monthly` freezes the completed previous month.

`rtk-export.sh` has no modes. It fetches the complete history
(`rtk gain --all --format json`) and merges it into `rtk/YYYY-MM.json`.

## Why the weekly run is mandatory

Blocks and sessions come from the JSONL files under `~/.claude`, whose history
only reaches back about 31 days. If the weekly run fails for longer than a
month, that period is irrecoverably lost. Daily and project data, by contrast,
can be regenerated at any time — they come from a source that does not expire.

## Regressions: strict, merge, freeze

An export containing less than the existing file would delete data. How that
should be judged depends on the run.

- `strict` — a regression is an error, the existing file stays as it is. For
  the current month, which can only grow; if it shrinks, something is wrong.
- `merge` — the export is layered onto the existing file instead of replacing
  it. For the rolling weekly window, whose start moves on with every run and
  would otherwise take the day that fell out with it. The file can then only
  grow.
- `freeze` — a regression means: the archive is more complete than what
  `ccusage` can still produce today. The file stays, the run counts as
  successful. For completed previous months.

A regression can be allowed deliberately: `CCUSAGE_ALLOW_SHRINK=1`.

## Environment variables

| Variable | Meaning | Default |
|---|---|---|
| `CCUSAGE_DATA_DIR` | data directory for `ccusage-export.sh` | `~/Library/Application Support/Claude-Code-Usage` |
| `CCUSAGE_BIN` | path to the `ccusage` binary | searched for |
| `CCUSAGE_LOOKBACK_DAYS` | overlap of the weekly window in days | `14` |
| `RTK_DATA_DIR` | data directory for `rtk-export.sh` | `~/Library/Application Support/Claude-Code-Usage` |
| `RTK_BIN` | path to the `rtk` binary | searched for |

Both scripts search for the binary themselves, because launchd starts with
`PATH=/usr/bin:/bin:/usr/sbin:/sbin` and nvm or Homebrew are invisible there.
If the search finds nothing, the run aborts with a message — it never runs
silently into nothing.

## Where the scripts run

The files in this directory are the source, not the place of deployment.
`install.sh` in the root directory copies them to `<data>/bin`, and the
launchd jobs call those copies. The detour is deliberate: a work in progress
should not drag the nightly export down with it. If something changes here,
`./install.sh --force` brings the copies up to date; if they differ without
`--force` being set, the script reports it and leaves them alone.

## Setting up launchd

The ordinary route is `./install.sh --with-launchagents` from the root
directory. What happens in the process is described by the rest of this
section — you only need it if the jobs are to be created by hand.

The four templates under `launchd/` carry three placeholders:

| Placeholder | Value |
|---|---|
| `__SCRIPT_DIR__` | absolute path of `<data>/bin` |
| `__DATA_DIR__` | absolute path of the data directory |
| `__LABEL_PREFIX__` | your own prefix for the job labels, for example `com.example` |

```bash
DATA_DIR="$HOME/Library/Application Support/Claude-Code-Usage"
SCRIPT_DIR="$DATA_DIR/bin"
LABEL_PREFIX="com.example"

for f in ccusage-daily ccusage-weekly ccusage-monthly rtk-daily; do
  sed -e "s|__SCRIPT_DIR__|$SCRIPT_DIR|g" \
      -e "s|__DATA_DIR__|$DATA_DIR|g" \
      -e "s|__LABEL_PREFIX__|$LABEL_PREFIX|g" \
      "export/launchd/$f.plist.template" \
      > "$HOME/Library/LaunchAgents/$LABEL_PREFIX.$f.plist"
  launchctl load "$HOME/Library/LaunchAgents/$LABEL_PREFIX.$f.plist"
done
```

The label prefix must match the file name: launchd expects the file to be
called `<label>.plist`.

## Where the clone may live

Not under `~/Documents`, not under `~/Desktop`, not in a cloud-synchronized
folder — this applies above all to the data directory, which the jobs write to
and from which they call the scripts: TCC denies the launchd process access
there, and the export aborts with a permission error that looks like a
program bug. `~/Developer` and `~/Library/Application Support` are safe.
`install.sh` checks both paths and reports a risky location.

## Name collision for rtk

`rtk` in this context is the token proxy with the command `rtk gain`. There is
a second tool of the same name, `reachingforthejack/rtk` (Rust Type Kit). If
that one is on the path, the export appears to run through, and the mix-up
only shows in the dashboard as an empty RTK tab. Check beforehand:

```bash
which rtk
rtk gain      # must show a savings statistic, not a type error
```

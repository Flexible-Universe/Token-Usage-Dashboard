#!/usr/bin/env python3
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
"""Sets up the dashboard on macOS, Linux and Windows.

Two modes, chosen by the presence of RELEASE.json next to this file:

- From a repository clone the application stays where it is; the
  scheduled jobs are created only with --with-jobs.
- From an unpacked release ZIP the application is copied to --app-dir,
  the jobs are created unless --no-jobs is given, and a start script with
  the pinned interpreter is written.

In both modes the export scripts are copied to <data>/bin and the jobs call
those copies, not the source: a work in progress must not take the nightly
export down with it.

The jobs get the absolute paths of the interpreter, ccusage and rtk that
this run found. A scheduler starts with its own sparse PATH; pinning makes
the job decide exactly as the installer did.

User-facing output stays German like the rest of the installer chain.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform as platform_module
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

# Must run before any import that needs 3.11; the version table in the
# versions section (MINIMA) names the same minimum for display.
if sys.version_info < (3, 11):
    sys.exit("Fehler: Python %d.%d ist zu alt, gebraucht wird 3.11 oder neuer."
             % sys.version_info[:2])

SOURCE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE_DIR / "export"))
import exportlib  # noqa: E402

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"
PLATFORM = "windows" if IS_WINDOWS else "macos" if IS_MACOS else "linux"

EXPORT_SCRIPTS = ("ccusage-export.py", "rtk-export.py", "exportlib.py",
                  "ccusage-check.py", "ccusage-merge.py", "rtk-merge.py",
                  "export-status.py")
SUBDIRS = ("bin", "logs", "projects", "sessions", "blocks", "rtk", "status")
DATA_GLOBS = ("*.json", "projects/*.json", "sessions/*.json", "blocks/*.json", "rtk/*.json")

PRODUCT = "Token-Usage-Dashboard"


# --- jobs -----------------------------------------------------------------

@dataclass(frozen=True)
class Schedule:
    hour: int
    minute: int
    weekday: int | None = None   # 0 = Sunday, as launchd and cron count
    day: int | None = None


@dataclass(frozen=True)
class Job:
    name: str          # ccusage-daily, ...
    log_name: str      # name part of the scheduler's own log files
    script: str
    mode: str | None
    schedule: Schedule


JOBS = (
    Job("ccusage-daily", "daily", "ccusage-export.py", "daily", Schedule(4, 0)),
    Job("rtk-daily", "rtk-daily", "rtk-export.py", None, Schedule(4, 15)),
    Job("ccusage-weekly", "weekly", "ccusage-export.py", "weekly", Schedule(4, 30, weekday=0)),
    Job("ccusage-monthly", "monthly", "ccusage-export.py", "monthly", Schedule(5, 0, day=1)),
)


@dataclass
class Context:
    data_dir: Path
    python: list[str]                  # interpreter for the jobs, maybe with arguments
    ccusage: str | None
    rtk: str | None
    prefix: str
    dry_run: bool
    out: "Output"

    def command(self, job: Job) -> list[str]:
        args = [*self.python, str(self.data_dir / "bin" / job.script)]
        if job.mode:
            args.append(job.mode)
        args += ["--data-dir", str(self.data_dir)]
        if job.script == "ccusage-export.py" and self.ccusage:
            args += ["--ccusage-bin", self.ccusage]
        if job.script == "rtk-export.py" and self.rtk:
            args += ["--rtk-bin", self.rtk]
        return args


# --- output ---------------------------------------------------------------

@dataclass
class Output:
    notes: list[str] = field(default_factory=list)

    def step(self, text: str) -> None:
        print(f"\n== {text}")

    def did(self, text: str) -> None:
        print(f"  {text}")

    def would(self, text: str) -> None:
        print(f"  [Trockenlauf] {text}")

    def note(self, text: str) -> None:
        # Collected again at the end, so a skipped step does not get lost
        # in the running output.
        self.notes.append(text)
        print(f"  Hinweis: {text}")


class InstallError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


# --- versions -------------------------------------------------------------

# The one place for the minimum versions: a comparison tuple and exactly one
# display text per component. Table, failure text and docs show only the
# display text, never a number formatted from the tuple.
MINIMA = {
    "Python": ((3, 11, 0), "3.11"),
    "macOS": ((14, 0, 0), "14"),
    "Node.js": ((22, 0, 0), "22"),
    "ccusage": ((20, 0, 16), "20.0.16"),
    "rtk": ((0, 7, 1), "0.7.1"),
}
REQUIRED = {"Python": "ja", "macOS": "fuer ccusage", "Node.js": "fuer ccusage",
            "ccusage": "fuer Live-Daten", "rtk": "nein"}
INSTALL_HINTS = {
    "Python": "https://www.python.org/downloads/",
    "macOS": "Systemaktualisierung",
    "Node.js": "https://nodejs.org",
    "ccusage": "npm install -g ccusage@latest",
    "rtk": "rtk aktualisieren",
}
VERSION_TIMEOUT = 10

OK, TOO_OLD, UNREADABLE, MISSING = "passt", "zu alt", "nicht lesbar", "fehlt"
OTHER_PROGRAM, NOT_NEEDED = "anderes Programm", "nicht noetig"

_VERSION_RE = re.compile(r"\d+(?:\.\d+){0,2}")


@dataclass(frozen=True)
class VersionRow:
    component: str
    required: str
    minimum: str
    found: str
    result: str


def parse_version(text: str) -> tuple[int, int, int] | None:
    # A pre-release suffix is ignored on purpose: only the numbers compare.
    match = _VERSION_RE.search(text or "")
    if not match:
        return None
    parts = [int(part) for part in match.group(0).split(".")]
    return tuple(parts + [0] * (3 - len(parts)))  # type: ignore[return-value]


def read_version(cmd: list[str], env: dict[str, str]) -> str | None:
    """Single gate to the version calls; tests replace it."""
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=VERSION_TIMEOUT, env=env,
                                **exportlib.child_kwargs())
        if result.returncode != 0:
            return None
        return (result.stdout.decode("utf-8").strip()
                or result.stderr.decode("utf-8").strip())
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None


def _judge(component: str, output: str | None) -> tuple[str, str]:
    """Return (found text, result) for one program's version output."""
    parsed = parse_version(output) if output else None
    if parsed is None:
        return "-", UNREADABLE
    found = _VERSION_RE.search(output).group(0)
    return found, OK if parsed >= MINIMA[component][0] else TOO_OLD


def _row(component: str, found: str, result: str) -> VersionRow:
    return VersionRow(component, REQUIRED[component], MINIMA[component][1], found, result)


def evaluate(ccusage: str | None, rtk: str | None, env: dict[str, str], demo: bool,
             platform: str = PLATFORM, python: tuple | None = None,
             mac: str | None = None) -> list[VersionRow]:
    python = python or tuple(sys.version_info[:3])
    py_found, py_result = _judge("Python", ".".join(str(n) for n in python))
    rows = [_row("Python", py_found, py_result)]

    def not_needed(component: str) -> VersionRow:
        return _row(component, "-", NOT_NEEDED)

    live = bool(ccusage) and not demo
    if platform == "macos":
        if live:
            rows.append(_row("macOS", *_judge("macOS", mac or platform_module.mac_ver()[0])))
        else:
            rows.append(not_needed("macOS"))

    if not live:
        rows.append(not_needed("Node.js"))
        rows.append(not_needed("ccusage") if demo else _row("ccusage", "-", MISSING))
    else:
        # Same lookup as the export job: the node beside ccusage first, then
        # the PATH handed in (not this process's own).
        ccusage_dir = os.path.dirname(ccusage)
        job_env = dict(env)
        job_env["PATH"] = ccusage_dir + os.pathsep + env.get("PATH", "")
        node = (shutil.which("node", path=ccusage_dir)
                or shutil.which("node", path=env.get("PATH", "")))
        if node is None:
            rows.append(_row("Node.js", "-", MISSING))
        else:
            rows.append(_row("Node.js", *_judge("Node.js", read_version([node, "--version"],
                                                                         job_env))))
        rows.append(_row("ccusage", *_judge("ccusage", read_version([ccusage, "--version"],
                                                                    job_env))))

    if demo:
        rows.append(not_needed("rtk"))
    elif rtk is None:
        rows.append(_row("rtk", "-", MISSING))
    elif not probe_rtk(rtk):
        rows.append(_row("rtk", "-", OTHER_PROGRAM))
    else:
        rows.append(_row("rtk", *_judge("rtk", read_version([rtk, "--version"], env))))
    return rows


def blocking(rows: list[VersionRow]) -> list[VersionRow]:
    # A missing ccusage or rtk never blocks (one of them suffices; both
    # missing is the demo dialog's business). Node can only read as missing
    # when ccusage was found, and then the job could not run.
    return [row for row in rows
            if row.result in (TOO_OLD, UNREADABLE)
            or (row.result == MISSING and row.component == "Node.js")]


def _grid(header: list[str], body: list[list[str]]) -> list[str]:
    widths = [max(len(line[i]) for line in [header] + body) for i in range(len(header))]
    def fmt(line: list[str]) -> str:
        return "  " + "  ".join(cell.ljust(width) for cell, width in zip(line, widths)).rstrip()
    return [fmt(header), fmt(["-" * width for width in widths])] + [fmt(line) for line in body]


def render_table(rows: list[VersionRow]) -> str:
    header = ["Komponente", "Pflicht", "Mindestens", "Gefunden", "Ergebnis"]
    body = [[r.component, r.required, r.minimum, r.found, r.result] for r in rows]
    return "\n".join(_grid(header, body))


_COUNT_WORDS = {1: "Eine Komponente passt", 2: "Zwei Komponenten passen",
                3: "Drei Komponenten passen", 4: "Vier Komponenten passen"}


def render_failure(rows: list[VersionRow]) -> str:
    bad = blocking(rows)
    good = [row for row in rows if row.result == OK]
    lead = _COUNT_WORDS.get(len(bad), f"{len(bad)} Komponenten passen")
    lines = [f"{lead} nicht. Installation abgebrochen.", "  Passt nicht:"]
    name_w = max(len(r.component) for r in bad)
    found_texts = [f"gefunden {r.found}," if r.result == TOO_OLD else f"{r.result}," for r in bad]
    found_w = max(len(text) for text in found_texts)
    need_texts = [f"gebraucht ab {r.minimum}" for r in bad]
    need_w = max(len(text) for text in need_texts)
    for row, found_text, need_text in zip(bad, found_texts, need_texts):
        lines.append(f"    {row.component.ljust(name_w)}  {found_text.ljust(found_w)}  "
                     f"{need_text.ljust(need_w)}  ({INSTALL_HINTS[row.component]})")
    if good:
        lines.append("  Passt:")
        lines.append("    " + ", ".join(f"{r.component} {r.found}" for r in good))
    return "\n".join(lines)


def run_command(cmd: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    """Single gate to the scheduler tools; tests replace it."""
    # schtasks answers in the console code page; a German umlaut must not
    # crash the installer.
    return subprocess.run(cmd, input=input_text, capture_output=True, text=True,
                          errors="replace")


def _checked(cmd: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
    try:
        result = run_command(cmd, input_text)
    except OSError as error:
        raise InstallError(f"{cmd[0]} konnte nicht gestartet werden: {error}")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise InstallError(f"{' '.join(cmd)} schlug fehl (Exitcode {result.returncode}): {detail}")
    return result


# --- schedulers -----------------------------------------------------------

class Scheduler:
    name = ""
    title = ""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def ident(self, job: Job) -> str:
        return f"{self.ctx.prefix}.{job.name}"

    def install(self, job: Job) -> None:
        raise NotImplementedError

    def remove(self, job: Job) -> None:
        raise NotImplementedError

    def exists(self, job: Job) -> bool:
        raise NotImplementedError

    def finish(self) -> None:
        """Called once after all jobs were installed or removed."""

    def notes(self) -> list[str]:
        return []


class Launchd(Scheduler):
    name = "launchd"
    title = "launchd-Jobs"

    @staticmethod
    def agents_dir() -> Path:
        return Path.home() / "Library" / "LaunchAgents"

    def path(self, job: Job) -> Path:
        return self.agents_dir() / f"{self.ident(job)}.plist"

    def render(self, job: Job) -> bytes:
        data = str(self.ctx.data_dir)
        interval: dict = {"Hour": job.schedule.hour, "Minute": job.schedule.minute}
        if job.schedule.weekday is not None:
            interval["Weekday"] = job.schedule.weekday
        if job.schedule.day is not None:
            interval["Day"] = job.schedule.day
        plist = {
            # launchd expects the file to be called <Label>.plist.
            "Label": self.ident(job),
            "ProgramArguments": self.ctx.command(job),
            "ProcessType": "Background",
            "RunAtLoad": False,
            "StartCalendarInterval": interval,
            "StandardOutPath": f"{data}/logs/launchd-{job.log_name}.out",
            "StandardErrorPath": f"{data}/logs/launchd-{job.log_name}.err",
            "WorkingDirectory": data,
        }
        return plistlib.dumps(plist)

    def _loaded(self, job: Job) -> bool:
        return run_command(["launchctl", "list", self.ident(job)]).returncode == 0

    def install(self, job: Job) -> None:
        target = self.path(job)
        out = self.ctx.out
        # A loaded job holds on to the old version: unload, write, load.
        if self.ctx.dry_run:
            out.would(f"schreiben: {target}")
            out.would(f"  Aufruf:   {shlex.join(self.ctx.command(job))}")
            out.would(f"laden: {self.ident(job)}")
            return
        if self._loaded(job):
            run_command(["launchctl", "unload", str(target)])
            out.did(f"entladen: {self.ident(job)}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.render(job))
        _checked(["launchctl", "load", str(target)])
        out.did(f"eingerichtet und geladen: {self.ident(job)}")

    def remove(self, job: Job) -> None:
        target = self.path(job)
        if not target.exists():
            return
        if self.ctx.dry_run:
            self.ctx.out.would(f"entladen und loeschen: {target}")
            return
        run_command(["launchctl", "unload", str(target)])
        target.unlink()
        self.ctx.out.did(f"entfernt: {self.ident(job)}")

    def exists(self, job: Job) -> bool:
        return self.path(job).exists()


def _systemd_quote(value: str) -> str:
    # systemd expands %-specifiers and $-variables even inside quotes.
    escaped = (value.replace("\\", "\\\\").replace('"', '\\"')
               .replace("%", "%%").replace("$", "$$"))
    return f'"{escaped}"'


class Systemd(Scheduler):
    name = "systemd"
    title = "systemd-Timer"
    WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

    def __init__(self, ctx: Context):
        super().__init__(ctx)
        self._pending: list[str] = []
        self._removed = False

    @staticmethod
    def unit_dir() -> Path:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(base) / "systemd" / "user"

    def ident(self, job: Job) -> str:
        return f"{self.ctx.prefix}-{job.name}"

    def on_calendar(self, job: Job) -> str:
        s = job.schedule
        clock = f"{s.hour:02d}:{s.minute:02d}:00"
        if s.weekday is not None:
            return f"{self.WEEKDAYS[s.weekday]} *-*-* {clock}"
        if s.day is not None:
            return f"*-*-{s.day:02d} {clock}"
        return f"*-*-* {clock}"

    def render_service(self, job: Job) -> str:
        data = str(self.ctx.data_dir)
        command = " ".join(_systemd_quote(part) for part in self.ctx.command(job))
        log = f"{data}/logs/systemd-{job.log_name}"
        return (
            "[Unit]\n"
            f"Description={PRODUCT}: {job.name}\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            # These keys take the rest of the line verbatim, without quotes;
            # only %-specifiers are expanded.
            f"WorkingDirectory={data.replace('%', '%%')}\n"
            f"ExecStart={command}\n"
            f"StandardOutput=append:{log.replace('%', '%%')}.out\n"
            f"StandardError=append:{log.replace('%', '%%')}.err\n"
        )

    def render_timer(self, job: Job) -> str:
        # Persistent=true runs a start that was missed while the machine was
        # off at the next boot or login; cron cannot do that.
        return (
            "[Unit]\n"
            f"Description={PRODUCT}: {job.name} (Zeitplan)\n\n"
            "[Timer]\n"
            f"OnCalendar={self.on_calendar(job)}\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )

    def paths(self, job: Job) -> tuple[Path, Path]:
        # Not with_suffix: a prefix with a dot (com.example) would lose the job name.
        base = self.unit_dir() / self.ident(job)
        return base.with_name(base.name + ".service"), base.with_name(base.name + ".timer")

    def install(self, job: Job) -> None:
        service, timer = self.paths(job)
        if self.ctx.dry_run:
            self.ctx.out.would(f"schreiben: {service}")
            self.ctx.out.would(f"schreiben: {timer}  ({self.on_calendar(job)})")
            self.ctx.out.would(f"  Aufruf:   {shlex.join(self.ctx.command(job))}")
            return
        service.parent.mkdir(parents=True, exist_ok=True)
        service.write_text(self.render_service(job), encoding="utf-8")
        timer.write_text(self.render_timer(job), encoding="utf-8")
        self.ctx.out.did(f"geschrieben: {timer.name}")
        self._pending.append(timer.name)

    def remove(self, job: Job) -> None:
        service, timer = self.paths(job)
        if not (service.exists() or timer.exists()):
            return
        if self.ctx.dry_run:
            self.ctx.out.would(f"abschalten und loeschen: {timer.name}")
            return
        run_command(["systemctl", "--user", "disable", "--now", timer.name])
        for path in (service, timer):
            if path.exists():
                path.unlink()
        self._removed = True
        self.ctx.out.did(f"entfernt: {self.ident(job)}")

    def exists(self, job: Job) -> bool:
        return self.paths(job)[1].exists()

    def finish(self) -> None:
        if self.ctx.dry_run:
            return
        if self._pending or self._removed:
            _checked(["systemctl", "--user", "daemon-reload"])
        if self._pending:
            _checked(["systemctl", "--user", "enable", "--now", *self._pending])
            self.ctx.out.did("Timer aktiviert: " + ", ".join(self._pending))

    def notes(self) -> list[str]:
        return ["systemd-User-Timer laufen nur, solange der Benutzer angemeldet ist; "
                "verpasste Laeufe holt Persistent=true bei der naechsten Anmeldung nach. "
                "Fuer Laeufe ohne Anmeldung: loginctl enable-linger"]

    @staticmethod
    def available() -> bool:
        if not shutil.which("systemctl"):
            return False
        try:
            return run_command(["systemctl", "--user", "show-environment"]).returncode == 0
        except OSError:
            return False


class Cron(Scheduler):
    name = "cron"
    title = "cron-Eintraege"

    def __init__(self, ctx: Context):
        super().__init__(ctx)
        self._jobs: list[Job] = []
        self._touched = False

    def markers(self) -> tuple[str, str]:
        return (f"# >>> {PRODUCT} {self.ctx.prefix} >>>",
                f"# <<< {PRODUCT} {self.ctx.prefix} <<<")

    def line(self, job: Job) -> str:
        s = job.schedule
        dow = "*" if s.weekday is None else str(s.weekday)
        dom = "*" if s.day is None else str(s.day)
        log = shlex.quote(f"{self.ctx.data_dir}/logs/cron-{job.log_name}.out")
        command = f"{shlex.join(self.ctx.command(job))} >>{log} 2>&1"
        # An unescaped % ends the command in a crontab line.
        return f"{s.minute} {s.hour} {dom} * {dow} " + command.replace("%", "\\%")

    def current(self) -> str:
        try:
            result = run_command(["crontab", "-l"])
        except OSError as error:
            raise InstallError(f"crontab konnte nicht gestartet werden: {error}")
        if result.returncode == 0:
            return result.stdout
        # Only "no crontab for <user>" means empty. Any other failure must not
        # lead to the user's crontab being replaced by ours.
        if "no crontab" in (result.stderr or "").lower():
            return ""
        raise InstallError(f"crontab -l schlug fehl: {(result.stderr or '').strip()}")

    def merged(self, existing: str, jobs: list[Job]) -> str:
        begin, end = self.markers()
        kept, inside = [], False
        for line in existing.splitlines():
            if line == begin:
                inside = True
            elif line == end:
                inside = False
            elif not inside:
                kept.append(line)
        if jobs:
            kept += [begin, *(self.line(job) for job in jobs), end]
        return "\n".join(kept) + "\n" if kept else ""

    def install(self, job: Job) -> None:
        self._jobs.append(job)
        self._touched = True
        if self.ctx.dry_run:
            self.ctx.out.would(f"cron-Zeile: {self.line(job)}")

    def remove(self, job: Job) -> None:
        self._touched = True

    def exists(self, job: Job) -> bool:
        begin, end = self.markers()
        text = self.current()
        if begin not in text:
            return False
        block = text.split(begin, 1)[1].split(end, 1)[0]
        return any(f"/{job.script}" in line and (job.mode is None or f" {job.mode} " in line)
                   for line in block.splitlines())

    def finish(self) -> None:
        if not self._touched or self.ctx.dry_run:
            return
        existing = self.current()
        wanted = self.merged(existing, self._jobs)
        if wanted == existing:
            return
        _checked(["crontab", "-"], wanted)
        if self._jobs:
            self.ctx.out.did(f"crontab aktualisiert: {len(self._jobs)} Eintraege")
        else:
            self.ctx.out.did("crontab: Eintraege entfernt")

    def notes(self) -> list[str]:
        return ["cron holt Laeufe nicht nach, die bei ausgeschaltetem Rechner faellig waren. "
                "Den Wochenlauf nach laengerer Pause von Hand starten.",
                "Der cron-Dienst muss laufen; unter WSL ohne systemd startet er nicht von "
                "selbst (sudo service cron start)."]


class Schtasks(Scheduler):
    name = "schtasks"
    title = "Aufgabenplanung"
    WEEKDAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
    MONTHS = ("January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December")

    def ident(self, job: Job) -> str:
        return f"\\{self.ctx.prefix}\\{job.name}"

    def render(self, job: Job) -> str:
        s = job.schedule
        start = f"{date.today().isoformat()}T{s.hour:02d}:{s.minute:02d}:00"
        if s.weekday is not None:
            schedule = ("<ScheduleByWeek><DaysOfWeek><%s /></DaysOfWeek>"
                        "<WeeksInterval>1</WeeksInterval></ScheduleByWeek>"
                        % self.WEEKDAYS[s.weekday])
        elif s.day is not None:
            months = "".join(f"<{m} />" for m in self.MONTHS)
            schedule = (f"<ScheduleByMonth><DaysOfMonth><Day>{s.day}</Day></DaysOfMonth>"
                        f"<Months>{months}</Months></ScheduleByMonth>")
        else:
            schedule = "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
        command, *args = self.ctx.command(job)
        e = xml_escape
        # StartWhenAvailable runs a start that was missed while the machine
        # was off as soon as it is back. InteractiveToken needs no stored
        # password; the job runs while the user is logged on. Without UserId
        # the task belongs to the registering user, which also works for
        # Entra ID accounts whose DOMAIN\name does not resolve.
        return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{e(PRODUCT)}: {e(job.name)}</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      {schedule}
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{e(command)}</Command>
      <Arguments>{e(subprocess.list2cmdline(args))}</Arguments>
      <WorkingDirectory>{e(str(self.ctx.data_dir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

    def install(self, job: Job) -> None:
        if self.ctx.dry_run:
            self.ctx.out.would(f"Aufgabe anlegen: {self.ident(job)}")
            self.ctx.out.would(f"  Aufruf:   {subprocess.list2cmdline(self.ctx.command(job))}")
            return
        xml_path = self.ctx.data_dir / "logs" / f"task-{job.name}.xml"
        # schtasks reads the task definition as UTF-16 with BOM.
        xml_path.write_text(self.render(job), encoding="utf-16")
        try:
            _checked(["schtasks", "/Create", "/TN", self.ident(job), "/XML", str(xml_path), "/F"])
        finally:
            xml_path.unlink(missing_ok=True)
        self.ctx.out.did(f"eingerichtet: {self.ident(job)}")

    def remove(self, job: Job) -> None:
        if not self.exists(job):
            return
        if self.ctx.dry_run:
            self.ctx.out.would(f"Aufgabe loeschen: {self.ident(job)}")
            return
        _checked(["schtasks", "/Delete", "/TN", self.ident(job), "/F"])
        self.ctx.out.did(f"entfernt: {self.ident(job)}")

    def exists(self, job: Job) -> bool:
        return run_command(["schtasks", "/Query", "/TN", self.ident(job)]).returncode == 0

    def notes(self) -> list[str]:
        return ["Die Aufgaben laufen nur, solange der Benutzer angemeldet ist; "
                "verpasste Laeufe holt die Aufgabenplanung nach (StartWhenAvailable)."]


SCHEDULERS = {cls.name: cls for cls in (Launchd, Systemd, Cron, Schtasks)}


def pick_scheduler(choice: str) -> str:
    if choice != "auto":
        return choice
    if IS_WINDOWS:
        return "schtasks"
    if IS_MACOS:
        return "launchd"
    if Systemd.available():
        return "systemd"
    if shutil.which("crontab"):
        return "cron"
    raise InstallError("Weder systemd (systemctl --user) noch crontab ist verfuegbar. "
                       "Ohne Planer mit --no-jobs installieren und die Exporte von Hand starten.", 2)


def default_prefix(scheduler: str) -> str:
    if scheduler == "launchd":
        return f"com.{getpass.getuser()}"
    if scheduler == "schtasks":
        return PRODUCT
    return PRODUCT.lower()


# --- environment ----------------------------------------------------------

def default_app_dir() -> Path:
    home = Path.home()
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return Path(base) / "Programs" / PRODUCT
    if IS_MACOS:
        return home / "Library" / "Application Support" / PRODUCT
    base = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return Path(base) / PRODUCT.lower()


def _python_ok(cmd: list[str]) -> bool:
    try:
        return run_command([*cmd, "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"]
                           ).returncode == 0
    except OSError:
        return False


def job_python() -> list[str]:
    """Interpreter for the jobs and the start script.

    Prefer a name that survives upgrades: /opt/homebrew/bin/python3 follows
    Homebrew, while sys.executable may name a versioned Cellar path. On
    Windows pythonw.exe, so that no console window opens at night.
    """
    if IS_WINDOWS:
        # The py launcher picks the newest installed Python at every start,
        # so removing an old version does not break the tasks.
        launcher, windowless_launcher = shutil.which("py"), shutil.which("pyw")
        if launcher and windowless_launcher and _python_ok([launcher, "-3"]):
            return [windowless_launcher, "-3"]
        here = Path(sys.executable)
        windowless = here.with_name("pythonw.exe")
        return [str(windowless if windowless.exists() else here)]
    found = shutil.which("python3")
    if found and _python_ok([found]):
        return [found]
    return [sys.executable]


def console_python() -> list[str]:
    """Interpreter for the start script, which should show its console."""
    if IS_WINDOWS:
        launcher = shutil.which("py")
        if launcher and _python_ok([launcher, "-3"]):
            return [launcher, "-3"]
        here = Path(sys.executable).with_name("python.exe")
        return [str(here if here.exists() else sys.executable)]
    return job_python()


def probe_rtk(path: str) -> bool:
    """The name collides with Rust Type Kit; only the JSON answer counts."""
    try:
        result = subprocess.run([path, "gain", "--format", "json"], capture_output=True,
                                timeout=60)
        json.loads(result.stdout.decode("utf-8"))
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError, ValueError):
        return False
    return result.returncode == 0


def risky_location(path: Path) -> bool:
    text = str(path)
    home = str(Path.home())
    if "/Dropbox/" in text.replace("\\", "/") + "/":
        return True
    if IS_MACOS:
        return (text.startswith(home + "/Documents/") or text.startswith(home + "/Desktop/")
                or "/Library/Mobile Documents/" in text)
    if IS_WINDOWS:
        for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            base = os.environ.get(var)
            if base and text.lower().startswith(base.lower().rstrip("\\") + "\\"):
                return True
    return False


def expand(path: str) -> Path:
    return Path(os.path.expandvars(path)).expanduser()


# --- steps ----------------------------------------------------------------

def copy_file(source: Path, target: Path, *, force: bool, dry_run: bool, out: Output,
              label: str, executable: bool = False) -> None:
    if not source.is_file():
        raise InstallError(f"{source} fehlt. Ist das Paket vollstaendig?")
    if target.exists() and target.read_bytes() == source.read_bytes():
        out.did(f"unveraendert: {label}")
        return
    if target.exists() and not force:
        out.note(f"{label} unter {target.parent} weicht von der Quelle ab und bleibt stehen. "
                 f"Mit --force ueberschreiben.")
        return
    verb = "ueberschreiben" if target.exists() else "kopieren"
    if dry_run:
        out.would(f"{verb}: {label}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if executable and not IS_WINDOWS:
        target.chmod(0o755)
    out.did(("ueberschrieben: " if verb == "ueberschreiben" else "kopiert: ") + label)


def write_config(app_dir: Path, data_dir: Path, dry_run: bool, out: Output) -> None:
    import tomllib
    config = app_dir / "config.toml"
    template = SOURCE_DIR / "config.example.toml"
    if config.exists():
        out.did(f"vorhanden, bleibt unveraendert: {config}")
        try:
            with config.open("rb") as handle:
                current = tomllib.load(handle).get("data", {}).get("directory", "")
        except (OSError, tomllib.TOMLDecodeError) as error:
            out.note(f"{config} ist nicht lesbar: {error}")
            return
        if expand(str(current)) != data_dir:
            out.note(f'In der config.toml steht directory = "{current}", eingerichtet wurde '
                     f"aber {data_dir}. Eines von beiden anpassen.")
        return
    if not template.is_file():
        raise InstallError(f"{template} fehlt. Ist das Paket vollstaendig?")
    if dry_run:
        out.would(f"anlegen aus config.example.toml mit directory = \"{data_dir}\"")
        return
    lines, replaced = [], False
    for line in template.read_text(encoding="utf-8").splitlines(keepends=True):
        if not replaced and line.lstrip().startswith("directory"):
            indent = line[: len(line) - len(line.lstrip())]
            lines.append(f"{indent}directory = {json.dumps(str(data_dir), ensure_ascii=False)}\n")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        raise InstallError("config.example.toml enthaelt keine directory-Zeile.")
    app_dir.mkdir(parents=True, exist_ok=True)
    config.write_text("".join(lines), encoding="utf-8")
    out.did(f"angelegt mit directory = \"{data_dir}\"")


def release_manifest() -> dict | None:
    path = SOURCE_DIR / "RELEASE.json"
    if not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise InstallError(f"RELEASE.json ist unlesbar: {error}")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise InstallError("RELEASE.json hat keine Dateiliste.")
    return manifest


def write_launcher(app_dir: Path, dry_run: bool, out: Output) -> Path:
    python = console_python()
    if IS_WINDOWS:
        target = app_dir / "start-dashboard.cmd"
        command = " ".join(f'"{part}"' if " " in part or not part.startswith("-") else part
                           for part in python)
        # cmd.exe reads a batch file in the console code page; chcp first, so
        # that a user name with an umlaut in the path survives.
        text = ('@echo off\r\n'
                'chcp 65001 >nul\r\n'
                'rem Startet das Token-Usage-Dashboard. Angelegt von install.py.\r\n'
                'cd /d "%~dp0"\r\n'
                f'{command} app.py %*\r\n'
                'if errorlevel 1 pause\r\n')
    else:
        target = app_dir / "start-dashboard.sh"
        text = ('#!/bin/sh\n'
                '# Startet das Token-Usage-Dashboard. Angelegt von install.py.\n'
                'cd "$(dirname "$0")" || exit 1\n'
                f'exec {shlex.join(python)} app.py "$@"\n')
    if dry_run:
        out.would(f"Startskript anlegen: {target}")
        return target
    target.write_text(text, encoding="utf-8", newline="")
    if not IS_WINDOWS:
        target.chmod(0o755)
    out.did(f"Startskript: {target}")
    return target


# --- main -----------------------------------------------------------------

def parse_args(argv: list[str], release: bool) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Richtet das Token-Usage-Dashboard ein: Datenverzeichnis, "
                    "Exportskripte, config.toml und die zeitgesteuerten Exportjobs.",
        epilog="Beispiele:\n"
               "  install.py\n"
               "  install.py --demo\n"
               "  install.py --with-jobs --dry-run\n"
               "  install.py --remove-jobs",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    jobs = parser.add_mutually_exclusive_group()
    jobs.add_argument("--with-jobs", action="store_true",
                      help="Exportjobs einrichten (Vorgabe nur beim Release-Paket).")
    jobs.add_argument("--with-launchagents", action="store_true", dest="with_jobs_alias",
                      help="Alter Name von --with-jobs.")
    jobs.add_argument("--no-jobs", action="store_true", help="Keine Exportjobs einrichten.")
    jobs.add_argument("--remove-jobs", action="store_true",
                      help="Die eingerichteten Exportjobs entfernen und beenden. Daten bleiben.")
    parser.add_argument("--scheduler", default="auto",
                        choices=("auto", *SCHEDULERS),
                        help="Planer. Vorgabe: launchd (macOS), schtasks (Windows), "
                             "systemd oder ersatzweise cron (Linux).")
    parser.add_argument("--label-prefix", metavar="NAME",
                        help="Praefix der Jobnamen, etwa com.beispiel. Nur mit Jobs.")
    parser.add_argument("--data-dir", metavar="PFAD",
                        help=f"Datenverzeichnis. Vorgabe: {exportlib.default_data_dir()}")
    parser.add_argument("--app-dir", metavar="PFAD",
                        help="Zielverzeichnis der Anwendung (nur Release-Paket). "
                             f"Vorgabe: {default_app_dir()}")
    parser.add_argument("--force", action="store_true",
                        help="Ueberschreibt abweichende Exportskripte unter <daten>/bin.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Zeigt nur, was geschehen wuerde. Aendert nichts.")
    parser.add_argument("--demo", action="store_true",
                        help="Demo-Modus mit Beispieldaten, ohne ccusage und rtk.")
    parser.add_argument("--no-first-export", action="store_true",
                        help="Den ersten Export am Ende der Einrichtung auslassen.")
    args = parser.parse_args(argv)
    args.with_jobs = args.with_jobs or args.with_jobs_alias
    if args.app_dir and not release:
        parser.error("--app-dir gibt es nur beim Release-Paket; aus dem Repository "
                     "laeuft die Anwendung an Ort und Stelle.")
    args.jobs = (args.with_jobs or (release and not args.no_jobs)) and not args.remove_jobs
    if args.label_prefix and not (args.jobs or args.remove_jobs):
        parser.error("--label-prefix wirkt nur zusammen mit --with-jobs (--with-launchagents).")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(sys.argv[1:] if argv is None else argv)
    except InstallError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return error.code
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return 130


def _main(argv: list[str]) -> int:
    manifest = release_manifest()
    release = manifest is not None
    args = parse_args(argv, release)
    out = Output()

    if release and manifest.get("platform") != PLATFORM:
        raise InstallError(f"Dieses Paket ist fuer {manifest.get('platform')}, hier laeuft "
                           f"{PLATFORM}. Bitte das passende ZIP verwenden.", 2)

    data_dir = expand(args.data_dir) if args.data_dir else exportlib.default_data_dir()
    data_dir = data_dir.absolute()
    app_dir = (expand(args.app_dir).absolute() if args.app_dir else default_app_dir()) \
        if release else SOURCE_DIR
    if args.remove_jobs:
        return remove_jobs(args.scheduler, args.label_prefix, data_dir, args.dry_run, out)
    scheduler_error = None
    try:
        scheduler_name = pick_scheduler(args.scheduler)
    except InstallError as error:
        # Raised only once jobs are really set up: demo mode, which the
        # dialog below may still switch on, skips them. Without jobs the
        # scheduler only serves the leftover check below.
        scheduler_error = error
        scheduler_name = "cron"
    prefix = args.label_prefix or default_prefix(scheduler_name)

    print("Token-Usage-Dashboard einrichten")
    print(f"  System:            {PLATFORM}")
    print(f"  Quelle:            {SOURCE_DIR}")
    print(f"  Anwendung:         {app_dir}")
    print(f"  Datenverzeichnis:  {data_dir}")
    if args.jobs and scheduler_error:
        print("  Exportjobs:        ja, aber kein Planer gefunden")
    elif args.jobs:
        print(f"  Exportjobs:        ja, {scheduler_name}, Praefix {prefix}")
    else:
        print("  Exportjobs:        nein")
    if args.dry_run:
        print("  Trockenlauf:       es wird nichts geaendert")

    # --- requirements
    out.step("Voraussetzungen")
    if IS_WINDOWS and "WindowsApps" in sys.executable:
        out.note("Python aus dem Microsoft Store leitet Schreibzugriffe unter AppData in einen "
                 "privaten Paketordner um; Anwendung und Daten landen dann nicht dort, wo sie "
                 "angezeigt werden. Besser Python von python.org oder per winget installieren.")
    live = 0
    ccusage = exportlib.find_binary("ccusage", "CCUSAGE_BIN", exportlib.ccusage_search_dirs())
    if ccusage:
        out.did(f"ccusage gefunden: {ccusage}")
        live += 1
    else:
        out.note("ccusage wurde nicht gefunden. Installation: npm install -g ccusage "
                 "(braucht Node.js). Danach die Installation wiederholen. Das Dashboard "
                 "laeuft trotzdem und zeigt, was schon im Datenverzeichnis liegt.")
    rtk = exportlib.find_binary("rtk", "RTK_BIN", exportlib.rtk_search_dirs())
    rtk_ok = False
    if rtk:
        if probe_rtk(rtk):
            out.did(f"rtk gefunden: {rtk}")
            rtk_ok = True
            live += 1
        else:
            out.note(f"rtk gefunden ({rtk}), liefert aber kein JSON (gain --format json). "
                     "Vermutlich ein anderes Programm gleichen Namens. rtk/ und der Job "
                     "rtk-daily werden nicht eingerichtet.")
            rtk = None
    else:
        out.note("rtk wurde nicht gefunden (RTK_BIN, feste Verzeichnisse, PATH). rtk/ und der "
                 "Job rtk-daily werden nicht eingerichtet. Nach der Installation von rtk die "
                 "Installation erneut aufrufen.")

    demo = args.demo
    if live == 0:
        print("\n  Fuer Live-Daten muss mindestens eines der Programme ccusage oder RTK installiert sein.")
        if demo:
            out.did("Demo-Modus aktiviert (--demo).")
        else:
            while True:
                print("  [a] Installation abbrechen  [d] Demo-Modus aktivieren: ", end="", flush=True)
                answer = sys.stdin.readline()
                if not answer:
                    raise InstallError("Keine Auswahl moeglich. Installation abgebrochen; fuer "
                                       "den Demo-Modus erneut mit --demo aufrufen.", 2)
                answer = answer.strip().lower()
                if answer == "a":
                    raise InstallError("Installation auf Wunsch abgebrochen.", 2)
                if answer == "d":
                    demo = True
                    out.did("Demo-Modus aktiviert.")
                    break
                print("  Bitte a oder d eingeben.")

    # The table comes before any write, so a mismatch aborts a clean system
    # (dry run included) and the reader sees every row before the abort.
    rows = evaluate(ccusage, rtk, dict(os.environ), demo)
    print()
    print(render_table(rows))
    if blocking(rows):
        raise InstallError(render_failure(rows), 2)

    jobs_wanted = args.jobs
    if demo and jobs_wanted:
        out.note("Exportjobs werden im Demo-Modus uebersprungen, weil Demo-Daten keine "
                 "Live-Exporte brauchen.")
        jobs_wanted = False
    if jobs_wanted and scheduler_error:
        raise scheduler_error
    if jobs_wanted and scheduler_name == "launchd" and not IS_MACOS:
        raise InstallError(f"launchd gibt es nur auf macOS; hier laeuft {PLATFORM}.", 2)
    if jobs_wanted and scheduler_name == "schtasks" and not IS_WINDOWS:
        raise InstallError(f"Die Aufgabenplanung gibt es nur unter Windows; hier laeuft {PLATFORM}.", 2)
    if jobs_wanted and scheduler_name in ("systemd", "cron") and IS_WINDOWS:
        raise InstallError(f"{scheduler_name} gibt es unter Windows nicht.", 2)

    if demo:
        for pattern in DATA_GLOBS:
            if any(path.is_file() for path in data_dir.glob(pattern)):
                raise InstallError(f"Demo-Modus abgebrochen: In {data_dir} liegen bereits "
                                   "Datendateien. Bitte ein leeres --data-dir verwenden.")

    # A synchronised folder is the error that later disguises itself as a
    # permission error of the scheduled process and looks like a bug.
    for path in {app_dir, data_dir}:
        if risky_location(path):
            out.note(f"{path} liegt in einem synchronisierten oder geschuetzten Ordner. Der "
                     "naechtliche Export kann dort mit einem Rechtefehler abbrechen.")

    # --- application (release only)
    if release:
        out.step(f"Anwendung nach {app_dir}")
        if app_dir.resolve() == SOURCE_DIR:
            out.did("Paket liegt bereits am Zielort, nichts zu kopieren.")
        else:
            for name in manifest["files"]:
                # The application is replaced as a whole; only config.toml,
                # which the package never contains, is the user's.
                copy_file(SOURCE_DIR / name, app_dir / name, force=True,
                          dry_run=args.dry_run, out=out, label=name,
                          executable=name.endswith((".py", ".sh")))

    # --- data directory
    out.step("Datenverzeichnis")
    for sub in ("", *SUBDIRS):
        # In demo mode status/ is missing on purpose: only a missing directory
        # gives "no status" in the dashboard; an empty one would show every
        # job as never logged.
        if demo and sub == "status":
            continue
        # rtk/ only exists with a working rtk (or demo data filling it): an
        # existing directory makes the dashboard expect rtk exports.
        if sub == "rtk" and not rtk_ok and not demo:
            continue
        target = data_dir / sub if sub else data_dir
        if target.is_dir():
            out.did(f"vorhanden: {sub or '.'}")
        elif args.dry_run:
            out.would(f"anlegen: {target}")
        else:
            target.mkdir(parents=True, exist_ok=True)
            out.did(f"angelegt: {target}")

    # --- leftovers of an install without rtk; nothing is deleted
    scheduler = SCHEDULERS[scheduler_name](Context(
        data_dir, job_python(), ccusage, rtk, prefix, args.dry_run, out))
    if not rtk_ok and not demo:
        rtk_empty = (data_dir / "rtk").is_dir() and not any((data_dir / "rtk").glob("????-??.json"))
        rtk_job = _safe_exists(scheduler, _job("rtk-daily"))
        if rtk_empty or rtk_job:
            out.note(f"Fruehere Installation ohne rtk: Bitte von Hand aufraeumen, sonst meldet "
                     f"das Dashboard dauerhaft einen rtk-Exportfehler. Das leere Verzeichnis "
                     f"{data_dir / 'rtk'} und die Dateien status/rtk.*.json entfernen und den Job "
                     f"rtk-daily ({scheduler.ident(_job('rtk-daily'))}) loeschen. Es wird nichts "
                     f"automatisch geloescht.")

    if demo:
        out.step("Demo-Daten")
        if args.dry_run:
            out.would(f"Demo-Daten erzeugen: {data_dir}")
        else:
            result = subprocess.run([sys.executable, str(SOURCE_DIR / "tools" / "make-sample-data.py"),
                                     "--out", str(data_dir)], capture_output=True, text=True)
            if result.returncode != 0:
                raise InstallError(f"Demo-Daten nicht erzeugt: {result.stderr.strip()}")
            out.did(f"Demo-Daten erzeugt: {data_dir}")

    # --- export scripts
    out.step(f"Exportskripte nach {data_dir / 'bin'}")
    for name in EXPORT_SCRIPTS:
        # A release brings a consistent new set; mixing old and new copies
        # would be worse than replacing local edits, which --force does too.
        copy_file(SOURCE_DIR / "export" / name, data_dir / "bin" / name,
                  force=args.force or release, dry_run=args.dry_run, out=out, label=name,
                  executable=name.endswith("-export.py"))

    stale = [name for name in ("ccusage-export.sh", "rtk-export.sh")
             if (data_dir / "bin" / name).exists()]
    if stale:
        out.note(f"Veraltete Exportskripte unter {data_dir / 'bin'}: {', '.join(stale)}. Die Jobs "
                 "rufen jetzt die Python-Fassungen auf; die alten Dateien koennen geloescht werden.")

    out.step("config.toml")
    write_config(app_dir, data_dir, args.dry_run, out)

    out.step(scheduler.title)
    if jobs_wanted:
        for job in JOBS:
            if job.name == "rtk-daily" and not rtk_ok:
                out.note("Job rtk-daily wird nicht eingerichtet, weil kein funktionierendes rtk "
                         "gefunden wurde.")
                continue
            scheduler.install(job)
        scheduler.finish()
        for text in scheduler.notes():
            out.note(text)
    else:
        out.did("uebersprungen." + ("" if release else " Mit --with-jobs einrichten."))

    if not (demo or args.dry_run or args.no_first_export) and (ccusage or rtk_ok):
        first_export(data_dir, ccusage, rtk if rtk_ok else None, out)

    launcher = None
    if release:
        out.step("Startskript")
        launcher = write_launcher(app_dir, args.dry_run, out)

    out.step("Ergebnis")
    if out.notes:
        print(f"  {len(out.notes)} Hinweis(e):")
        for text in out.notes:
            print(f"   - {text}")
    else:
        out.did("keine Hinweise.")

    if args.dry_run:
        print("\nTrockenlauf beendet, es wurde nichts geaendert.")
    elif launcher:
        print(f"\nFertig. Starten mit:\n  {launcher}")
    elif IS_WINDOWS:
        print(f'\nFertig. Starten mit:\n  cd /d "{app_dir}" && py -3 app.py')
    else:
        print(f"\nFertig. Starten mit:\n  cd {shlex.quote(str(app_dir))} && python3 app.py")
    return 0


def first_export(data_dir: Path, ccusage: str | None, rtk: str | None, out: Output) -> None:
    """Runs the exports once, so the dashboard has data before the first night.

    Without a monthly file the dashboard refuses to start; a fresh install
    would otherwise look broken until 04:00.
    """
    out.step("Erster Export")
    runs = []
    if ccusage:
        for mode in ("daily", "weekly"):
            runs.append((f"ccusage {mode}", ["ccusage-export.py", mode, "--ccusage-bin", ccusage]))
    if rtk:
        runs.append(("rtk", ["rtk-export.py", "--rtk-bin", rtk]))
    for label, (script, *rest) in runs:
        cmd = [sys.executable, str(data_dir / "bin" / script), *rest, "--data-dir", str(data_dir)]
        try:
            ok = subprocess.run(cmd, capture_output=True, timeout=600).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if ok:
            out.did(f"{label}: ok")
        else:
            out.note(f"Erster Export {label} fehlgeschlagen; Einzelheiten unter "
                     f"{data_dir / 'logs'}. Der geplante Job versucht es erneut.")


def _job(name: str) -> Job:
    return next(job for job in JOBS if job.name == name)


def _safe_exists(scheduler: Scheduler, job: Job) -> bool:
    try:
        return scheduler.exists(job)
    except (OSError, InstallError):
        return False


def remove_jobs(choice: str, prefix: str | None, data_dir: Path, dry_run: bool,
                out: Output) -> int:
    if choice != "auto":
        names = [choice]
    elif IS_WINDOWS:
        names = ["schtasks"]
    elif IS_MACOS:
        names = ["launchd"]
    else:
        # The systemd session may be unreachable now although the timers
        # were installed through it, or the other way round: clean up both.
        names = [name for name, usable in (("systemd", Systemd.available()),
                                           ("cron", bool(shutil.which("crontab")))) if usable]
    for name in names:
        name_prefix = prefix or default_prefix(name)
        scheduler = SCHEDULERS[name](Context(
            data_dir, [sys.executable], None, None, name_prefix, dry_run, out))
        out.step(f"{scheduler.title} entfernen (Praefix {name_prefix})")
        for job in JOBS:
            scheduler.remove(job)
        scheduler.finish()
    out.did("Das Datenverzeichnis bleibt unberuehrt.")
    if dry_run:
        print("\nTrockenlauf beendet, es wurde nichts geaendert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

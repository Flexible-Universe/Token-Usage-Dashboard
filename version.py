"""Running version of the dashboard, read from files only.

Sources in order: RELEASE.json (release ZIP), CHANGELOG.md plus the commit
from .git (clone). No program is called: the commit comes from the files
under .git, so the lookup also works where git is not installed.
"""
import json
import re
from pathlib import Path

# Official SemVer 2.0.0 expression.
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*)?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?$"
)
_HEADING_RE = re.compile(r"^## \[([^\]]+)\](?:\s+-\s+(\d{4}-\d{2}-\d{2}))?\s*$")
_HASH_RE = re.compile(r"^[0-9a-f]{40}$")
SHORT_HASH_LENGTH = 7


def is_semver(text: str) -> bool:
    return bool(_SEMVER_RE.match(text))


def changelog_versions(text: str) -> list[tuple[str, str | None, bool]]:
    """(name, date or None, has_content) per `## [x]` heading, in order."""
    entries: list[list] = []
    for line in text.splitlines():
        if line.startswith("## "):
            match = _HEADING_RE.match(line)
            if match:
                entries.append([match.group(1), match.group(2), False])
            else:
                # A heading of another shape still ends the previous section.
                entries.append(None)
        elif entries and entries[-1] is not None and line.strip():
            entries[-1][2] = True
    return [tuple(entry) for entry in entries if entry is not None]


def latest_release(text: str) -> str | None:
    for name, _date, _content in changelog_versions(text):
        if is_semver(name):
            return name
    return None


def release_version(text: str) -> str:
    """Top numbered version for the release build.

    Raises ValueError (German text, printed by the builder) if [Unreleased]
    still holds entries or no numbered version exists.
    """
    for name, _date, has_content in changelog_versions(text):
        if name.lower() == "unreleased" and has_content:
            raise ValueError(
                "CHANGELOG.md: [Unreleased] enthaelt noch Eintraege; "
                "vor dem Release in eine Version verschieben."
            )
    version = latest_release(text)
    if version is None:
        raise ValueError("CHANGELOG.md enthaelt keine nummerierte Version.")
    return version


def _git_dir(root: Path) -> Path | None:
    dot_git = root / ".git"
    if dot_git.is_dir():
        return dot_git
    if not dot_git.is_file():
        return None
    first = dot_git.read_text(encoding="utf-8").strip()
    if not first.startswith("gitdir:"):
        raise ValueError(".git ist weder Verzeichnis noch gitdir-Verweis")
    target = Path(first[len("gitdir:"):].strip())
    if not target.is_absolute():
        target = root / target
    if not target.is_dir():
        raise ValueError(f"gitdir zeigt ins Leere: {target}")
    return target


def _resolve_ref(git_dir: Path, common: Path, ref: str) -> str:
    # Worktrees keep HEAD privately but refs in the common directory.
    for base in (git_dir, common):
        path = base / ref
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if _HASH_RE.match(value):
                return value
            raise ValueError(f"Ref {ref} enthaelt keinen gueltigen Hash")
    packed = common / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            if not line or line[0] in "#^":
                continue
            value, _, name = line.partition(" ")
            if name.strip() == ref and _HASH_RE.match(value):
                return value
    raise ValueError(f"Ref {ref} nicht aufloesbar")


def read_commit(root: Path) -> str | None:
    """Short hash of HEAD, None without .git; ValueError if unresolvable."""
    git_dir = _git_dir(root)
    if git_dir is None:
        return None
    head_file = git_dir / "HEAD"
    if not head_file.is_file():
        raise ValueError("HEAD fehlt")
    head = head_file.read_text(encoding="utf-8").strip()
    common = git_dir
    common_file = git_dir / "commondir"
    if common_file.is_file():
        common = git_dir / common_file.read_text(encoding="utf-8").strip()
    if head.startswith("ref:"):
        head = _resolve_ref(git_dir, common, head[len("ref:"):].strip())
    if not _HASH_RE.match(head):
        raise ValueError("HEAD enthaelt keinen gueltigen Hash")
    return head[:SHORT_HASH_LENGTH]


def _from_manifest(path: Path) -> tuple[dict, list[str]]:
    info = {"version": None, "release": True, "commit": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return info, [f"RELEASE.json nicht lesbar: {exc}"]
    value = data.get("version") if isinstance(data, dict) else None
    if not isinstance(value, str) or not value:
        return info, ["RELEASE.json enthaelt keine Version als Text"]
    info["version"] = value
    return info, []


def detect(root: Path) -> tuple[dict, list[str]]:
    """({"version": str|None, "release": bool, "commit": str|None},
    warnings) - warnings are German lines for stderr."""
    manifest = root / "RELEASE.json"
    if manifest.is_file():
        # No fallback to the changelog: a damaged release must not
        # pose as a clone with a guessed number.
        return _from_manifest(manifest)
    info = {"version": None, "release": False, "commit": None}
    warnings: list[str] = []
    try:
        text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        info["version"] = latest_release(text)
        if info["version"] is None:
            warnings.append("CHANGELOG.md enthaelt keine nummerierte Version")
    except (OSError, ValueError) as exc:
        warnings.append(f"CHANGELOG.md nicht lesbar: {exc}")
    try:
        info["commit"] = read_commit(root)
    except (OSError, ValueError) as exc:
        warnings.append(f"Commit nicht ermittelbar: {exc}")
    return info, warnings

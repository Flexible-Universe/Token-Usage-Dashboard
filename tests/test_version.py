"""Tests for version.py: manifest, changelog and git files, no subprocess."""
import json
import re
import tempfile
import unittest
from pathlib import Path

import version

BASE_DIR = Path(__file__).resolve().parent.parent
HASH = "0123456789abcdef0123456789abcdef01234567"
HASH2 = "fedcba9876543210fedcba9876543210fedcba98"

CHANGELOG = """# Changelog

## [Unreleased]

## [1.2.0] - 2026-10-12

### Added

- Something.

## [1.1.0-rc.1+build.5] - 2026-10-01

- Older.
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class ChangelogTests(unittest.TestCase):
    def test_versions_in_order_with_date_and_content(self):
        self.assertEqual(
            version.changelog_versions(CHANGELOG),
            [("Unreleased", None, False),
             ("1.2.0", "2026-10-12", True),
             ("1.1.0-rc.1+build.5", "2026-10-01", True)],
        )

    def test_unreleased_with_content(self):
        text = "## [Unreleased]\n\n### Added\n\n- x\n\n## [1.0.0] - 2026-01-01\n"
        self.assertTrue(version.changelog_versions(text)[0][2])

    def test_latest_release_skips_unreleased(self):
        self.assertEqual(version.latest_release(CHANGELOG), "1.2.0")

    def test_latest_release_none(self):
        self.assertIsNone(version.latest_release("## [Unreleased]\n- x\n"))

    def test_release_version_empty_unreleased(self):
        self.assertEqual(version.release_version(CHANGELOG), "1.2.0")

    def test_release_version_without_unreleased(self):
        self.assertEqual(
            version.release_version("## [2.0.0] - 2026-01-01\n"), "2.0.0")

    def test_release_version_filled_unreleased_raises(self):
        text = "## [Unreleased]\n\n- x\n\n## [1.0.0] - 2026-01-01\n"
        with self.assertRaises(ValueError):
            version.release_version(text)

    def test_release_version_without_number_raises(self):
        with self.assertRaises(ValueError):
            version.release_version("## [Unreleased]\n")

    def test_is_semver(self):
        for good in ("1.0.0", "0.0.1", "1.0.0-alpha.1", "1.0.0+b.1",
                     "1.0.0-rc.1+b.1"):
            self.assertTrue(version.is_semver(good), good)
        for bad in ("1.0", "01.0.0", "1.0.0-", "v1.0.0", "Unreleased", ""):
            self.assertFalse(version.is_semver(bad), bad)


class ReadCommitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_no_git(self):
        self.assertIsNone(version.read_commit(self.root))

    def test_detached_head(self):
        write(self.root / ".git" / "HEAD", HASH + "\n")
        self.assertEqual(version.read_commit(self.root), HASH[:7])

    def test_ref_file(self):
        write(self.root / ".git" / "HEAD", "ref: refs/heads/main\n")
        write(self.root / ".git" / "refs" / "heads" / "main", HASH + "\n")
        self.assertEqual(version.read_commit(self.root), HASH[:7])

    def test_packed_refs(self):
        write(self.root / ".git" / "HEAD", "ref: refs/heads/main\n")
        write(self.root / ".git" / "packed-refs",
              "# pack-refs\n"
              f"{HASH2} refs/heads/other\n"
              f"{HASH} refs/heads/main\n"
              f"^{HASH2}\n")
        self.assertEqual(version.read_commit(self.root), HASH[:7])

    def test_gitdir_file_relative_with_commondir(self):
        common = self.root / "main" / ".git"
        gitdir = common / "worktrees" / "wt"
        write(common / "refs" / "heads" / "feat", HASH + "\n")
        write(gitdir / "HEAD", "ref: refs/heads/feat\n")
        write(gitdir / "commondir", "../..\n")
        write(self.root / "wt" / ".git",
              "gitdir: ../main/.git/worktrees/wt\n")
        self.assertEqual(version.read_commit(self.root / "wt"), HASH[:7])

    def test_unresolvable_head_raises(self):
        write(self.root / ".git" / "HEAD", "ref: refs/heads/missing\n")
        with self.assertRaises(ValueError):
            version.read_commit(self.root)


class DetectTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_release_manifest_wins(self):
        write(self.root / "RELEASE.json", json.dumps({"version": "1.4.0"}))
        write(self.root / "CHANGELOG.md", CHANGELOG)
        write(self.root / ".git" / "HEAD", HASH)
        info, warnings = version.detect(self.root)
        self.assertEqual(
            info, {"version": "1.4.0", "release": True, "commit": None})
        self.assertEqual(warnings, [])

    def test_broken_manifests(self):
        for content in ("{not json", "[]", json.dumps({"version": 3}),
                        json.dumps({})):
            write(self.root / "RELEASE.json", content)
            write(self.root / "CHANGELOG.md", CHANGELOG)
            info, warnings = version.detect(self.root)
            self.assertEqual(
                info, {"version": None, "release": True, "commit": None},
                content)
            self.assertEqual(len(warnings), 1, content)

    def test_clone_with_git(self):
        write(self.root / "CHANGELOG.md", CHANGELOG)
        write(self.root / ".git" / "HEAD", HASH)
        info, warnings = version.detect(self.root)
        self.assertEqual(
            info, {"version": "1.2.0", "release": False, "commit": HASH[:7]})
        self.assertEqual(warnings, [])

    def test_clone_without_git_has_no_warning(self):
        write(self.root / "CHANGELOG.md", CHANGELOG)
        info, warnings = version.detect(self.root)
        self.assertEqual(
            info, {"version": "1.2.0", "release": False, "commit": None})
        self.assertEqual(warnings, [])

    def test_unresolvable_head_warns(self):
        write(self.root / "CHANGELOG.md", CHANGELOG)
        write(self.root / ".git" / "HEAD", "ref: refs/heads/nowhere\n")
        info, warnings = version.detect(self.root)
        self.assertIsNone(info["commit"])
        self.assertEqual(info["version"], "1.2.0")
        self.assertEqual(len(warnings), 1)

    def test_gitdir_pointing_nowhere_warns(self):
        write(self.root / "CHANGELOG.md", CHANGELOG)
        write(self.root / ".git", "gitdir: ./gone\n")
        info, warnings = version.detect(self.root)
        self.assertIsNone(info["commit"])
        self.assertEqual(len(warnings), 1)

    def test_invalid_detached_hash_warns(self):
        write(self.root / "CHANGELOG.md", CHANGELOG)
        write(self.root / ".git" / "HEAD", "zzzz\n")
        info, warnings = version.detect(self.root)
        self.assertIsNone(info["commit"])
        self.assertEqual(len(warnings), 1)

    def test_missing_changelog_warns(self):
        info, warnings = version.detect(self.root)
        self.assertEqual(
            info, {"version": None, "release": False, "commit": None})
        self.assertEqual(len(warnings), 1)

    def test_changelog_without_number_warns(self):
        write(self.root / "CHANGELOG.md", "## [Unreleased]\n")
        info, warnings = version.detect(self.root)
        self.assertIsNone(info["version"])
        self.assertEqual(len(warnings), 1)

    def test_no_subprocess_import(self):
        source = (BASE_DIR / "version.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)


class RealChangelogTests(unittest.TestCase):
    def test_headings_are_well_formed_and_descending(self):
        text = (BASE_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
        entries = version.changelog_versions(text)
        self.assertTrue(entries)
        numbers = []
        for index, (name, date, _content) in enumerate(entries):
            if name == "Unreleased":
                self.assertEqual(index, 0)
                self.assertIsNone(date)
                continue
            self.assertTrue(version.is_semver(name), name)
            self.assertRegex(date or "", r"^\d{4}-\d{2}-\d{2}$")
            numbers.append(tuple(
                int(p) for p in re.split(r"[-+]", name)[0].split(".")))
        self.assertEqual(numbers, sorted(numbers, reverse=True))


if __name__ == "__main__":
    unittest.main()

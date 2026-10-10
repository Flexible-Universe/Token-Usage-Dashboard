"""The minimum versions in install.py and in the docs must not drift apart.

The installer holds the display text of each minimum (install.MINIMA). The
docs repeat it by hand; this test compares line by line, so a number that
happens to appear elsewhere in the file cannot satisfy it.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest

from tests.helpers import BASE_DIR

_spec = importlib.util.spec_from_file_location("install_under_test", BASE_DIR / "install.py")
install = importlib.util.module_from_spec(_spec)
# dataclasses look the module up by name while the class is created.
sys.modules[_spec.name] = install
_spec.loader.exec_module(install)

INSTALL_DOC = BASE_DIR / "docs" / "07-installation.md"
README = BASE_DIR / "README.md"

# Start of the table row that carries each component's minimum.
DOC_ROW = {
    "Python": "| Python |",
    "Node.js": "| Node.js",
    "ccusage": "| `ccusage`",
    "rtk": "| `rtk`",
    "macOS": "| macOS |",
}
# The README has no operating-system table; macOS sits in a sentence.
README_ROW = {**DOC_ROW, "macOS": "macOS 14"}


def _lines(path, start, contains=False):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln for ln in lines if (start in ln if contains else ln.startswith(start))]


class MinimaInDocsTests(unittest.TestCase):
    def test_every_component_is_covered(self):
        self.assertEqual(set(install.MINIMA), set(DOC_ROW))

    def test_minima_match_installation_doc(self):
        for component, (_, text) in install.MINIMA.items():
            with self.subTest(component=component):
                hits = _lines(INSTALL_DOC, DOC_ROW[component])
                self.assertEqual(len(hits), 1, f"row for {component}")
                self.assertIn(text, hits[0])

    def test_minima_match_readme(self):
        for component, (_, text) in install.MINIMA.items():
            with self.subTest(component=component):
                hits = _lines(README, README_ROW[component], contains=component == "macOS")
                self.assertEqual(len(hits), 1, f"row for {component}")
                self.assertIn(text, hits[0])


if __name__ == "__main__":
    unittest.main()

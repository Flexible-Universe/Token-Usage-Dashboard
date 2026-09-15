"""Runs the dependency-free JavaScript regression tests."""

import shutil
import subprocess
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is not installed")
class FrontendTests(unittest.TestCase):
    def test_filter_flow(self):
        result = subprocess.run(
            [NODE, "--test", str(BASE_DIR / "tests" / "frontend-filter.test.js")],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

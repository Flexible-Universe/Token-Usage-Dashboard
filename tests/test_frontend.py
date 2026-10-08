"""Runs the dependency-free JavaScript regression tests."""

import glob
import shutil
import subprocess
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is not installed")
class FrontendTests(unittest.TestCase):
    def test_node_suites(self):
        test_files = sorted(glob.glob(str(BASE_DIR / "tests" / "*.test.js")))
        self.assertTrue(test_files, "No test files found matching tests/*.test.js")
        result = subprocess.run(
            [NODE, "--test"] + test_files,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

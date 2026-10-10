"""Tests for the installer starters install.sh and install.cmd."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_stub

BASE_DIR = Path(__file__).resolve().parent.parent

OLD_PYTHON = (
    "import sys\n"
    "if '--version' in sys.argv:\n"
    "    print('Python 3.9.6')\n"
    "    sys.exit(0)\n"
    "sys.exit(1)\n"
)


class StarterTooOldTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    @unittest.skipIf(os.name == "nt", "install.sh is the POSIX starter")
    def test_sh_names_the_version_of_a_too_old_python(self):
        # A private bin directory instead of /usr/bin:/bin, which holds a real
        # python3 on Linux and would let the starter succeed.
        bindir = self.tmp / "bin"
        bindir.mkdir()
        # Tools install.sh needs outside the shell builtins.
        for tool in ("dirname",):
            found = shutil.which(tool)
            self.assertIsNotNone(found)
            (bindir / tool).symlink_to(found)
        make_stub(bindir, "python3", OLD_PYTHON)
        result = subprocess.run(
            ["/bin/sh", str(BASE_DIR / "install.sh"), "--help"],
            capture_output=True, text=True,
            env={"PATH": str(bindir)},
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("3.9.6", result.stderr)
        self.assertIn("python3", result.stderr)

    @unittest.skipUnless(os.name == "nt", "install.cmd is the Windows starter")
    def test_cmd_names_the_version_of_a_too_old_python(self):
        bindir = self.tmp / "bin"
        make_stub(bindir, "python", OLD_PYTHON)
        # No %SystemRoot% itself: py.exe lives there. System32 supplies find.
        system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        result = subprocess.run(
            ["cmd.exe", "/c", str(BASE_DIR / "install.cmd"), "--help"],
            capture_output=True, text=True,
            env={"PATH": os.pathsep.join([str(bindir), str(system32)]),
                 "SystemRoot": str(system32.parent)},
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("3.9.6", result.stderr)


if __name__ == "__main__":
    unittest.main()

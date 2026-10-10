"""The data directory default exists twice; both copies must agree."""

from __future__ import annotations

import sys
import tomllib
import unittest
from pathlib import Path

from tests.helpers import BASE_DIR

import loader

sys.path.insert(0, str(BASE_DIR / "export"))
import exportlib  # noqa: E402


class DefaultDataDirectoryTests(unittest.TestCase):
    def test_loader_and_export_chain_agree(self):
        self.assertEqual(Path(loader.default_data_directory()).expanduser(),
                         exportlib.default_data_dir())

    def test_default_config_text_parses_back_to_the_default(self):
        parsed = tomllib.loads(loader.DEFAULT_CONFIG_TEXT)
        self.assertEqual(parsed["data"]["directory"], loader.default_data_directory())

    def test_windows_path_survives_toml(self):
        path = r"C:\Users\Anna Muster\AppData\Local\Claude-Code-Usage"
        parsed = tomllib.loads(f"directory = {loader.toml_string(path)}\n")
        self.assertEqual(parsed["directory"], path)

    def test_quote_in_path_survives_toml(self):
        path = '/home/a"b/data'
        parsed = tomllib.loads(f"directory = {loader.toml_string(path)}\n")
        self.assertEqual(parsed["directory"], path)


if __name__ == "__main__":
    unittest.main()

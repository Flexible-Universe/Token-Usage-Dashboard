"""Tests for the message catalogues under static/i18n/.

The catalogues are data, not code: everything to the right of
"window.I18N.<code> =" up to the closing semicolon is valid JSON, so these
tests read them with json.loads instead of parsing JavaScript. Keeping
that property is part of the catalogue format.
"""
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

import app
import insights
import loader
import sources

BASE_DIR = Path(__file__).resolve().parent.parent
I18N_DIR = BASE_DIR / "static" / "i18n"
INDEX_HTML = BASE_DIR / "static" / "index.html"

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)(?::([a-z0-9]+))?\}")
KNOWN_FORMATS = {None, "int", "cost", "cost4", "date", "list"}


def read_catalog(code: str) -> dict:
    text = (I18N_DIR / f"{code}.js").read_text(encoding="utf-8")
    start = text.index("window.I18N." + code + " =") + len("window.I18N." + code + " =")
    end = text.rindex(";")
    return json.loads(text[start:end])


def placeholders(sentence: str) -> set[tuple[str, str | None]]:
    return {(m.group(1), m.group(2)) for m in PLACEHOLDER_RE.finditer(sentence)}


class DataI18nParser(HTMLParser):
    """Collects every i18n key referenced from index.html."""

    def __init__(self):
        super().__init__()
        self.keys: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("data-i18n", "data-i18n-title", "data-i18n-aria") and value:
                self.keys.add(value)


LANGUAGES = sorted(p.stem for p in I18N_DIR.glob("*.js"))


class CatalogParityTests(unittest.TestCase):
    def setUp(self):
        self.catalogs = {code: read_catalog(code) for code in LANGUAGES}

    def test_mindestens_zwei_sprachen(self):
        self.assertGreaterEqual(len(self.catalogs), 2)

    def test_jede_sprache_nennt_locale_und_label(self):
        for code, cat in self.catalogs.items():
            with self.subTest(lang=code):
                self.assertTrue(cat["locale"])
                self.assertTrue(cat["label"])

    def test_gleiche_schluesselmenge(self):
        reference = set(self.catalogs["de"]["strings"])
        for code, cat in self.catalogs.items():
            with self.subTest(lang=code):
                self.assertEqual(set(cat["strings"]), reference)

    def test_zwoelf_monatsnamen_je_sprache(self):
        for code, cat in self.catalogs.items():
            with self.subTest(lang=code):
                self.assertEqual(len(cat["months"]), 12)

    def test_gleiche_platzhalter_je_schluessel(self):
        reference = self.catalogs["de"]["strings"]
        for code, cat in self.catalogs.items():
            if code == "de":
                continue
            for key, sentence in reference.items():
                with self.subTest(lang=code, key=key):
                    self.assertEqual(
                        placeholders(cat["strings"][key]), placeholders(sentence),
                        "Gleicher Wert einmal als int und einmal als cost "
                        "hiesse, dass die Sprachen verschiedene Zahlen zeigen.")

    def test_nur_bekannte_formatangaben(self):
        for code, cat in self.catalogs.items():
            for key, sentence in cat["strings"].items():
                for name, spec in placeholders(sentence):
                    with self.subTest(lang=code, key=key, placeholder=name):
                        self.assertIn(spec, KNOWN_FORMATS)

    def test_projektionsbasis_steht_im_katalog(self):
        for code, cat in self.catalogs.items():
            with self.subTest(lang=code):
                self.assertIn("ui.projection.basis", cat["strings"])


class MessageCodeCompletenessTests(unittest.TestCase):
    """Every code the backend can emit exists in every catalogue.

    Without this test a new backend message would only show up in the
    browser, as <check.neu>.
    """

    MODULES = (loader, sources, insights, app)

    def setUp(self):
        self.catalogs = {code: read_catalog(code) for code in LANGUAGES}

    def test_jeder_code_steht_in_jedem_katalog(self):
        for module in self.MODULES:
            for code in module.MESSAGE_CODES:
                for lang, cat in self.catalogs.items():
                    with self.subTest(module=module.__name__, code=code, lang=lang):
                        self.assertIn(code, cat["strings"])

    def test_die_konstante_veraltet_nicht(self):
        """Every key literally used in a module is listed in MESSAGE_CODES."""
        for module in self.MODULES:
            source = Path(module.__file__).read_text(encoding="utf-8")
            used = set(re.findall(r'"code":\s*"([a-z0-9_.]+)"', source))
            used |= set(re.findall(r'_error_json\(\s*\d+,\s*"([a-z0-9_.]+)"', source))
            used |= set(re.findall(r'note_code = "([a-z0-9_.]+)"', source))
            with self.subTest(module=module.__name__):
                self.assertEqual(used - set(module.MESSAGE_CODES), set())

    def test_die_konstante_nennt_nichts_erfundenes(self):
        for module in self.MODULES:
            source = Path(module.__file__).read_text(encoding="utf-8")
            for code in module.MESSAGE_CODES:
                with self.subTest(module=module.__name__, code=code):
                    self.assertIn('"' + code + '"', source)


class StaticLabelTests(unittest.TestCase):
    def test_jeder_data_i18n_schluessel_steht_in_jedem_katalog(self):
        parser = DataI18nParser()
        parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
        self.assertTrue(parser.keys, "index.html traegt keine data-i18n-Attribute.")
        for code in LANGUAGES:
            strings = read_catalog(code)["strings"]
            for key in sorted(parser.keys):
                with self.subTest(lang=code, key=key):
                    self.assertIn(key, strings)


if __name__ == "__main__":
    unittest.main()

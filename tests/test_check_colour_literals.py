# SPDX-License-Identifier: AGPL-3.0-or-later
"""The colour-literal ratchet (scripts/check_colour_literals.py) fails on a new
pre-Deep-Water colour, passes on a fall, and skips the map identity palette.

Plain unittest with temporary directories: no database, so it runs in any job.
"""

import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_colour_literals", REPO / "scripts" / "check_colour_literals.py")
ccl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ccl)


class ColourLiteralRatchetTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.baseline = {"static/css/map.css": {"#040608": 2}}
        self.write("static/css/map.css", "a { color: #040608; }\nb { color: #040608; }\n")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def check(self):
        return ccl.compare(ccl.scan(self.root), self.baseline)

    def test_the_baseline_itself_passes(self):
        failures, lowerable = self.check()
        self.assertEqual(failures, [])
        self.assertEqual(lowerable, [])

    def test_a_new_hit_in_a_new_file_fails(self):
        self.write("templates/page.html", '<div style="color:#8899AA">x</div>')
        failures, _ = self.check()
        self.assertEqual(len(failures), 1)
        self.assertIn("templates/page.html", failures[0])
        self.assertIn("no baseline", failures[0])

    def test_one_more_hit_in_a_baselined_file_fails(self):
        self.write("static/css/map.css", "a { color: #040608; }\nb { color: #040608; }\nc { color: #040608; }\n")
        failures, _ = self.check()
        self.assertEqual(len(failures), 1)
        self.assertIn("#040608 x3 (baseline 2)", failures[0])

    def test_a_new_value_in_a_baselined_file_fails(self):
        self.write("static/css/map.css", "a { color: #040608; }\nb { color: #040608; }\nc { color: #4d5e6f; }\n")
        failures, _ = self.check()
        self.assertEqual(len(failures), 1)
        self.assertIn("#4d5e6f x1 (baseline 0)", failures[0])

    def test_a_fall_passes_and_says_to_lower_the_baseline(self):
        self.write("static/css/map.css", "a { color: var(--color-base); }\nb { color: #040608; }\n")
        failures, lowerable = self.check()
        self.assertEqual(failures, [])
        self.assertEqual(len(lowerable), 1)
        self.assertIn("lower the baseline to 1", lowerable[0])

    def test_the_map_identity_palette_is_skipped(self):
        self.write("static/css/tokens.css", ":root {\n  --color-entity-dark: #040608;\n}\n")
        failures, _ = self.check()
        self.assertEqual(failures, [])

    def test_tests_docs_and_markdown_are_not_scanned(self):
        self.write("tests/test_x.py", "OLD = '#040608'")
        self.write("docs/palette.txt", "#8899aa")
        self.write("NOTES.md", "#e8edf4")
        failures, _ = self.check()
        self.assertEqual(failures, [])

    def test_main_exits_1_and_addresses_the_fixer(self):
        self.write("templates/page.html", "<p style='color:#e8edf4'>x</p>")
        out, err = io.StringIO(), io.StringIO()
        original = ccl.BASELINE
        ccl.BASELINE = self.baseline
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = ccl.main(["--root", str(self.root)])
        finally:
            ccl.BASELINE = original
        self.assertEqual(code, 1)
        self.assertIn("Paste this whole message to Claude", err.getvalue())
        self.assertIn("Never hardcode a colour", err.getvalue())

    def test_the_live_tree_passes(self):
        failures, _ = ccl.compare(ccl.scan(REPO), ccl.BASELINE)
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()

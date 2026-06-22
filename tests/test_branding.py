import io
import os
import re
import unittest
from unittest import mock

from manageroo.branding import (
    BTTLABS_LABEL,
    BTTLABS_URL,
    FULL_ACRONYM,
    FULL_NAME,
    PROJECT_DIR,
    PUBLIC_COMMAND,
    THINKING_LINE,
    TURTLE_ASCII,
    print_banner,
)


_ANSI_RE = re.compile(r"\033\]8;;[^\033]*\033\\|\033\[[0-9;]*m|\r")


class _TtyStringIO(io.StringIO):
    def isatty(self):
        return True


def _fixture(codes):
    return "".join(chr(code) for code in codes)


class BrandingTests(unittest.TestCase):
    def test_plain_banner_contains_project_manageroo_brand(self):
        stream = io.StringIO()
        print_banner(stream, animation=False)
        rendered = stream.getvalue()
        self.assertEqual(FULL_NAME, "Uncle Matt's Project Manageroo")
        self.assertEqual(FULL_ACRONYM, "MANAGEROO")
        self.assertEqual(PUBLIC_COMMAND, "manageroo")
        self.assertEqual(PROJECT_DIR, ".manageroo")
        self.assertIn(FULL_NAME, rendered)
        self.assertIn(THINKING_LINE, rendered)
        self.assertIn(TURTLE_ASCII, rendered)
        self.assertIn(BTTLABS_LABEL, rendered)
        self.assertNotIn("COMMAND: manageroo", rendered)
        self.assertNotIn("ACRONYM: MANAGEROO", rendered)
        self.assertNotIn("ONE BRIEF IN. CHECKED PATCH OUT.", rendered)
        self.assertNotIn(
            _fixture([83, 117, 112, 101, 114, 32, 77, 101, 103, 97, 32, 70, 111, 114, 119, 97, 114, 100, 32, 66, 117, 105, 108, 100]),
            rendered,
        )
        self.assertNotIn(_fixture([85, 77, 83, 77, 70, 66, 85, 82, 65, 83, 66, 79, 70, 69]), rendered)
        self.assertNotIn("\033[", rendered)

    def test_banner_box_edges_are_aligned(self):
        stream = io.StringIO()
        print_banner(stream, animation=False)
        box = [line for line in stream.getvalue().splitlines() if line.startswith(("╔", "║", "╚"))]
        self.assertEqual(len(box), 7)
        self.assertEqual(len({len(line) for line in box}), 1)
        for line in box[1:-1]:
            self.assertTrue(line.startswith("║"))
            self.assertTrue(line.endswith("║"))
        self.assertIn(THINKING_LINE, box[3])
        self.assertIn(TURTLE_ASCII, box[4])
        self.assertIn(BTTLABS_LABEL, box[5])

    def test_banner_box_lines_have_distinct_color_effects_when_color_is_available(self):
        stream = _TtyStringIO()
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False):
            os.environ.pop("NO_COLOR", None)
            print_banner(stream, animation=False)
        rendered = stream.getvalue()
        stripped = _ANSI_RE.sub("", rendered)
        self.assertIn("MANAGEROO", stripped)
        self.assertIn(FULL_NAME, stripped)
        self.assertIn(THINKING_LINE, stripped)
        self.assertIn(TURTLE_ASCII, stripped)
        self.assertIn(BTTLABS_LABEL, stripped)
        self.assertIn("\033[3m", rendered)
        self.assertIn(f"\033]8;;{BTTLABS_URL}\033\\", rendered)
        self.assertIn("\033[4m", rendered)
        self.assertGreaterEqual(rendered.count("\033[38;5;"), 30)

    def test_banner_thinking_line_animates_rainbow_when_animation_is_enabled(self):
        stream = _TtyStringIO()
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False):
            os.environ.pop("NO_COLOR", None)
            print_banner(stream, animation=True, delay=0)
        rendered = stream.getvalue()
        stripped = _ANSI_RE.sub("", rendered)
        self.assertIn("MANAGEROO", stripped)
        self.assertIn(FULL_NAME, stripped)
        self.assertIn(THINKING_LINE, stripped)
        self.assertIn(TURTLE_ASCII, stripped)
        self.assertIn(BTTLABS_LABEL, stripped)
        self.assertGreater(rendered.count("\r"), 3)

    def test_installer_banner_can_keep_effect_rows_moving(self):
        stream = _TtyStringIO()
        with (
            mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
            mock.patch("manageroo.branding._current_terminal_row", return_value=20),
        ):
            os.environ.pop("NO_COLOR", None)
            ticker = print_banner(stream, animation=True, delay=0, persistent_rainbow=True)
        self.assertIsNotNone(ticker)
        assert ticker is not None
        self.assertGreaterEqual(len(ticker.rows), 5)
        ticker.stop()


if __name__ == "__main__":
    unittest.main()

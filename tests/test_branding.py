import io
import unittest

from manageroo.branding import FULL_ACRONYM, FULL_NAME, PROJECT_DIR, PUBLIC_COMMAND, print_banner


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
        self.assertIn(FULL_NAME.upper(), rendered)
        self.assertIn("COMMAND: manageroo", rendered)
        self.assertIn("ACRONYM: MANAGEROO", rendered)
        self.assertNotIn(
            _fixture([83, 117, 112, 101, 114, 32, 77, 101, 103, 97, 32, 70, 111, 114, 119, 97, 114, 100, 32, 66, 117, 105, 108, 100]),
            rendered,
        )
        self.assertNotIn(_fixture([85, 77, 83, 77, 70, 66, 85, 82, 65, 83, 66, 79, 70, 69]), rendered)
        self.assertNotIn("".join(("bt", "tlabs.fun")), rendered)
        self.assertNotIn("\033[", rendered)


if __name__ == "__main__":
    unittest.main()

import io
import unittest

from umsmfburasbofe.branding import BRAND, EDITION_NAME, PRODUCT_NAME, print_banner


class BrandingTests(unittest.TestCase):
    def test_plain_banner_contains_complete_brand(self):
        stream = io.StringIO()
        print_banner(stream, animation=False)
        rendered = stream.getvalue()
        self.assertIn(PRODUCT_NAME.upper(), rendered)
        self.assertIn(EDITION_NAME.upper(), rendered)
        self.assertIn(BRAND, rendered)
        self.assertNotIn("\033[", rendered)


if __name__ == "__main__":
    unittest.main()

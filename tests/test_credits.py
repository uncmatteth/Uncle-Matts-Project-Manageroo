import unittest

from manageroo.credits import SUPER_TEAM, format_special_thanks


class CreditsTests(unittest.TestCase):
    def test_special_thanks_names_the_super_team(self):
        text = format_special_thanks()
        for name in ["Peter Yang", "Matthew Berman", "Garry Tan", "Abhigyan Patwari", "OpenClaw"]:
            self.assertIn(name, text)
        self.assertIn("Stats:", text)
        self.assertIn("local-agent super team", text)
        self.assertGreaterEqual(len(SUPER_TEAM), 6)


if __name__ == "__main__":
    unittest.main()

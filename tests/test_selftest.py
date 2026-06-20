import unittest

from umsmfburasbofe.selftest import run_self_test


class EndToEndTests(unittest.TestCase):
    def test_mock_one_shot(self):
        result = run_self_test()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["target_contents"], "UMSMFBURASBOFE deterministic fixture completed\n")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from umsmfburasbofe.errors import ValidationError
from umsmfburasbofe.review import validate_review_evidence


class ReviewTests(unittest.TestCase):
    def test_valid_finding(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
            review = {
                "findings": [{
                    "path": "a.py",
                    "start_line": 2,
                    "end_line": 2,
                    "quote": "two",
                    "blocking": True,
                }]
            }
            self.assertEqual(len(validate_review_evidence(review, repo)), 1)

    def test_bad_quote_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "a.py").write_text("one\ntwo\n", encoding="utf-8")
            review = {
                "findings": [{
                    "path": "a.py",
                    "start_line": 1,
                    "end_line": 1,
                    "quote": "not there",
                    "blocking": True,
                }]
            }
            with self.assertRaises(ValidationError):
                validate_review_evidence(review, repo)


if __name__ == "__main__":
    unittest.main()

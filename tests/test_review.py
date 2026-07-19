import tempfile
import unittest
from pathlib import Path

from manageroo.errors import ValidationError
from manageroo.review import validate_review_evidence


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

    def test_review_evidence_rejects_traversal_and_absolute_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            outside = root / "outside.txt"
            outside.write_text("secret\n", encoding="utf-8")
            for path in ("../outside.txt", str(outside.resolve())):
                review = {
                    "findings": [{
                        "path": path,
                        "start_line": 1,
                        "end_line": 1,
                        "quote": "secret",
                        "blocking": True,
                    }]
                }
                with self.subTest(path=path), self.assertRaises(ValidationError):
                    validate_review_evidence(review, repo)

    def test_blocking_finding_requires_non_empty_quote(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "a.py").write_text("one\ntwo\n", encoding="utf-8")
            review = {
                "status": "changes-required",
                "findings": [{
                    "path": "a.py",
                    "start_line": 1,
                    "end_line": 1,
                    "quote": "",
                    "blocking": True,
                }],
            }
            with self.assertRaises(ValidationError):
                validate_review_evidence(review, repo, allowed_paths=["a.py"])

    def test_blocking_finding_outside_allowed_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "a.py").write_text("one\n", encoding="utf-8")
            (repo / "unrelated.py").write_text("bad\n", encoding="utf-8")
            review = {
                "status": "changes-required",
                "findings": [{
                    "path": "unrelated.py",
                    "start_line": 1,
                    "end_line": 1,
                    "quote": "bad",
                    "blocking": True,
                }],
            }
            with self.assertRaises(ValidationError):
                validate_review_evidence(review, repo, allowed_paths=["a.py"])


if __name__ == "__main__":
    unittest.main()

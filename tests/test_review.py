import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.base import AgentRequest
from manageroo.assets import asset_path
from manageroo.errors import SafetyError, ValidationError
from manageroo.review import run_isolated_review, validate_review_evidence
from manageroo.runner import CommandRunner
from manageroo.schema import load_schema, validate


class ReviewTests(unittest.TestCase):
    def test_adapter_failure_after_mutation_raises_safety_error(self):
        class MutatingFailingAdapter:
            def run(self, request):
                (request.cwd / "a.py").write_text("mutated\n", encoding="utf-8")
                raise RuntimeError("adapter failed")

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            runner = CommandRunner()
            self.assertTrue(runner.run(["git", "init"], cwd=repo).passed)
            (repo / "a.py").write_text("original\n", encoding="utf-8")
            request = AgentRequest(
                role="reviewer",
                prompt_path=repo / "prompt.md",
                schema_path=repo / "schema.json",
                output_path=repo / "review.json",
                cwd=repo,
                sandbox="read-only",
            )

            with self.assertRaisesRegex(SafetyError, "a.py") as caught:
                run_isolated_review(
                    adapter=MutatingFailingAdapter(),
                    request=request,
                    runner=runner,
                )

            self.assertIsInstance(caught.exception.__cause__, RuntimeError)
            self.assertEqual(str(caught.exception.__cause__), "adapter failed")

    def test_review_contract_is_binary_and_rejects_confidence_scores(self):
        schema = load_schema(asset_path("schemas/review.schema.json"))
        validate(
            {"status": "approved", "summary": "No blocking defects.", "findings": []},
            schema,
        )

        with self.assertRaisesRegex(ValidationError, "unknown property 'overall_confidence'"):
            validate(
                {
                    "status": "approved",
                    "summary": "No blocking defects.",
                    "findings": [],
                    "overall_confidence": 0.94,
                },
                schema,
            )

        finding = {
            "id": "review-1",
            "severity": "high",
            "category": "correctness",
            "path": "a.py",
            "start_line": 1,
            "end_line": 1,
            "quote": "broken",
            "reason": "The normal path fails.",
            "action": "Repair the normal path.",
            "blocking": True,
        }
        validate(
            {"status": "changes-required", "summary": "Blocking defect.", "findings": [finding]},
            schema,
        )
        with self.assertRaisesRegex(ValidationError, "unknown property 'confidence'"):
            validate(
                {
                    "status": "changes-required",
                    "summary": "Blocking defect.",
                    "findings": [{**finding, "confidence": 0.94}],
                },
                schema,
            )

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

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from manageroo.discovery_policy import apply_resolved_decisions
from manageroo.entrypoint import _decisions_main, _validated_decisions
from manageroo.errors import ValidationError
from manageroo.util import atomic_write_json


class DecisionRegressionTests(unittest.TestCase):
    def test_show_json_returns_valid_empty_payload_when_no_decisions_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_id = "empty-run"
            (repo / ".manageroo" / "runs" / run_id).mkdir(parents=True)
            output = io.StringIO()
            with redirect_stdout(output):
                code = _decisions_main(["show", run_id, "--repo", str(repo), "--json"])
            self.assertEqual(code, 1)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload, {"run_id": run_id, "decisions": []})

    def test_optionless_decision_is_rejected_before_interactive_prompting(self):
        decisions, error = _validated_decisions([
            {"id": "deployment-mode", "question": "Choose deployment", "options": []}
        ])
        self.assertEqual(decisions, [])
        self.assertIn("no selectable options", error or "")

    def test_unknown_resolved_answer_is_rejected_without_consuming_input(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp) / "run"
            planning = run_root / "artifacts" / "planning"
            planning.mkdir(parents=True)
            resolved = planning / "resolved-decisions.json"
            atomic_write_json(
                planning / "product-model.json",
                {
                    "blocking_decisions": [
                        {"id": "known", "question": "Known?", "options": ["yes", "no"], "chosen": ""}
                    ]
                },
            )
            atomic_write_json(
                resolved,
                {"answers": [{"id": "known", "chosen": "yes"}, {"id": "unknown", "chosen": "no"}]},
            )
            with self.assertRaisesRegex(ValidationError, "unknown decision id"):
                apply_resolved_decisions(run_root)
            self.assertTrue(resolved.is_file())

    def test_duplicate_resolved_answer_is_rejected_without_last_writer_wins(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp) / "run"
            planning = run_root / "artifacts" / "planning"
            planning.mkdir(parents=True)
            resolved = planning / "resolved-decisions.json"
            atomic_write_json(
                planning / "product-model.json",
                {
                    "blocking_decisions": [
                        {"id": "known", "question": "Known?", "options": ["yes", "no"], "chosen": ""}
                    ]
                },
            )
            atomic_write_json(
                resolved,
                {"answers": [{"id": "known", "chosen": "yes"}, {"id": "known", "chosen": "no"}]},
            )
            with self.assertRaisesRegex(ValidationError, "duplicate answer id"):
                apply_resolved_decisions(run_root)
            self.assertTrue(resolved.is_file())


if __name__ == "__main__":
    unittest.main()

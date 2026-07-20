import tempfile
import unittest
from pathlib import Path

from manageroo.artifacts import ArtifactStore
from manageroo.discovery_policy import (
    apply_resolved_decisions,
    decisions_fully_resolved,
    render_blocking_questions,
)
from manageroo.errors import SafetyError
from manageroo.util import atomic_write_json, read_json


class DecisionWorkflowTests(unittest.TestCase):
    def _run_root(self, root: Path) -> Path:
        run_root = root / ".manageroo" / "runs" / "run-1"
        planning = run_root / "artifacts" / "planning"
        planning.mkdir(parents=True)
        atomic_write_json(
            planning / "product-model.json",
            {
                "product_name": "Example",
                "blocking_decisions": [
                    {
                        "id": "DATA-1",
                        "question": "How should old data be migrated?",
                        "why": "The options have different data-loss risk.",
                        "options": ["Additive migration", "Destructive reset"],
                        "recommended": "Additive migration",
                        "reversible": False,
                        "category": "data",
                        "chosen": None,
                    }
                ],
            },
        )
        atomic_write_json(
            planning / "blocking-decisions.json",
            {
                "decisions": [
                    {
                        "id": "DATA-1",
                        "question": "How should old data be migrated?",
                        "why": "The options have different data-loss risk.",
                        "options": ["Additive migration", "Destructive reset"],
                        "recommended": "Additive migration",
                        "reversible": False,
                        "category": "data",
                    }
                ]
            },
        )
        return run_root

    def test_blocking_questions_render_recommendations_and_next_command(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = self._run_root(Path(temp))
            path = render_blocking_questions(run_root)
            self.assertIsNotNone(path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("How should old data be migrated?", text)
            self.assertIn("**Recommended:** Additive migration", text)
            self.assertIn("manageroo decisions answer", text)

    def test_resolved_decisions_preserve_original_evidence_and_unblock_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = self._run_root(Path(temp))
            planning = run_root / "artifacts" / "planning"
            atomic_write_json(
                planning / "resolved-decisions.json",
                {"answers": [{"id": "DATA-1", "chosen": "Additive migration"}]},
            )
            self.assertTrue(apply_resolved_decisions(run_root))
            product = read_json(planning / "product-model.json")
            decision = product["blocking_decisions"][0]
            self.assertEqual(decision["chosen"], "Additive migration")
            self.assertIn("operator answer", decision["resolution_source"])
            self.assertTrue((planning / "blocking-decisions.json").exists())
            self.assertFalse((planning / "resolved-decisions.json").exists())
            resolution = read_json(planning / "decision-resolution.json")
            self.assertEqual(resolution["answers"][0]["id"], "DATA-1")
            self.assertTrue(decisions_fully_resolved(run_root))
            self.assertIsNone(render_blocking_questions(run_root))

    def test_real_artifact_store_locks_resolved_product_and_decision_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = self._run_root(Path(temp))
            planning = run_root / "artifacts" / "planning"
            store = ArtifactStore(run_root / "artifacts")
            store.write_json(
                "planning/product-model.json",
                read_json(planning / "product-model.json"),
                lock=False,
            )
            atomic_write_json(
                planning / "resolved-decisions.json",
                {"answers": [{"id": "DATA-1", "chosen": "Additive migration"}]},
            )
            self.assertTrue(
                apply_resolved_decisions(
                    run_root,
                    artifact_store=store,
                )
            )
            store.verify_locked()
            resolution_path = planning / "decision-resolution.json"
            resolution_path.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(SafetyError):
                store.verify_locked()

    def test_replay_after_product_model_lock_finishes_resolution_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = self._run_root(Path(temp))
            planning = run_root / "artifacts" / "planning"
            store = ArtifactStore(run_root / "artifacts")
            product = read_json(planning / "product-model.json")
            decision = product["blocking_decisions"][0]
            decision["chosen"] = "Additive migration"
            decision["resolution_source"] = "operator answer via manageroo decisions"
            store.write_json(
                "planning/product-model.json",
                product,
                lock=True,
            )
            atomic_write_json(
                planning / "resolved-decisions.json",
                {"answers": [{"id": "DATA-1", "chosen": "Additive migration"}]},
            )
            self.assertTrue(
                apply_resolved_decisions(
                    run_root,
                    artifact_store=store,
                )
            )
            self.assertTrue((planning / "decision-resolution.json").is_file())
            self.assertFalse((planning / "resolved-decisions.json").exists())
            store.verify_locked()

    def test_invalid_answer_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = self._run_root(Path(temp))
            planning = run_root / "artifacts" / "planning"
            atomic_write_json(
                planning / "resolved-decisions.json",
                {"answers": [{"id": "DATA-1", "chosen": "Invent a third option"}]},
            )
            with self.assertRaisesRegex(Exception, "not one of the allowed options"):
                apply_resolved_decisions(run_root)
            self.assertTrue((planning / "blocking-decisions.json").exists())
            self.assertFalse(decisions_fully_resolved(run_root))


if __name__ == "__main__":
    unittest.main()

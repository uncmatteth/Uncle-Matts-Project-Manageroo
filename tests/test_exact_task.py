from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from manageroo.errors import SafetyError, ValidationError
from manageroo.exact_task import build_exact_artifacts, render_external_source_context


class ExactTaskTests(unittest.TestCase):
    def test_explicit_brief_outcomes_are_the_locked_acceptance_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            outcome = "The generated file contains exactly BANANA."
            artifacts = build_exact_artifacts(
                repo=repo,
                brief=(
                    "# Product brief\n\n"
                    "## What I want\n\nCreate the exact file.\n\n"
                    f"## Required outcomes\n\n- {outcome}\n\n"
                    "## Complete means\n\n- Demonstrate the exact file contents.\n"
                ),
                contract={
                    "targets": ["result.txt"],
                    "proofs": ["The generated file contains exactly BANANA"],
                    "gate_ids": ["exact-content"],
                },
                configured_gate_ids=["exact-content"],
            )

        product = artifacts["planning/product-model.json"]
        plan = artifacts["planning/task-plan.json"]
        intake = artifacts["intake/exact-task.json"]
        self.assertEqual(product["acceptance_outcomes"], [outcome])
        self.assertEqual(plan["tasks"][0]["acceptance"], [outcome])
        self.assertEqual(intake["brief_required_outcomes"], [outcome])
        self.assertEqual(intake["locked_acceptance_outcomes"], [outcome])
        self.assertEqual(
            plan["demonstration"]["product_evidence"],
            [{"outcome": outcome, "gate_ids": ["exact-content"]}],
        )

    def test_builds_deterministic_model_and_plan_without_substitution(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "src").mkdir()
            (repo / "src" / "source.py").write_text("VALUE = 69\n", encoding="utf-8")
            (repo / "src" / "target.py").write_text("VALUE = 0\n", encoding="utf-8")
            artifacts = build_exact_artifacts(
                repo=repo,
                brief="Use src/source.py to update src/target.py exactly.",
                contract={
                    "targets": ["src/target.py"],
                    "sources": ["src/source.py"],
                    "exclusions": ["Do not edit anything else."],
                    "proofs": ["The target matches the named source behavior."],
                    "gate_ids": ["tests"],
                },
                configured_gate_ids=["tests"],
            )
        plan = artifacts["planning/task-plan.json"]
        self.assertEqual(plan["tasks"][0]["allowed_paths"], ["src/target.py"])
        self.assertEqual(plan["tasks"][0]["context_paths"], ["src/source.py", "src/target.py"])
        self.assertEqual(plan["reuse_bindings"][0]["implementation"], "adapt-existing")
        self.assertEqual(plan["reuse_bindings"][0]["deviation"], "")

    def test_external_source_is_hash_bound_and_embedded_for_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            source = root / "final.py"
            source.write_text("FINAL = True\n", encoding="utf-8")
            artifacts = build_exact_artifacts(
                repo=repo,
                brief="Use the named final source.",
                contract={
                    "targets": ["target.py"],
                    "sources": [str(source)],
                    "proofs": ["Target uses final source."],
                    "gate_ids": ["tests"],
                },
                configured_gate_ids=["tests"],
            )
            task = artifacts["planning/task-plan.json"]["tasks"][0]
            self.assertIn("FINAL = True", render_external_source_context(task))
            source.write_text("FINAL = False\n", encoding="utf-8")
            with self.assertRaisesRegex(SafetyError, "changed after contract lock"):
                render_external_source_context(task)

    def test_requires_proof_and_real_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            with self.assertRaises(ValidationError):
                build_exact_artifacts(
                    repo=repo,
                    brief="Fix it.",
                    contract={"targets": ["target.py"]},
                    configured_gate_ids=[],
                )


if __name__ == "__main__":
    unittest.main()

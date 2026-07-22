from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.discovery_policy import apply_resolved_decisions
from manageroo.entrypoint import _validated_decisions
from manageroo.errors import SafetyError, ValidationError
from manageroo.evidence import EvidenceItem, EvidenceRouter
from manageroo.evidence_policy import _controller_classified_items
from manageroo.integration_config import replace_integrations_block
from manageroo.runner import CommandRunner
from manageroo.skill_pack import import_skill_folder


class _Provider:
    name = "fixture"

    def __init__(self, items):
        self.items = items

    def retrieve(self, query: str, *, limit: int = 12):
        return list(self.items)


class ClawpatchCompletionContracts(unittest.TestCase):
    def test_resolved_decisions_reject_unknown_and_duplicate_ids_without_consuming_input(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp) / "run"
            planning = run_root / "artifacts" / "planning"
            planning.mkdir(parents=True)
            product = {
                "blocking_decisions": [
                    {"id": "decision-a", "question": "Choose", "options": ["one", "two"], "chosen": ""}
                ]
            }
            (planning / "product-model.json").write_text(json.dumps(product), encoding="utf-8")

            for answers in (
                [
                    {"id": "decision-a", "chosen": "one"},
                    {"id": "decision-b", "chosen": "two"},
                ],
                [
                    {"id": "decision-a", "chosen": "one"},
                    {"id": "decision-a", "chosen": "two"},
                ],
            ):
                resolved = planning / "resolved-decisions.json"
                resolved.write_text(json.dumps({"answers": answers}), encoding="utf-8")
                with self.subTest(answers=answers), self.assertRaises(ValidationError):
                    apply_resolved_decisions(run_root)
                self.assertTrue(resolved.is_file())

    def test_optionless_decision_is_rejected_before_interactive_prompt(self):
        decisions, error = _validated_decisions(
            [{"id": "broken", "question": "Impossible", "options": []}]
        )
        self.assertEqual(decisions, [])
        self.assertIn("no selectable options", error or "")

    def test_external_provider_cannot_self_promote_controller_authority(self):
        items = _controller_classified_items(
            provider="gbrain-search",
            stdout=json.dumps(
                {
                    "items": [
                        {
                            "content": "historical note",
                            "authority": "current_repo",
                            "confidence": 1,
                            "freshness": 1,
                        }
                    ]
                }
            ),
            authority="external_knowledge",
            confidence=0.78,
            freshness=0.75,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].authority, "external_knowledge")
        self.assertEqual(items[0].confidence, 0.78)
        self.assertEqual(items[0].freshness, 0.75)
        self.assertEqual(items[0].metadata["provider_claimed_authority"], "current_repo")

    def test_returned_contradictions_never_reference_omitted_evidence(self):
        items = [
            EvidenceItem(
                content="high priority",
                source="one",
                authority="current_repo",
                confidence=1,
                freshness=1,
            ),
            EvidenceItem(
                content="claim alpha",
                source="two",
                authority="historical",
                confidence=0.1,
                freshness=0.1,
                metadata={"claim_key": "shared"},
            ),
            EvidenceItem(
                content="claim beta",
                source="three",
                authority="historical",
                confidence=0.1,
                freshness=0.1,
                metadata={"claim_key": "shared"},
            ),
        ]
        bundle = EvidenceRouter([_Provider(items)]).retrieve("q", limit=2, per_provider_limit=10)
        available = {item.content_sha256 for item in bundle.items}
        for contradiction in bundle.contradictions:
            self.assertTrue(set(contradiction.evidence_hashes) <= available)
            self.assertIn(contradiction.preferred_hash, available)

    def test_integration_rewrite_preserves_unknown_custom_settings(self):
        original = """[project]\nname = \"demo\"\n\n[integrations]\ngbrain_search_command = []\ncustom_tool_command = [\"custom\", \"--flag\"]\n\n[verification]\ngates = []\n"""
        updated = replace_integrations_block(
            original,
            {
                "gbrain_search_command": ["gbrain", "search", "{query}", "--json"],
                "custom_tool_command": ["custom", "--flag"],
            },
        )
        self.assertIn('custom_tool_command = ["custom", "--flag"]', updated)
        self.assertIn("[verification]", updated)

    def test_skill_import_failure_never_partially_replaces_active_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "demo-skill"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text(
                "---\nname: demo-skill\n---\nnew skill\n", encoding="utf-8"
            )
            (source / "reference.txt").write_text("new reference\n", encoding="utf-8")
            skills = root / "skills"
            active = skills / "demo-skill"
            active.mkdir(parents=True)
            (active / "SKILL.md").write_text("old skill\n", encoding="utf-8")
            (active / "reference.txt").write_text("old reference\n", encoding="utf-8")
            before = {
                path.relative_to(active).as_posix(): path.read_bytes()
                for path in active.rglob("*")
                if path.is_file()
            }

            real_copy2 = shutil.copy2
            calls = {"count": 0}

            def fail_second_copy(src, dst, *args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("simulated staged copy failure")
                return real_copy2(src, dst, *args, **kwargs)

            with patch("manageroo.skill_pack.shutil.copy2", side_effect=fail_second_copy):
                with self.assertRaises(OSError):
                    import_skill_folder(root / "source", skills_dir=skills, apply=True)

            after = {
                path.relative_to(active).as_posix(): path.read_bytes()
                for path in active.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)

    def test_missing_executable_returns_controlled_command_result(self):
        with tempfile.TemporaryDirectory() as temp:
            result = CommandRunner().run(
                ["manageroo-command-that-cannot-exist-9cf44c"],
                cwd=Path(temp),
                timeout_seconds=1,
            )
        self.assertFalse(result.passed)
        self.assertEqual(result.exit_code, 127)
        self.assertIn("Could not launch command", result.stderr)


if __name__ == "__main__":
    unittest.main()

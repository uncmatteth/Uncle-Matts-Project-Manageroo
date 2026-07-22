from __future__ import annotations

import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.config import config_template
from manageroo.discovery_policy import apply_resolved_decisions
from manageroo.entrypoint import _validated_decisions
from manageroo.errors import ValidationError
from manageroo.integration_config import configure_integrations


class ClawpatchCompletionContracts(unittest.TestCase):
    def _decision_run(self, root: Path) -> tuple[Path, Path]:
        run_root = root / "run"
        planning = run_root / "artifacts" / "planning"
        planning.mkdir(parents=True)
        (planning / "product-model.json").write_text(
            json.dumps(
                {
                    "blocking_decisions": [
                        {
                            "id": "decision-a",
                            "question": "Choose",
                            "options": ["one", "two"],
                            "chosen": "",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return run_root, planning / "resolved-decisions.json"

    def test_resolved_decisions_reject_unknown_id_without_consuming_input(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root, resolved = self._decision_run(Path(temp))
            resolved.write_text(
                json.dumps(
                    {
                        "answers": [
                            {"id": "decision-a", "chosen": "one"},
                            {"id": "decision-b", "chosen": "two"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            before = resolved.read_bytes()
            with self.assertRaisesRegex(ValidationError, "unknown decision id"):
                apply_resolved_decisions(run_root)
            self.assertEqual(resolved.read_bytes(), before)

    def test_resolved_decisions_reject_duplicate_id_without_consuming_input(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root, resolved = self._decision_run(Path(temp))
            resolved.write_text(
                json.dumps(
                    {
                        "answers": [
                            {"id": "decision-a", "chosen": "one"},
                            {"id": "decision-a", "chosen": "two"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            before = resolved.read_bytes()
            with self.assertRaisesRegex(ValidationError, "duplicate answer id"):
                apply_resolved_decisions(run_root)
            self.assertEqual(resolved.read_bytes(), before)

    def test_optionless_decision_is_rejected_before_interactive_prompt(self):
        decisions, error = _validated_decisions(
            [{"id": "broken", "question": "Impossible", "options": []}]
        )
        self.assertEqual(decisions, [])
        self.assertIn("no selectable options", error or "")

    def test_configure_integrations_preserves_unknown_existing_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            config_path = repo / ".manageroo" / "config.toml"
            config_path.parent.mkdir(parents=True)
            text = config_template("codex", [])
            text = text.replace(
                "gbrain_search_command = []",
                'gbrain_search_command = []\ncustom_tool_command = ["custom", "--flag"]',
            )
            config_path.write_text(text, encoding="utf-8")

            with patch(
                "manageroo.integration_config.shutil.which",
                side_effect=lambda name: "/usr/bin/gbrain" if name == "gbrain" else None,
            ):
                report = configure_integrations(
                    repo,
                    gbrain=True,
                    gitnexus=False,
                    apply=True,
                )

            self.assertTrue(report["applied"])
            parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(
                parsed["integrations"]["custom_tool_command"],
                ["custom", "--flag"],
            )
            self.assertEqual(
                parsed["integrations"]["gbrain_search_command"],
                ["gbrain", "search", "{query}", "--json"],
            )


if __name__ == "__main__":
    unittest.main()

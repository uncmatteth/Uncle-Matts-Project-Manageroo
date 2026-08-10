from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NoGlobalOperatorHooksTests(unittest.TestCase):
    def test_runtime_has_no_legacy_prompt_derived_permission_firewall(self):
        forbidden = (
            "operator-receipt",
            "operator-exec",
            "controlled_run_required",
            "Manageroo denied access to an unnamed repository",
        )
        for path in sorted((ROOT / "src" / "manageroo").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for phrase in forbidden:
                self.assertNotIn(phrase, text, f"{phrase!r} remains in {path}")
        self.assertFalse((ROOT / "src" / "manageroo" / "operator_scope.py").exists())
        self.assertFalse((ROOT / "src" / "manageroo" / "operator_exec.py").exists())
        entrypoint = (ROOT / "src" / "manageroo" / "entrypoint.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('argv == ["operator-' 'scope-hook"]', entrypoint)

    def test_installer_replaces_legacy_guard_with_agent_continuity(self):
        text = (ROOT / "scripts" / "install.py").read_text(encoding="utf-8")
        self.assertIn("remove_legacy_codex_operator_hooks", text)
        self.assertIn("install_codex_continuity_hooks", text)
        continuity = (ROOT / "src" / "manageroo" / "agent_continuity.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"PreToolUse": {"matcher": "*"', continuity)
        self.assertIn('"Stop": {"hooks":', continuity)
        self.assertIn("This controls agent behavior; it never limits what the operator", continuity)

    def test_bundled_skill_does_not_forbid_normal_operator_tools(self):
        skill = (
            ROOT
            / "src"
            / "manageroo"
            / "assets"
            / "skills"
            / "uncle-matts-project-manageroo"
            / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("The current operator request owns the work", skill)
        self.assertIn("Never answer authorized work with a receipt", skill)
        for phrase in (
            "do not implement it freehand",
            "freehand repository search",
            "host `Stop` gate",
            ".manageroo/operator-tmp",
        ):
            self.assertNotIn(phrase, skill)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CodexContinuityHooksTests(unittest.TestCase):
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
        self.assertFalse((ROOT / "src" / "manageroo" / "action_authority.py").exists())
        entrypoint = (ROOT / "src" / "manageroo" / "entrypoint.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('argv == ["operator-' 'scope-hook"]', entrypoint)

    def test_installer_replaces_legacy_guard_with_agent_continuity(self):
        installer = runpy.run_path(str(ROOT / "scripts" / "install.py"))
        events = {
            "SessionStart": "startup|resume|clear|compact",
            "UserPromptSubmit": None,
            "PreToolUse": "*",
            "SubagentStart": None,
            "Stop": None,
        }
        legacy_group = {
            "hooks": [{"command": "/bin/manageroo operator-" "scope-hook"}]
        }
        unrelated_group = {"hooks": [{"command": "gbrain prompt hook"}]}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / ".codex"
            codex_home.mkdir()
            hooks_path = codex_home / "hooks.json"
            hooks_path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            event: (
                                [unrelated_group, legacy_group]
                                if event == "UserPromptSubmit"
                                else [legacy_group]
                            )
                        for event in events
                        }
                    }
                ),
                encoding="utf-8",
            )
            manageroo_command = root / "bin" / "manageroo"

            removed = installer["remove_legacy_codex_operator_hooks"](
                codex_home=codex_home
            )
            installed = installer["install_codex_continuity_hooks"](
                codex_home=codex_home,
                manageroo_command=manageroo_command,
            )

            self.assertEqual(removed["removed"], len(events))
            self.assertTrue(removed["changed"])
            self.assertTrue(installed["changed"])
            written = json.loads(hooks_path.read_text(encoding="utf-8"))
            rendered = json.dumps(written)
            self.assertNotIn("operator-" "scope-hook", rendered)
            self.assertIn("gbrain prompt hook", rendered)
            for event, matcher in events.items():
                groups = [
                    group
                    for group in written["hooks"][event]
                    if "agent-continuity-hook" in json.dumps(group)
                ]
                self.assertEqual(len(groups), 1, event)
                if matcher is None:
                    self.assertNotIn("matcher", groups[0])
                else:
                    self.assertEqual(groups[0]["matcher"], matcher)
                handler = groups[0]["hooks"][0]
                self.assertEqual(handler["type"], "command")
                self.assertEqual(handler["timeout"], 10)
                self.assertIn(str(manageroo_command.resolve()), handler["command"])
                self.assertEqual(handler["additionalContextLimit"], 10000)
            self.assertIn("Stop", written["hooks"])

            first_bytes = hooks_path.read_bytes()
            removed_again = installer["remove_legacy_codex_operator_hooks"](
                codex_home=codex_home
            )
            installed_again = installer["install_codex_continuity_hooks"](
                codex_home=codex_home,
                manageroo_command=manageroo_command,
            )
            self.assertEqual(removed_again["removed"], 0)
            self.assertFalse(removed_again["changed"])
            self.assertFalse(installed_again["changed"])
            self.assertEqual(hooks_path.read_bytes(), first_bytes)

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

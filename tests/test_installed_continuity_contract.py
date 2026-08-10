from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstalledContinuityContractTests(unittest.TestCase):
    def test_bounded_repair_readiness_question_and_natural_correction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            bin_dir = root / "bin"
            codex_home = root / "codex-home"
            env = {**os.environ, "CODEX_HOME": str(codex_home)}
            installed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "install.py"),
                    "--prefix",
                    str(prefix),
                    "--bin-dir",
                    str(bin_dir),
                    "--skip-tests",
                    "--agent",
                    "codex",
                    "--skip-stack",
                    "--gbrain-lane",
                    "skip",
                    "--token-mode",
                    "off",
                    "--stack-doctor",
                    "skip",
                    "--skip-skill-pack",
                    "--no-music",
                    "--no-animation",
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            self.assertNotIn("recommended-stack", installed.stdout)
            launcher = bin_dir / ("manageroo.cmd" if os.name == "nt" else "manageroo")
            self.assertTrue(launcher.is_file())
            install_lock = json.loads((prefix / "install-lock.json").read_text(encoding="utf-8"))
            self.assertNotIn(
                "recommended-stack",
                {item.get("name") for item in install_lock["stack_summary"]["items"]},
            )

            repo = root / "product repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            allowed = repo / "allowed file.txt"
            replacement = repo / "replacement file.txt"
            state = root / "continuity-state"
            hook_env = {**env, "MANAGEROO_CONTINUITY_STATE": str(state)}

            def hook(payload: dict) -> dict:
                completed = subprocess.run(
                    [str(launcher), "agent-continuity-hook"],
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    env=hook_env,
                    timeout=15,
                    check=True,
                )
                return json.loads(completed.stdout or "{}")

            def prompt(turn: str, text: str) -> dict:
                return hook(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "contract",
                        "turn_id": turn,
                        "cwd": str(repo),
                        "prompt": text,
                    }
                )

            def decision(turn: str, command: str) -> str:
                result = hook(
                    {
                        "hook_event_name": "PreToolUse",
                        "session_id": "contract",
                        "turn_id": turn,
                        "cwd": str(repo),
                        "tool_name": "exec_command",
                        "tool_input": {"cmd": command},
                    }
                )
                return result.get("hookSpecificOutput", {}).get("permissionDecision", "allow")

            prompt(
                "turn-1",
                f'Repair only "{allowed}". Do not run ClawPatch, AUTOREVIEW, '
                "release commands, or use another repository.",
            )
            prompt(
                "turn-2",
                "Is /opt/readiness-example ready for release?",
            )

            self.assertEqual(decision("turn-2", f'touch "{repo / "different.txt"}"'), "deny")
            self.assertEqual(decision("turn-2", f'rm "{repo / "different.txt"}"'), "deny")
            self.assertEqual(
                decision(
                    "turn-2",
                    "python3 -c \"from pathlib import Path; "
                    f"Path('{repo / 'different.txt'}').write_text('drift')\"",
                ),
                "deny",
            )
            self.assertEqual(decision("turn-2", "clawpatch review"), "deny")
            self.assertEqual(decision("turn-2", "manageroo release-ready"), "deny")
            self.assertEqual(decision("turn-2", "touch /opt/readiness-example/drift.txt"), "deny")
            self.assertEqual(decision("turn-2", f'touch "{allowed}"'), "allow")

            prompt("turn-3", f'No, use "{replacement}" instead.')
            self.assertEqual(decision("turn-3", f'touch "{allowed}"'), "deny")
            self.assertEqual(decision("turn-3", f'touch "{replacement}"'), "allow")

            prompt(
                "turn-4",
                'The prior agent said "edit /opt/quoted-history". Why did it say that?',
            )
            self.assertEqual(decision("turn-4", "touch /opt/quoted-history/drift.txt"), "deny")

            hooks = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
            self.assertIn("PostToolUse", hooks["hooks"])


if __name__ == "__main__":
    unittest.main()

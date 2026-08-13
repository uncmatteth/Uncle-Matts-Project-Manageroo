from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.agent_continuity import install_codex_continuity_hooks
from manageroo.install_status import INSTALL_OWNERSHIP_MARKER, LAUNCHER_MARKER
from manageroo.cli import main
from manageroo.token_modes import install_core_helper_skills
from manageroo.uninstall import build_uninstall_inventory, uninstall_manageroo


def _launcher_text(prefix: Path) -> str:
    app = prefix / "app"
    python = prefix / "venv" / "bin" / "python"
    return (
        "#!/bin/sh\n"
        f"# {LAUNCHER_MARKER}\n"
        f"export PYTHONPATH={app}${{PYTHONPATH:+:$PYTHONPATH}}\n"
        f"export MANAGEROO_PREFIX={prefix}\n"
        f'exec {python} -m manageroo "$@"\n'
    )


def _write_owned_lock(prefix: Path, launcher: Path, external_tools: list[dict]) -> None:
    installation_id = "a" * 64
    marker = prefix / INSTALL_OWNERSHIP_MARKER
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "Uncle Matt's Project Manageroo",
                "prefix": str(prefix.resolve()),
                "installation_id": installation_id,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    lock = {
        "product": "Uncle Matt's Project Manageroo",
        "prefix": str(prefix.resolve()),
        "launcher": str(launcher.resolve()),
        "agent_continuity_hooks": {"ok": True},
        "external_tools": external_tools,
        "installation_ownership": {
            "schema_version": 1,
            "marker": INSTALL_OWNERSHIP_MARKER,
            "marker_sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
            "installation_id": installation_id,
        },
    }
    (prefix / "install-lock.json").write_text(json.dumps(lock), encoding="utf-8")


class UninstallTests(unittest.TestCase):
    def test_cli_lists_components_and_requires_final_confirmation(self):
        components = [
            {"id": item, "label": item.title(), "removable": True, "paths": [], "detail": "ready"}
            for item in ("runtime", "hooks", "skills", "state")
        ]
        inventory = {
            "ok": True,
            "components": components,
            "by_id": {item["id"]: item for item in components},
            "surrounding_tools": [
                {"name": "codex", "note": "Shared or ownership-unproven tool; preserved automatically."}
            ],
        }
        applied = {**inventory, "applied": True, "actions": []}
        output = io.StringIO()
        with (
            patch.object(sys.stdin, "isatty", return_value=True),
            patch("builtins.input", side_effect=["1", "yes"]),
            patch("manageroo.cli.build_uninstall_inventory", return_value=inventory),
            patch("manageroo.cli.uninstall_manageroo", return_value=applied) as uninstall,
            patch("sys.stdout", output),
        ):
            code = main(["uninstall"])

        self.assertEqual(code, 0)
        self.assertIn("Recorded surrounding tools", output.getvalue())
        uninstall.assert_called_once()
        self.assertEqual(
            uninstall.call_args.kwargs["components"],
            ["runtime", "hooks", "skills", "state"],
        )
        self.assertTrue(uninstall.call_args.kwargs["confirmed"])

    def test_inventory_lists_owned_pieces_and_preserves_shared_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            launcher = root / "bin" / "manageroo"
            skills = root / "skills"
            ledger = root / "skill-ownership.json"
            codex_home = root / "codex-home"
            prefix.mkdir()
            launcher.parent.mkdir()
            launcher.write_text(_launcher_text(prefix), encoding="utf-8")
            launcher.chmod(0o755)
            _write_owned_lock(
                prefix,
                launcher,
                [{"name": "codex", "path": str(root / "shared" / "codex"), "installed": True}],
            )
            install_core_helper_skills(skills_dir=skills, search_roots=[], ownership_path=ledger)
            install_codex_continuity_hooks(codex_home=codex_home, manageroo_command=launcher)

            inventory = build_uninstall_inventory(
                prefix=prefix,
                bin_dir=launcher.parent,
                codex_home=codex_home,
                skills_dir=skills,
                ownership_path=ledger,
            )

            self.assertEqual(
                [item["id"] for item in inventory["components"]],
                ["runtime", "hooks", "skills", "state"],
            )
            self.assertTrue(inventory["by_id"]["runtime"]["removable"])
            self.assertEqual(len(inventory["by_id"]["skills"]["paths"]), 22)
            self.assertEqual(inventory["surrounding_tools"][0]["name"], "codex")
            self.assertFalse(inventory["surrounding_tools"][0]["automatic_removal"])

    def test_uninstall_requires_confirmation_and_can_remove_selected_pieces(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            launcher = root / "bin" / "manageroo"
            skills = root / "skills"
            ledger = root / "skill-ownership.json"
            codex_home = root / "codex-home"
            continuity_state = root / "continuity"
            token_state = root / "token-mode.json"
            shared_codex = root / "shared" / "codex"
            prefix.mkdir()
            launcher.parent.mkdir()
            shared_codex.parent.mkdir()
            shared_codex.write_text("shared\n", encoding="utf-8")
            launcher.write_text(_launcher_text(prefix), encoding="utf-8")
            launcher.chmod(0o755)
            _write_owned_lock(
                prefix,
                launcher,
                [{"name": "codex", "path": str(shared_codex), "installed": True}],
            )
            install_core_helper_skills(skills_dir=skills, search_roots=[], ownership_path=ledger)
            install_codex_continuity_hooks(codex_home=codex_home, manageroo_command=launcher)
            continuity_state.mkdir()
            (continuity_state / "session.json").write_text("{}\n", encoding="utf-8")
            token_state.write_text("{}\n", encoding="utf-8")
            environment = {
                "MANAGEROO_CONTINUITY_STATE": str(continuity_state),
                "MANAGEROO_TOKEN_MODE_FILE": str(token_state),
            }

            with patch.dict(os.environ, environment, clear=False):
                cancelled = uninstall_manageroo(
                    prefix=prefix,
                    bin_dir=launcher.parent,
                    codex_home=codex_home,
                    skills_dir=skills,
                    ownership_path=ledger,
                    components=["hooks"],
                    confirmed=False,
                )
                hooks_only = uninstall_manageroo(
                    prefix=prefix,
                    bin_dir=launcher.parent,
                    codex_home=codex_home,
                    skills_dir=skills,
                    ownership_path=ledger,
                    components=["hooks"],
                    confirmed=True,
                )

            self.assertFalse(cancelled["applied"])
            self.assertTrue(hooks_only["applied"])
            self.assertTrue(prefix.is_dir())
            self.assertTrue(launcher.is_file())
            self.assertNotIn(str(launcher), (codex_home / "hooks.json").read_text(encoding="utf-8"))

            with patch.dict(os.environ, environment, clear=False):
                removed = uninstall_manageroo(
                    prefix=prefix,
                    bin_dir=launcher.parent,
                    codex_home=codex_home,
                    skills_dir=skills,
                    ownership_path=ledger,
                    components=["skills", "state", "runtime"],
                    confirmed=True,
                )

            self.assertTrue(removed["applied"])
            self.assertFalse(prefix.exists())
            self.assertFalse(launcher.exists())
            self.assertFalse(continuity_state.exists())
            self.assertFalse(token_state.exists())
            self.assertTrue(shared_codex.is_file())


if __name__ == "__main__":
    unittest.main()

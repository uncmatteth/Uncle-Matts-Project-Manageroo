from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from manageroo.errors import ValidationError
from manageroo.runtime_contract import (
    REQUIRED_STACK_CAPABILITIES,
    default_gbrain_source_id,
    ensure_default_obsidian_vault,
    gbrain_status_has_repo,
    missing_required_stack,
    required_stack_records,
    validate_required_stack,
)
from manageroo.runtime_contract_policy import (
    install_runtime_cli_policy,
    install_runtime_contract_policy,
)


class RuntimeContractTests(unittest.TestCase):
    def _config(self, *, adapter: str = "codex") -> dict:
        return {
            "agent": {"adapter": adapter},
            "integrations": {
                "obsidian_vault": "",
                "obsidian_export_folder": "MANAGEROO",
                "gbrain_search_command": [],
                "gbrain_capture_command": [],
                "gitnexus_analyze_command": [],
                "gitnexus_query_command": [],
                "autoreview_command": [],
                "clawpatch_command": [],
            },
        }

    def test_missing_stack_ids_are_authoritative_and_mock_is_exempt(self):
        config = self._config()
        self.assertEqual(
            missing_required_stack(config),
            list(REQUIRED_STACK_CAPABILITIES),
        )
        with self.assertRaisesRegex(ValidationError, "required Manageroo stack"):
            validate_required_stack(config)
        self.assertEqual(missing_required_stack(self._config(adapter="mock")), [])

    def test_complete_stack_records_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tool = root / "tool"
            tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            tool.chmod(0o755)
            vault = root / "vault"
            (vault / "MANAGEROO").mkdir(parents=True)
            config = self._config()
            integrations = config["integrations"]
            for key in (
                "gbrain_search_command",
                "gbrain_capture_command",
                "gitnexus_analyze_command",
                "gitnexus_query_command",
                "autoreview_command",
                "clawpatch_command",
            ):
                integrations[key] = [str(tool), key]
            integrations["obsidian_vault"] = str(vault)

            records = required_stack_records(config)
            self.assertTrue(all(record["ok"] for record in records), records)
            self.assertEqual(missing_required_stack(config), [])
            validate_required_stack(config)

    def test_readiness_and_orchestrator_share_the_same_contract(self):
        config = self._config()

        class FakeOrchestrator:
            def __init__(self):
                self.config = config

            def _validate_required_stack_configuration(self):
                raise AssertionError("unpatched")

        def base_readiness(_repo, *, require_gbrain=False):
            del require_gbrain
            return {
                "ok": True,
                "status": "READY TO RUN",
                "repo": "/product",
                "items": [],
                "next_commands": [],
            }

        readiness_module = SimpleNamespace(
            readiness=base_readiness,
            load_config=lambda _repo: config,
        )
        release_ready_module = SimpleNamespace(readiness=base_readiness)
        orchestrator_module = SimpleNamespace(Orchestrator=FakeOrchestrator)
        install_runtime_contract_policy(
            orchestrator_module, readiness_module, release_ready_module
        )

        report = readiness_module.readiness(Path("/product"))
        ids = [
            item["name"].split(":", 1)[1]
            for item in report["items"]
            if item["name"].startswith("required stack:")
        ]
        self.assertEqual(ids, list(REQUIRED_STACK_CAPABILITIES))
        self.assertFalse(report["ok"])
        self.assertEqual(release_ready_module.readiness, readiness_module.readiness)
        with self.assertRaisesRegex(ValidationError, "gbrain"):
            FakeOrchestrator()._validate_required_stack_configuration()

    def test_public_setup_for_real_adapter_configures_full_stack_and_maps_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            captured: dict = {}

            def original(selected_repo, *args, **kwargs):
                captured["repo"] = Path(selected_repo)
                captured["args"] = args
                captured["kwargs"] = dict(kwargs)
                return {"ok": True, "records": [], "next_command": "manageroo ready"}

            mapped = {
                "ok": True,
                "status": {
                    "sources": [
                        {"id": "mapped", "path": str(repo.resolve())}
                    ]
                },
                "next_commands": [],
            }
            setup_calls: list[dict] = []

            def gbrain_setup_status(**kwargs):
                setup_calls.append(dict(kwargs))
                return {"ok": False, "status": {"sources": []}} if not kwargs else mapped

            cli_module = SimpleNamespace(
                configure_integrations=original,
                load_config=lambda _repo: self._config(),
                gbrain_setup_status=gbrain_setup_status,
            )
            with patch.dict(
                os.environ,
                {"MANAGEROO_DEFAULT_OBSIDIAN_VAULT_ROOT": str(root / "vaults")},
                clear=False,
            ):
                install_runtime_cli_policy(cli_module)
                report = cli_module.configure_integrations(
                    repo,
                    gbrain=False,
                    gitnexus=False,
                    apply=True,
                )

            kwargs = captured["kwargs"]
            self.assertTrue(kwargs["full"])
            self.assertTrue(kwargs["gbrain"])
            self.assertTrue(kwargs["gitnexus"])
            self.assertTrue(Path(kwargs["obsidian_vault"]).is_dir())
            self.assertTrue(
                Path(kwargs["obsidian_vault"], kwargs["obsidian_export_folder"]).is_dir()
            )
            self.assertEqual(len(setup_calls), 2)
            self.assertEqual(setup_calls[1]["source_path"], repo)
            self.assertEqual(
                setup_calls[1]["source_id"], default_gbrain_source_id(repo)
            )
            self.assertTrue(setup_calls[1]["apply"])
            self.assertTrue(setup_calls[1]["sync"])
            self.assertTrue(report["ok"])
            self.assertEqual(report["gbrain_repo_source"], mapped)

    def test_mock_setup_does_not_force_host_stack(self):
        captured: dict = {}

        def original(_repo, *args, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

        cli_module = SimpleNamespace(
            configure_integrations=original,
            load_config=lambda _repo: self._config(adapter="mock"),
            gbrain_setup_status=Mock(side_effect=AssertionError("must not run")),
        )
        install_runtime_cli_policy(cli_module)
        report = cli_module.configure_integrations(
            Path("/mock"), gbrain=False, gitnexus=False, apply=True
        )
        self.assertEqual(report, {"ok": True})
        self.assertNotIn("full", captured)
        self.assertFalse(captured["gbrain"])
        self.assertFalse(captured["gitnexus"])

    def test_existing_exact_gbrain_mapping_is_reused_without_duplicate_add(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            current = {
                "ok": False,
                "status": {
                    "sources": [
                        {"id": "existing", "path": str(repo.resolve())}
                    ]
                },
                "next_commands": ["sync existing"],
            }
            calls: list[dict] = []

            def gbrain_setup_status(**kwargs):
                calls.append(dict(kwargs))
                return current

            cli_module = SimpleNamespace(
                configure_integrations=lambda *_args, **_kwargs: {"ok": True},
                load_config=lambda _repo: self._config(),
                gbrain_setup_status=gbrain_setup_status,
            )
            with patch.dict(
                os.environ,
                {"MANAEROO_DEFAULT_OBSIDIAN_VAULT_ROOT": str(Path(temp) / "vaults")},
                clear=False,
            ):
                install_runtime_cli_policy(cli_module)
                report = cli_module.configure_integrations(repo, apply=True)

            self.assertEqual(calls, [{}])
            self.assertFalse(report["ok"])
            self.assertEqual(report["next_command"], "sync existing")
            self.assertTrue(gbrain_status_has_repo(current, repo))

    def test_default_vault_is_outside_repo_and_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            with patch.dict(
                os.environ,
                {"MANAGEROO_DEFAULT_OBSIDIAN_VAULT_ROOT": str(root / "vaults")},
                clear=False,
            ):
                first, export = ensure_default_obsidian_vault(repo)
                second, second_export = ensure_default_obsidian_vault(repo)
            self.assertEqual(first, second)
            self.assertEqual(export, second_export)
            self.assertFalse(first.is_relative_to(repo))
            self.assertTrue((first / export).is_dir())


if __name__ == "__main__":
    unittest.main()

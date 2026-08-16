from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from manageroo.errors import ValidationError
from manageroo.runtime_contract import (
    ENHANCED_STACK_CAPABILITIES,
    default_gbrain_source_id,
    ensure_default_obsidian_vault,
    gbrain_status_has_repo,
    missing_required_stack,
    runtime_capability_records,
    validate_required_stack,
)
from manageroo.runtime_contract_policy import (
    install_runtime_cli_policy,
    install_runtime_contract_policy,
)


class RuntimeContractTests(unittest.TestCase):
    def _config(self, *, adapter: str = "codex", required=()) -> dict:
        return {
            "agent": {"adapter": adapter},
            "runtime": {"required_capabilities": list(required)},
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

    def _complete_stack(self, root: Path, config: dict) -> None:
        tool = root / "tool"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
        vault = root / "vault"
        (vault / "MANAGEROO").mkdir(parents=True)
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

    def test_core_only_real_adapter_does_not_require_enhanced_stack(self):
        config = self._config()
        records = runtime_capability_records(config)
        self.assertEqual(
            [record["id"] for record in records],
            list(ENHANCED_STACK_CAPABILITIES),
        )
        self.assertTrue(all(not record["required"] for record in records))
        self.assertTrue(all(not record["available"] for record in records))
        self.assertEqual(missing_required_stack(config), [])
        validate_required_stack(config)

    def test_explicitly_required_missing_lane_fails_precisely(self):
        config = self._config(required=("gbrain",))
        self.assertEqual(missing_required_stack(config), ["gbrain"])
        with self.assertRaisesRegex(
            ValidationError, "requires unavailable capabilities: gbrain"
        ):
            validate_required_stack(config)

    def test_complete_enhanced_stack_is_recorded_available(self):
        with tempfile.TemporaryDirectory() as temp:
            config = self._config()
            self._complete_stack(Path(temp), config)
            records = runtime_capability_records(config)
            self.assertTrue(all(record["available"] for record in records), records)
            self.assertEqual(missing_required_stack(config), [])
            validate_required_stack(config)

    def test_readiness_and_orchestrator_share_optional_contract(self):
        config = self._config()

        class FakeOrchestrator:
            def __init__(self):
                self.config = config
                self.written = None

            def _write_or_reuse_json(self, relative, data, lock=False):
                self.written = (relative, data, lock)

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
        capabilities = [
            item for item in report["items"]
            if item["name"].startswith("runtime capability:")
        ]
        self.assertEqual(len(capabilities), len(ENHANCED_STACK_CAPABILITIES))
        self.assertTrue(all(not item["required"] for item in capabilities))
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "READY TO RUN")
        self.assertEqual(release_ready_module.readiness, readiness_module.readiness)

        orchestrator = FakeOrchestrator()
        orchestrator._validate_required_stack_configuration()
        self.assertEqual(orchestrator.written[0], "verification/runtime-capabilities.json")
        self.assertEqual(
            orchestrator.written[1]["enhanced_stack_unavailable"],
            list(ENHANCED_STACK_CAPABILITIES),
        )

    def test_readiness_can_explicitly_require_gbrain(self):
        config = self._config()

        class FakeOrchestrator:
            pass

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
        install_runtime_contract_policy(
            SimpleNamespace(Orchestrator=FakeOrchestrator),
            readiness_module,
            release_ready_module,
        )
        report = readiness_module.readiness(Path("/product"), require_gbrain=True)
        gbrain = next(
            item for item in report["items"]
            if item["name"] == "runtime capability:gbrain"
        )
        self.assertTrue(gbrain["required"])
        self.assertFalse(report["ok"])
        self.assertIn("manageroo integrations configure --full", report["next_commands"])

    def test_public_setup_honors_selected_integrations_without_forcing_full_stack(self):
        captured: dict = {}

        def original(_repo, *args, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

        cli_module = SimpleNamespace(
            configure_integrations=original,
            load_config=lambda _repo: self._config(),
            gbrain_setup_status=Mock(side_effect=AssertionError("must not run")),
        )
        install_runtime_cli_policy(cli_module)
        report = cli_module.configure_integrations(
            Path("/product"), gbrain=False, gitnexus=False, apply=True
        )
        self.assertEqual(report, {"ok": True})
        self.assertFalse(captured["gbrain"])
        self.assertFalse(captured["gitnexus"])
        self.assertNotIn("full", captured)
        self.assertNotIn("obsidian_vault", captured)

    def test_selected_gbrain_setup_maps_exact_repo(self):
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
            install_runtime_cli_policy(cli_module)
            report = cli_module.configure_integrations(
                repo,
                gbrain=True,
                gitnexus=False,
                apply=True,
            )

            kwargs = captured["kwargs"]
            self.assertNotIn("full", kwargs)
            self.assertTrue(kwargs["gbrain"])
            self.assertFalse(kwargs["gitnexus"])
            self.assertEqual(len(setup_calls), 2)
            self.assertEqual(setup_calls[1]["source_path"], repo)
            self.assertEqual(
                setup_calls[1]["source_id"], default_gbrain_source_id(repo)
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["gbrain_repo_source"], mapped)

    def test_full_setup_creates_default_obsidian_vault(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            captured: dict = {}

            def original(_repo, *args, **kwargs):
                captured.update(kwargs)
                return {"ok": True}

            cli_module = SimpleNamespace(
                configure_integrations=original,
                load_config=lambda _repo: self._config(),
                gbrain_setup_status=lambda **_kwargs: {
                    "ok": True,
                    "status": {"sources": [{"path": str(repo.resolve())}]},
                },
            )
            with patch.dict(
                os.environ,
                {"MANAGEROO_DEFAULT_OBSIDIAN_VAULT_ROOT": str(root / "vaults")},
                clear=False,
            ):
                install_runtime_cli_policy(cli_module)
                cli_module.configure_integrations(
                    repo,
                    full=True,
                    gbrain=False,
                    gitnexus=True,
                    apply=True,
                )
            self.assertTrue(Path(captured["obsidian_vault"]).is_dir())
            self.assertTrue(
                Path(
                    captured["obsidian_vault"],
                    captured["obsidian_export_folder"],
                ).is_dir()
            )

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
        self.assertFalse(captured["gbrain"])
        self.assertFalse(captured["gitnexus"])

    def test_existing_exact_gbrain_mapping_is_reused_without_duplicate_add(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            current = {
                "ok": True,
                "status": {
                    "sources": [
                        {"id": "existing", "path": str(repo.resolve())}
                    ]
                },
                "next_commands": [],
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
            install_runtime_cli_policy(cli_module)
            report = cli_module.configure_integrations(
                repo, gbrain=True, gitnexus=False, apply=True
            )

            self.assertEqual(calls, [{}])
            self.assertTrue(report["ok"])
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

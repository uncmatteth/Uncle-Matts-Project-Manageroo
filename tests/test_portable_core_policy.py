from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from manageroo.errors import ValidationError
from manageroo.portable_core_policy import install_portable_core_policy


class PortableCorePolicyTests(unittest.TestCase):
    @staticmethod
    def _config(*, required=()) -> dict:
        return {
            "agent": {"adapter": "codex"},
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

    @staticmethod
    def _orchestrator_class(config: dict):
        class FakeOrchestrator:
            def __init__(self):
                self.config = config
                self.source_repo = Path("/product")
                self.run_root = Path("/run")
                self.__dict__["artifacts"] = SimpleNamespace(write_json=lambda *_a, **_k: None)

            def _required_stack_enabled(self):
                return True

            def _external_values(self, *, brief):
                return {"query": brief}

            def _run_optional_external_command(self, **kwargs):
                return {
                    "name": kwargs["name"],
                    "enabled": True,
                    "ok": True,
                    "stdout": "[]",
                }

            def _external_intelligence(self, brief, inventory):
                del brief, inventory
                return {"summary": {}, "records": []}

            def _capture_external_outcome(self, **kwargs):
                del kwargs
                return None

        return FakeOrchestrator

    def _modules(self, config: dict):
        fake_class = self._orchestrator_class(config)
        orchestrator_module = SimpleNamespace(
            Orchestrator=fake_class,
            requested_intelligence_lanes=lambda _brief: {
                "document-analysis": False,
                "gbrain-search": True,
            },
            gbrain_repo_source_item=lambda _repo: {
                "ok": True,
                "matched_sources": [{"id": "product", "path": "/product"}],
            },
            gbrain_query_payload=lambda brief, _source: brief,
            scope_gbrain_search_record=lambda record, _source: record,
        )
        readiness_module = SimpleNamespace(
            requested_intelligence_lanes=orchestrator_module.requested_intelligence_lanes,
            _mentions=lambda text, terms: [
                term for term in terms if term in text.casefold()
            ],
            EXPLICIT_EXTERNAL_MEMORY_TERMS=("gbrain", "obsidian"),
        )
        return fake_class, orchestrator_module, readiness_module

    def test_core_only_run_does_not_enable_legacy_full_stack_mode(self):
        config = self._config()
        fake_class, orchestrator_module, readiness_module = self._modules(config)
        install_portable_core_policy(orchestrator_module, readiness_module)

        self.assertFalse(fake_class()._required_stack_enabled())
        self.assertFalse(
            readiness_module.requested_intelligence_lanes("Fix login.")[
                "gbrain-search"
            ]
        )
        self.assertTrue(
            readiness_module.requested_intelligence_lanes(
                "Use GBrain for prior project context."
            )["gbrain-search"]
        )

    def test_complete_enhanced_stack_enables_existing_strict_path(self):
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

            fake_class, orchestrator_module, readiness_module = self._modules(config)
            install_portable_core_policy(orchestrator_module, readiness_module)
            self.assertTrue(fake_class()._required_stack_enabled())

    def test_explicit_required_discovery_lane_must_pass(self):
        config = self._config(required=("gbrain",))
        fake_class, orchestrator_module, readiness_module = self._modules(config)

        def failed_intelligence(self, brief, inventory):
            del self, brief, inventory
            return {
                "summary": {},
                "records": [
                    {
                        "name": "gbrain-search",
                        "enabled": True,
                        "ok": False,
                        "error": "provider failed",
                    }
                ],
            }

        fake_class._external_intelligence = failed_intelligence
        install_portable_core_policy(orchestrator_module, readiness_module)

        with self.assertRaisesRegex(
            ValidationError,
            "requires gbrain-search, and it failed: provider failed",
        ):
            fake_class()._external_intelligence("Use GBrain.", {})


if __name__ == "__main__":
    unittest.main()

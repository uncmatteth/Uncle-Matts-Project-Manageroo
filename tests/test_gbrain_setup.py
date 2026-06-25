import json
import unittest

from manageroo.gbrain_setup import (
    format_gbrain_setup,
    gbrain_activation_status,
    safe_probe_record,
    summarize_gbrain_config,
    summarize_integrations_list,
    summarize_recommendation_json,
    summarize_search_modes,
    summarize_sync_status,
)


class GBrainSetupTests(unittest.TestCase):
    def test_safe_probe_record_omits_success_output(self):
        record = safe_probe_record(
            {"ok": True, "exit_code": 0, "argv": ["gbrain"], "output": "secret"}
        )
        self.assertNotIn("output", record)

    def test_summarize_gbrain_config_extracts_engine_and_embedding_model(self):
        summary = summarize_gbrain_config(
            "Config:\n"
            "  engine: postgres\n"
            "  embedding_model: ollama:nomic-embed-text\n"
            "  schema_pack: gbrain-base-v2\n"
        )
        self.assertEqual(summary["engine"], "postgres")
        self.assertEqual(summary["embedding_model"], "ollama:nomic-embed-text")
        self.assertEqual(summary["schema_pack"], "gbrain-base-v2")

    def test_activation_summarizers_extract_gbrain_setup_state(self):
        self.assertEqual(
            summarize_search_modes("Search mode (active): balanced\n"),
            {"ok": True, "active_mode": "balanced"},
        )
        recommendations = summarize_recommendation_json(
            json.dumps(
                {
                    "recommendations": [
                        {
                            "id": "autopilot",
                            "title": "Install autopilot",
                            "command": "gbrain autopilot --install",
                            "apply_policy": "operator",
                            "auto_fixable": False,
                            "ignored": "noisy",
                        }
                    ],
                    "summary": {"status": "needs_action"},
                    "brain_score": 45,
                }
            )
        )
        self.assertTrue(recommendations["ok"])
        self.assertEqual(recommendations["recommendation_count"], 1)
        self.assertEqual(
            recommendations["recommendations"][0]["command"],
            "gbrain autopilot --install",
        )
        integrations = summarize_integrations_list(
            "retrieval-reflex CONFIGURED\nx-to-brain AVAILABLE\n"
        )
        self.assertTrue(integrations["ok"])
        self.assertEqual(integrations["configured"], ["retrieval-reflex"])
        self.assertEqual(integrations["available"], ["x-to-brain"])

    def test_gbrain_activation_status_uses_official_surfaces_without_guessing(self):
        def runner(argv, timeout_seconds=60):
            command = argv[1:]
            if command == ["search", "modes"]:
                return {"ok": True, "argv": argv, "exit_code": 0, "output": "Search mode (active): balanced"}
            if command == ["onboard", "--check", "--json"]:
                return {
                    "ok": True,
                    "argv": argv,
                    "exit_code": 0,
                    "output": json.dumps(
                        {
                            "recommendations": [
                                {"command": "gbrain autopilot --install", "title": "Autopilot"}
                            ]
                        }
                    ),
                }
            if command == ["features", "--json"]:
                return {"ok": True, "argv": argv, "exit_code": 0, "output": json.dumps({"recommendations": []})}
            if command == ["integrations", "list"]:
                return {"ok": True, "argv": argv, "exit_code": 0, "output": "retrieval-reflex CONFIGURED"}
            if command == ["check-update", "--json"]:
                return {"ok": False, "argv": argv, "exit_code": 1, "output": "offline"}
            return {"ok": False, "argv": argv, "exit_code": 2, "output": "unexpected"}

        report = gbrain_activation_status("/usr/bin/gbrain", runner=runner)

        self.assertTrue(report["ok"])
        self.assertEqual(report["search"]["active_mode"], "balanced")
        self.assertEqual(report["integrations"]["configured_count"], 1)
        self.assertIn("gbrain autopilot --install", report["next_commands"])
        self.assertIn("gbrain dream --json", report["recurring_job_commands"])
        self.assertIn(
            "gbrain integrations show retrieval-reflex",
            report["integration_setup_choices"],
        )

    def test_summarize_sync_status_rejects_warning_only_json(self):
        summary = summarize_sync_status(json.dumps({"warning": "old status shape"}))
        self.assertFalse(summary["ok"])
        self.assertIn("sync", summary["error"])

    def test_summarize_sync_status_reports_sources_and_embedding_gap(self):
        summary = summarize_sync_status(
            json.dumps(
                {
                    "sync": {
                        "sources": [
                            {
                                "source_id": "site",
                                "name": "Site",
                                "local_path": "/repo",
                                "pages": 3,
                                "chunks_total": 10,
                                "chunks_unembedded": 2,
                                "embedding_coverage_pct": 80.0,
                            }
                        ],
                        "unacknowledged_failures": 1,
                    }
                }
            )
        )
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["source_count"], 1)
        self.assertEqual(summary["chunks_total"], 10)
        self.assertEqual(summary["chunks_unembedded"], 2)
        self.assertEqual(summary["embedding_coverage_min_pct"], 80.0)

    def test_format_gbrain_setup_surfaces_failed_actions(self):
        text = format_gbrain_setup(
            {
                "installed": True,
                "status": {
                    "ok": True,
                    "sources": [{"id": "site", "path": "/repo"}],
                    "source_count": 1,
                    "chunks_total": 1,
                    "chunks_unembedded": 0,
                },
                "actions": [
                    {
                        "ok": False,
                        "argv": ["gbrain", "sources", "add"],
                        "output": "bad path",
                    }
                ],
                "next_commands": [],
                "rule": "No broad scan.",
            }
        )
        self.assertIn("FAILED: gbrain sources add", text)
        self.assertIn("site: /repo", text)
        self.assertIn("bad path", text)
        self.assertIn("No broad scan.", text)

    def test_format_gbrain_setup_zero_sources_is_action_not_ok(self):
        text = format_gbrain_setup(
            {
                "installed": True,
                "status": {
                    "ok": True,
                    "sources": [],
                    "source_count": 0,
                    "chunks_total": 0,
                    "chunks_unembedded": 0,
                },
                "actions": [],
                "next_commands": ["gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder"],
                "rule": "No broad scan.",
            }
        )
        self.assertIn("GBRAIN: ACTION", text)
        self.assertIn("Sources: 0", text)
        self.assertNotIn("GBRAIN: OK", text)


if __name__ == "__main__":
    unittest.main()

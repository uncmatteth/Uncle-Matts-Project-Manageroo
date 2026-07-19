import json
import unittest

from manageroo.gbrain_setup import (
    format_gbrain_setup,
    safe_probe_record,
    summarize_gbrain_config,
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
                "ok": False,
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
        self.assertTrue(text.startswith("GBRAIN: ACTION"))
        self.assertNotIn("GBRAIN: OK", text)
        self.assertIn("FAILED: gbrain sources add", text)
        self.assertIn("site: /repo", text)
        self.assertIn("bad path", text)
        self.assertIn("No broad scan.", text)

    def test_format_gbrain_setup_zero_sources_is_action_not_ok(self):
        text = format_gbrain_setup(
            {
                "ok": False,
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

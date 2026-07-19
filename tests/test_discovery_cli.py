import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo import entrypoint
from manageroo.util import atomic_write_json


class DiscoveryCliTests(unittest.TestCase):
    def test_capacity_json_command_routes_without_main_cli(self):
        fake = {
            "platform": {"system": "Linux"},
            "cpu": {"logical_cores": 8},
            "memory": {"total_gib": 32.0},
            "gpu": {"devices": []},
            "disk": {"free_gib": 50.0},
            "manageroo_core": {
                "hardware_agnostic": True,
                "gpu_required": False,
                "auto_tunes_worker_concurrency_from_hardware": False,
            },
            "notes": [],
        }
        output = io.StringIO()
        with patch("manageroo.entrypoint.host_capacity", return_value=fake):
            with redirect_stdout(output):
                self.assertEqual(entrypoint._capacity_main([".", "--json"]), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["memory"]["total_gib"], 32.0)
        self.assertTrue(payload["manageroo_core"]["hardware_agnostic"])

    def test_decision_answer_uses_recommendation_on_empty_input(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_root = repo / ".manageroo" / "runs" / "run-1"
            planning = run_root / "artifacts" / "planning"
            planning.mkdir(parents=True)
            atomic_write_json(
                planning / "blocking-decisions.json",
                {
                    "decisions": [
                        {
                            "id": "SEC-1",
                            "question": "Keep existing authorization boundary?",
                            "why": "Changing it may expose private data.",
                            "options": ["Preserve it", "Replace it"],
                            "recommended": "Preserve it",
                            "category": "security",
                        }
                    ]
                },
            )
            output = io.StringIO()
            with patch("builtins.input", return_value=""):
                with redirect_stdout(output):
                    code = entrypoint._decisions_main(
                        ["answer", "run-1", "--repo", str(repo)]
                    )
            self.assertEqual(code, 0)
            resolved = json.loads(
                (planning / "resolved-decisions.json").read_text(encoding="utf-8")
            )
            self.assertEqual(resolved["answers"][0]["chosen"], "Preserve it")
            self.assertIn("manageroo run --continue run-1", output.getvalue())

    def test_root_help_lists_discovery_commands(self):
        text = entrypoint._root_help()
        self.assertIn("capacity", text)
        self.assertIn("decisions", text)
        self.assertIn("context only", text)


if __name__ == "__main__":
    unittest.main()

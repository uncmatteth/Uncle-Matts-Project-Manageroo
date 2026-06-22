import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from umsmfburasbofe.cli import main
from umsmfburasbofe.stack_doctor import format_stack_doctor, stack_doctor


class StackDoctorTests(unittest.TestCase):
    def test_gbrain_installed_without_sources_gets_mapping_next_steps(self):
        probes = {
            ("gbrain", "config", "show"): {
                "ok": True,
                "exit_code": 0,
                "output": "engine: postgres\nembedding_model: ollama:nomic-embed-text\nschema_pack: gbrain-base-v2\n",
            },
            ("gbrain", "status", "--json", "--section", "sync"): {
                "ok": True,
                "exit_code": 0,
                "output": json.dumps({"sync": {"sources": []}}),
            },
            ("gbrain", "doctor", "--json", "--fast"): {"ok": True, "exit_code": 0, "output": "{}"},
        }

        def which(name: str) -> str | None:
            return "/usr/bin/gbrain" if name == "gbrain" else None

        def runner(argv: list[str], timeout_seconds: int = 30) -> dict:
            key = tuple(Path(argv[0]).name if index == 0 else value for index, value in enumerate(argv))
            return probes.get(key, {"ok": False, "exit_code": 1, "output": "unexpected"})

        with tempfile.TemporaryDirectory() as temp:
            report = stack_doctor(which=which, runner=runner, home=Path(temp))

        gbrain = next(item for item in report["items"] if item["name"] == "gbrain")
        self.assertTrue(gbrain["installed"])
        self.assertFalse(gbrain["configured"])
        self.assertEqual(gbrain["status"], "needs_action")
        self.assertIn("ollama:nomic-embed-text", gbrain["detail"])
        self.assertIn("gbrain sources add YOUR_SOURCE_ID --path /absolute/path/to/folder", gbrain["next_commands"])
        self.assertFalse(report["ready"])

    def test_cli_stack_doctor_json_reports_missing_tools_without_mutation(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["stack-doctor", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["executes_changes"])
        self.assertIn("items", payload)

    def test_format_stack_doctor_is_plain_and_actionable(self):
        text = format_stack_doctor(
            {
                "ok": True,
                "ready": False,
                "executes_changes": False,
                "items": [
                    {
                        "name": "gitnexus",
                        "status": "needs_action",
                        "installed": True,
                        "configured": False,
                        "detail": "installed; setup verification still needed",
                        "next_commands": ["gitnexus setup"],
                    }
                ],
            }
        )
        self.assertIn("SMART STACK DOCTOR", text)
        self.assertIn("read-only", text)
        self.assertIn("ACTION gitnexus", text)
        self.assertIn("gitnexus setup", text)


if __name__ == "__main__":
    unittest.main()

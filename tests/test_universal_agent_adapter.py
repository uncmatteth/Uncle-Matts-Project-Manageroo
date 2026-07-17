import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.base import AgentRequest
from manageroo.adapters.budget import BudgetedAdapter
from manageroo.adapters.factory import build_adapter
from manageroo.adapters.generic import GenericAdapter
from manageroo.config import AGENT_PRESETS
from manageroo.errors import ConfigurationError


class _Result:
    def __init__(self, stdout='{"ok": true}', stderr="", passed=True):
        self.stdout = stdout
        self.stderr = stderr
        self.passed = passed


class _Runner:
    def __init__(self):
        self.calls = []

    def run(self, argv, *, cwd, timeout_seconds, input_text=None, log_name=None, **kwargs):
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
                "input_text": input_text,
                "log_name": log_name,
            }
        )
        return _Result()


def _request(root: Path) -> AgentRequest:
    prompt = root / "prompt.md"
    schema = root / "schema.json"
    output = root / "output.json"
    prompt.write_text("DO THE EXACT MANAGEROO JOB", encoding="utf-8")
    schema.write_text(
        '{"type":"object","required":["ok"],"properties":{"ok":{"type":"boolean"}}}',
        encoding="utf-8",
    )
    return AgentRequest(
        role="worker",
        prompt_path=prompt,
        schema_path=schema,
        output_path=output,
        cwd=root,
        sandbox="workspace-write",
        timeout_seconds=60,
    )


class UniversalAgentAdapterTests(unittest.TestCase):
    def test_file_path_transport_passes_schema_augmented_prompt_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            runner = _Runner()
            adapter = GenericAdapter(
                ["any-agent", "--prompt-file", "{prompt}"],
                runner,
                prompt_transport="file_path",
            )
            response = adapter.run(request)
            call = runner.calls[0]
            protocol_path = Path(call["argv"][-1])
            self.assertNotEqual(protocol_path, request.prompt_path)
            protocol = protocol_path.read_text(encoding="utf-8")
            self.assertIn("DO THE EXACT MANAGEROO JOB", protocol)
            self.assertIn("Required output protocol", protocol)
            self.assertIn('"required":["ok"]', protocol)
            self.assertIsNone(call["input_text"])
            self.assertTrue(response.data["ok"])

    def test_argument_transport_passes_prompt_and_schema_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            runner = _Runner()
            adapter = GenericAdapter(
                ["any-agent", "-p", "{prompt_text}"],
                runner,
                prompt_transport="argument",
            )
            adapter.run(request)
            call = runner.calls[0]
            self.assertIn("DO THE EXACT MANAGEROO JOB", call["argv"][-1])
            self.assertIn("Required output protocol", call["argv"][-1])
            self.assertIsNone(call["input_text"])

    def test_stdin_transport_passes_prompt_and_schema_on_stdin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            runner = _Runner()
            adapter = GenericAdapter(
                ["any-agent", "--structured"],
                runner,
                prompt_transport="stdin",
            )
            adapter.run(request)
            call = runner.calls[0]
            self.assertIn("DO THE EXACT MANAGEROO JOB", call["input_text"])
            self.assertIn("Required output protocol", call["input_text"])
            self.assertNotIn(str(request.prompt_path), call["argv"])

    def test_sandbox_mode_is_mapped_into_provider_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            runner = _Runner()
            adapter = GenericAdapter(
                ["any-agent", "--structured"],
                runner,
                prompt_transport="stdin",
                sandbox_argv={"workspace-write": ["--mode", "edit"]},
            )
            adapter.run(request)
            self.assertEqual(runner.calls[0]["argv"][-2:], ["--mode", "edit"])

    def test_transport_configuration_fails_closed_when_template_cannot_deliver_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            runner = _Runner()
            for transport in ("file_path", "argument"):
                with self.subTest(transport=transport):
                    adapter = GenericAdapter(
                        ["any-agent", "--no-prompt-here"],
                        runner,
                        prompt_transport=transport,
                    )
                    with self.assertRaises(ConfigurationError):
                        adapter.run(request)

    def test_factory_builds_same_protocol_for_any_generic_worker(self):
        runner = _Runner()
        adapter = build_adapter(
            {
                "agent": {
                    "adapter": "generic",
                    "argv_template": ["future-agent", "--json"],
                    "prompt_transport": "stdin",
                },
                "budget": {},
            },
            runner,
        )
        self.assertIsInstance(adapter, BudgetedAdapter)
        self.assertIsInstance(adapter.inner, GenericAdapter)
        self.assertEqual(adapter.inner.prompt_transport, "stdin")

    def test_claude_and_gemini_presets_use_stdin_and_provider_safety_modes(self):
        claude = AGENT_PRESETS["claude-code"]
        gemini = AGENT_PRESETS["gemini"]
        for preset in (claude, gemini):
            self.assertEqual(preset["adapter"], "generic")
            self.assertEqual(preset["prompt_transport"], "stdin")
            self.assertNotIn("{prompt_text}", preset["argv_template"])
            self.assertNotIn("{prompt}", preset["argv_template"])
        self.assertEqual(claude["sandbox_read_only_argv"], ["--permission-mode", "plan"])
        self.assertIn("--approval-mode=plan", gemini["sandbox_read_only_argv"])

    def test_generic_protocol_is_not_vendor_limited(self):
        preset = {
            "adapter": "generic",
            "executable": "future-agent",
            "argv_template": ["future-agent", "--structured"],
            "prompt_transport": "stdin",
        }
        adapter = build_adapter({"agent": preset, "budget": {}}, _Runner())
        self.assertIsInstance(adapter, BudgetedAdapter)
        self.assertIsInstance(adapter.inner, GenericAdapter)
        self.assertEqual(adapter.inner.argv_template[0], "future-agent")


if __name__ == "__main__":
    unittest.main()

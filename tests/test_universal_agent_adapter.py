import concurrent.futures
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.adapters.base import AgentRequest
from manageroo.adapters.budget import BudgetedAdapter
from manageroo.adapters.factory import build_adapter
from manageroo.adapters.generic import GenericAdapter
from manageroo.adapters.transactional import TransactionalAdapter
from manageroo.config import AGENT_PRESETS
from manageroo.errors import ConfigurationError, SafetyError


PROTECTED_SANDBOX_ARGV = {
    "read-only": ["--mode", "plan"],
    "workspace-write": ["--mode", "edit"],
}


class _Result:
    def __init__(self, stdout='{"ok": true}', stderr="", passed=True, exit_code=None):
        self.stdout = stdout
        self.stderr = stderr
        self.passed = passed
        self.exit_code = (0 if passed else 1) if exit_code is None else exit_code


class _Runner:
    def __init__(self, *, result=None):
        self.calls = []
        self.result = result or _Result()

    def run(self, argv, *, cwd, timeout_seconds, input_text=None, log_name=None, **kwargs):
        call = {
            "argv": list(argv),
            "cwd": cwd,
            "timeout_seconds": timeout_seconds,
            "input_text": input_text,
            "log_name": log_name,
        }
        if "--prompt-file" in argv:
            prompt_path = Path(argv[argv.index("--prompt-file") + 1])
            call["prompt_file_text"] = prompt_path.read_text(encoding="utf-8")
        self.calls.append(call)
        return self.result


class _ConcurrentProtocolRunner:
    def __init__(self):
        self.barrier = threading.Barrier(2)
        self.calls = []
        self._lock = threading.Lock()

    def run(self, argv, *, cwd, timeout_seconds, input_text=None, log_name=None, **kwargs):
        role = argv[argv.index("--role") + 1]
        protocol_path = Path(argv[argv.index("--prompt-file") + 1])
        self.barrier.wait(timeout=5)
        protocol_text = protocol_path.read_text(encoding="utf-8")
        with self._lock:
            self.calls.append((role, protocol_path, protocol_text))
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
    def test_concurrent_file_path_requests_use_distinct_protocol_prompts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            requests = []
            for name in ("alpha", "beta"):
                prompt = root / f"prompt-{name}.md"
                schema = root / f"schema-{name}.json"
                prompt.write_text(f"DO THE {name.upper()} JOB", encoding="utf-8")
                schema.write_text(
                    '{"title":"'
                    + name.upper()
                    + '-SCHEMA","type":"object","required":["ok"],'
                    '"properties":{"ok":{"type":"boolean"}}}',
                    encoding="utf-8",
                )
                requests.append(
                    AgentRequest(
                        role=name,
                        prompt_path=prompt,
                        schema_path=schema,
                        output_path=root / f"output-{name}.json",
                        cwd=root,
                        sandbox="workspace-write",
                        timeout_seconds=60,
                    )
                )
            runner = _ConcurrentProtocolRunner()
            adapter = GenericAdapter(
                ["any-agent", "--role", "{role}", "--prompt-file", "{prompt}"],
                runner,
                prompt_transport="file_path",
                sandbox_argv=PROTECTED_SANDBOX_ARGV,
            )

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(adapter.run, requests))

            self.assertTrue(all(response.data["ok"] for response in responses))
            self.assertEqual(len({path for _role, path, _text in runner.calls}), 2)
            captured = {role: text for role, _path, text in runner.calls}
            self.assertIn("DO THE ALPHA JOB", captured["alpha"])
            self.assertIn("ALPHA-SCHEMA", captured["alpha"])
            self.assertNotIn("BETA", captured["alpha"])
            self.assertIn("DO THE BETA JOB", captured["beta"])
            self.assertIn("BETA-SCHEMA", captured["beta"])
            self.assertNotIn("ALPHA", captured["beta"])
            self.assertTrue(all(not path.exists() for _role, path, _text in runner.calls))

    def test_file_path_transport_passes_schema_augmented_prompt_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            runner = _Runner()
            adapter = GenericAdapter(
                ["any-agent", "--prompt-file", "{prompt}"],
                runner,
                prompt_transport="file_path",
                sandbox_argv=PROTECTED_SANDBOX_ARGV,
            )
            response = adapter.run(request)
            call = runner.calls[0]
            protocol_path = Path(call["argv"][call["argv"].index("--prompt-file") + 1])
            self.assertNotEqual(protocol_path, request.prompt_path)
            protocol = call["prompt_file_text"]
            self.assertIn("DO THE EXACT MANAGEROO JOB", protocol)
            self.assertIn("Required output protocol", protocol)
            self.assertIn('"required":["ok"]', protocol)
            self.assertIsNone(call["input_text"])
            self.assertFalse(protocol_path.exists())
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
                sandbox_argv=PROTECTED_SANDBOX_ARGV,
            )
            adapter.run(request)
            call = runner.calls[0]
            prompt_argument = call["argv"][call["argv"].index("-p") + 1]
            self.assertIn("DO THE EXACT MANAGEROO JOB", prompt_argument)
            self.assertIn("Required output protocol", prompt_argument)
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
                sandbox_argv=PROTECTED_SANDBOX_ARGV,
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
                sandbox_argv=PROTECTED_SANDBOX_ARGV,
            )
            adapter.run(request)
            self.assertEqual(runner.calls[0]["argv"][-2:], ["--mode", "edit"])

    def test_missing_requested_sandbox_mode_rejects_before_provider_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            request.sandbox = "read-only"
            runner = _Runner()
            adapter = GenericAdapter(
                ["any-agent", "--structured"],
                runner,
                prompt_transport="stdin",
            )

            with self.assertRaisesRegex(ConfigurationError, "protected mode 'read-only'"):
                adapter.run(request)

            self.assertEqual(runner.calls, [])

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
                        sandbox_argv=PROTECTED_SANDBOX_ARGV,
                    )
                    with self.assertRaises(ConfigurationError):
                        adapter.run(request)

    def test_generic_doctor_rejects_incompatible_provider_cli(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "manageroo.adapters.generic.shutil.which", return_value="/usr/bin/provider"
        ):
            adapter = GenericAdapter(
                ["provider", "-p", "job"],
                _Runner(result=_Result(stdout="--prompt only")),
                prompt_transport="stdin",
                doctor_argv=["provider", "--help"],
                required_help_flags=["--prompt", "--approval-mode"],
                sandbox_argv=PROTECTED_SANDBOX_ARGV,
            )
            doctor = adapter.doctor(Path(temp))
            self.assertFalse(doctor["ok"])
            self.assertEqual(doctor["missing_required_flags"], ["--approval-mode"])

    def test_generic_doctor_accepts_compatible_provider_cli(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "manageroo.adapters.generic.shutil.which", return_value="/usr/bin/provider"
        ):
            adapter = GenericAdapter(
                ["provider", "-p", "job"],
                _Runner(result=_Result(stdout="--prompt --approval-mode")),
                prompt_transport="stdin",
                doctor_argv=["provider", "--help"],
                required_help_flags=["--prompt", "--approval-mode"],
                sandbox_argv=PROTECTED_SANDBOX_ARGV,
            )
            doctor = adapter.doctor(Path(temp))
            self.assertTrue(doctor["ok"])
            self.assertEqual(doctor["missing_required_flags"], [])
            self.assertEqual(doctor["missing_provider_sandbox_modes"], [])

    def test_generic_doctor_rejects_missing_protected_sandbox_mode(self):
        with tempfile.TemporaryDirectory() as temp, patch(
            "manageroo.adapters.generic.shutil.which", return_value="/usr/bin/provider"
        ):
            adapter = GenericAdapter(
                ["provider", "-p", "job"],
                _Runner(),
                prompt_transport="stdin",
                sandbox_argv={"workspace-write": ["--mode", "edit"]},
            )

            doctor = adapter.doctor(Path(temp))

            self.assertFalse(doctor["ok"])
            self.assertEqual(doctor["missing_provider_sandbox_modes"], ["read-only"])

    def test_factory_builds_transactional_protocol_for_any_generic_worker(self):
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
        self.assertIsInstance(adapter.inner, TransactionalAdapter)
        self.assertIsInstance(adapter.inner.inner, GenericAdapter)
        self.assertEqual(adapter.inner.inner.prompt_transport, "stdin")
        with patch(
            "manageroo.adapters.generic.shutil.which", return_value="/usr/bin/future-agent"
        ):
            doctor = adapter.doctor(Path.cwd())
        self.assertFalse(doctor["ok"])
        self.assertEqual(
            doctor["missing_provider_sandbox_modes"],
            ["read-only", "workspace-write"],
        )

    def test_transactional_generic_worker_is_rejected_without_host_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = _Runner()
            adapter = build_adapter(
                {
                    "agent": {
                        "adapter": "generic",
                        "argv_template": ["future-agent", "--structured"],
                        "prompt_transport": "stdin",
                        "sandbox_read_only_argv": ["--mode", "plan"],
                        "sandbox_workspace_write_argv": ["--mode", "edit"],
                    },
                    "budget": {},
                },
                runner,
            )
            with self.assertRaisesRegex(SafetyError, "host filesystem isolation"):
                adapter.run(_request(root))
            self.assertEqual(runner.calls, [])

    def test_claude_and_gemini_presets_use_stdin_and_provider_safety_modes(self):
        claude = AGENT_PRESETS["claude-code"]
        gemini = AGENT_PRESETS["gemini"]
        for preset in (claude, gemini):
            self.assertEqual(preset["adapter"], "generic")
            self.assertEqual(preset["prompt_transport"], "stdin")
            self.assertNotIn("{prompt_text}", preset["argv_template"])
            self.assertNotIn("{prompt}", preset["argv_template"])
            self.assertTrue(preset["doctor_argv"])
            self.assertTrue(preset["required_help_flags"])
        self.assertEqual(claude["sandbox_read_only_argv"], ["--permission-mode", "plan"])
        self.assertEqual(gemini["sandbox_read_only_argv"], ["--approval-mode=plan"])
        self.assertNotIn("--sandbox", gemini["sandbox_read_only_argv"])

    def test_generic_protocol_is_not_vendor_limited(self):
        preset = {
            "adapter": "generic",
            "executable": "future-agent",
            "argv_template": ["future-agent", "--structured"],
            "prompt_transport": "stdin",
        }
        adapter = build_adapter({"agent": preset, "budget": {}}, _Runner())
        self.assertIsInstance(adapter, BudgetedAdapter)
        self.assertIsInstance(adapter.inner, TransactionalAdapter)
        self.assertIsInstance(adapter.inner.inner, GenericAdapter)
        self.assertEqual(adapter.inner.inner.argv_template[0], "future-agent")


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.adapters.base import AgentRequest
from manageroo.adapters.codex import CodexAdapter, _BWRAP_LOOPBACK_FAILURE
from manageroo.errors import AgentExecutionError
from manageroo.runner import CommandResult


def _result(argv, cwd, *, exit_code=0, stdout="", stderr=""):
    return CommandResult(
        argv=list(argv),
        cwd=str(cwd),
        started_at="start",
        finished_at="finish",
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )


class _Runner:
    def __init__(self, results, output_path: Path | None = None):
        self.results = list(results)
        self.calls = []
        self.output_path = output_path

    def run(self, argv, *, cwd, **kwargs):
        self.calls.append(list(argv))
        result = self.results.pop(0)
        if result.exit_code == 0 and self.output_path is not None:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self.output_path.write_text('{"ok": true}', encoding="utf-8")
        return result


def _request(root: Path) -> AgentRequest:
    prompt = root / "prompt.md"
    schema = root / "schema.json"
    output = root / "output.json"
    prompt.write_text("Do bounded work.", encoding="utf-8")
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    return AgentRequest(
        role="implementer",
        prompt_path=prompt,
        schema_path=schema,
        output_path=output,
        cwd=root,
        sandbox="workspace-write",
        timeout_seconds=30,
    )


class CodexSandboxFallbackTests(unittest.TestCase):
    def test_successful_worker_cannot_spoof_diagnostic_to_trigger_unrestricted_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            initial_argv = ["codex", "exec"]
            runner = _Runner(
                [_result(initial_argv, root, stdout=_BWRAP_LOOPBACK_FAILURE)],
                output_path=request.output_path,
            )
            with patch.dict(
                "os.environ",
                {"MANAGEROO_CODEX_DANGER_FULL_ACCESS_FALLBACK": "1"},
                clear=False,
            ):
                response = CodexAdapter("codex", runner).run(request)
            self.assertTrue(response.data["ok"])
            self.assertEqual(len(runner.calls), 1)
            self.assertNotIn("danger-full-access", runner.calls[0])

    def test_genuine_host_sandbox_failure_cannot_escalate_without_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            runner = _Runner(
                [_result(["codex", "exec"], root, exit_code=1, stderr=_BWRAP_LOOPBACK_FAILURE)]
            )
            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(AgentExecutionError, "refused to escalate automatically"):
                    CodexAdapter("codex", runner).run(request)
            self.assertEqual(len(runner.calls), 1)
            self.assertNotIn("danger-full-access", runner.calls[0])

    def test_explicit_opt_in_allows_retry_only_after_failed_host_sandbox_initialization(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = _request(root)
            runner = _Runner(
                [
                    _result(["codex", "exec"], root, exit_code=1, stderr=_BWRAP_LOOPBACK_FAILURE),
                    _result(["codex", "exec"], root, exit_code=0),
                ],
                output_path=request.output_path,
            )
            with patch.dict(
                "os.environ",
                {"MANAGEROO_CODEX_DANGER_FULL_ACCESS_FALLBACK": "1"},
                clear=True,
            ):
                response = CodexAdapter("codex", runner).run(request)
            self.assertTrue(response.data["ok"])
            self.assertEqual(len(runner.calls), 2)
            self.assertNotIn("danger-full-access", runner.calls[0])
            self.assertIn("danger-full-access", runner.calls[1])


if __name__ == "__main__":
    unittest.main()

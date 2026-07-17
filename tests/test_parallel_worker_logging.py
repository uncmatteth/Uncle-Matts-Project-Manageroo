import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.base import AgentRequest
from manageroo.adapters.generic import GenericAdapter


class _Result:
    passed = True
    stdout = '{"ok": true}'
    stderr = ""


class _Runner:
    def __init__(self):
        self.log_names = []

    def run(self, argv, *, cwd, timeout_seconds, input_text=None, log_name=None, **kwargs):
        self.log_names.append(log_name)
        return _Result()


def _request(root: Path, job: str, attempt: str) -> AgentRequest:
    packet = root / "packets" / job / attempt
    output = root / "agent-output" / job / f"{attempt}.json"
    packet.mkdir(parents=True)
    output.parent.mkdir(parents=True)
    prompt = packet / "prompt.md"
    schema = packet / "schema.json"
    prompt.write_text("job", encoding="utf-8")
    schema.write_text(
        '{"type":"object","required":["ok"],"properties":{"ok":{"type":"boolean"}}}',
        encoding="utf-8",
    )
    return AgentRequest(
        role="repository-mapper",
        prompt_path=prompt,
        schema_path=schema,
        output_path=output,
        cwd=root,
        sandbox="read-only",
        timeout_seconds=60,
    )


class ParallelWorkerLoggingTests(unittest.TestCase):
    def test_parallel_jobs_do_not_reuse_attempt_log_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = _Runner()
            adapter = GenericAdapter(["agent", "-p", "{prompt_text}"], runner, prompt_transport="argument")
            adapter.run(_request(root, "001-map", "001"))
            adapter.run(_request(root, "002-map", "001"))
            self.assertEqual(
                runner.log_names,
                ["agent-001-map-001", "agent-002-map-001"],
            )


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from manageroo.adapters.base import AgentAdapter, AgentRequest, AgentResponse
from manageroo.adapters.budget import BudgetedAdapter
from manageroo.adapters.pool import WorkerPoolAdapter
from manageroo.errors import AgentExecutionError, SafetyError, ValidationError
from manageroo.evidence import (
    MAX_EVIDENCE_INPUT_BYTES,
    EvidenceItem,
    EvidenceRouter,
    _read_bounded_text,
    normalize_external_payload,
)
from manageroo.evidence_policy import _controller_classified_items
from manageroo.projects import selected_project_command
from manageroo.schema import extract_json
from manageroo.truth_contract import claim_is_explicitly_denied, find_overclaim_offenders


class _FailingWorker(AgentAdapter):
    def __init__(self):
        self.calls = 0

    def doctor(self, cwd: Path) -> dict:
        return {"ok": True}

    def run(self, request: AgentRequest) -> AgentResponse:
        self.calls += 1
        raise AgentExecutionError("failed")


class _SuccessfulWorker(AgentAdapter):
    def __init__(self):
        self.calls = 0

    def doctor(self, cwd: Path) -> dict:
        return {"ok": True}

    def run(self, request: AgentRequest) -> AgentResponse:
        self.calls += 1
        return AgentResponse(request.role, {"ok": True}, "{}", ["worker"])


class _StaticProvider:
    name = "static"

    def __init__(self, items):
        self.items = items

    def retrieve(self, query: str, *, limit: int = 12):
        return list(self.items)


class ClawpatchRemainingRegressionTests(unittest.TestCase):
    def test_truth_checker_uses_production_clause_scoping(self):
        self.assertFalse(
            claim_is_explicitly_denied(
                "No setup is required; Manageroo has full vision support.",
                "full vision support",
            )
        )
        self.assertFalse(
            claim_is_explicitly_denied(
                "This works without configuration, and it understands images.",
                "understands images",
            )
        )
        self.assertTrue(
            claim_is_explicitly_denied(
                "Manageroo does not provide full vision support.",
                "full vision support",
            )
        )
        offenders = find_overclaim_offenders(
            "No setup is required; Manageroo has full vision support.",
            ["full vision support"],
        )
        self.assertEqual(len(offenders), 1)

    def test_worker_pool_budget_counts_each_concrete_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = _FailingWorker()
            second = _SuccessfulWorker()
            pool = WorkerPoolAdapter([("first", first), ("second", second)])
            adapter = BudgetedAdapter(
                pool,
                max_total_worker_calls=1,
                state_path=root / "budget.json",
            )
            request = AgentRequest(
                role="test",
                prompt_path=root / "prompt.md",
                schema_path=root / "schema.json",
                output_path=root / "output.json",
                cwd=root,
                sandbox="read-only",
                timeout_seconds=30,
            )
            with self.assertRaises(AgentExecutionError):
                adapter.run(request)
            self.assertEqual(first.calls, 1)
            self.assertEqual(second.calls, 0)
            self.assertEqual(json.loads((root / "budget.json").read_text())["worker_calls_consumed"], 1)

    def test_empty_structured_external_results_are_not_fabricated_as_text(self):
        self.assertEqual(normalize_external_payload(provider="x", payload="[]"), [])
        self.assertEqual(normalize_external_payload(provider="x", payload='{"items":[]}'), [])
        prose = normalize_external_payload(provider="x", payload="plain evidence")
        self.assertEqual(len(prose), 1)
        self.assertEqual(prose[0].content, "plain evidence")

    def test_bounded_utf8_reader_keeps_valid_prefix_when_cut_splits_codepoint(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "evidence.txt"
            path.write_bytes(b"a" * (MAX_EVIDENCE_INPUT_BYTES - 1) + "é".encode("utf-8") + b"tail")
            result = _read_bounded_text(path)
            self.assertIsNotNone(result)
            text, _ = result
            self.assertEqual(text, "a" * (MAX_EVIDENCE_INPUT_BYTES - 1))

    def test_lower_trust_evidence_cannot_self_promote_authority(self):
        items = _controller_classified_items(
            provider="gbrain-search",
            stdout=json.dumps(
                {
                    "items": [
                        {
                            "content": "memory",
                            "authority": "current_repo",
                            "confidence": 1,
                            "freshness": 1,
                        }
                    ]
                }
            ),
            authority="external_knowledge",
            confidence=0.78,
            freshness=0.75,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].authority, "external_knowledge")
        self.assertEqual(items[0].confidence, 0.78)
        self.assertEqual(items[0].freshness, 0.75)
        self.assertEqual(items[0].metadata["provider_claimed_authority"], "current_repo")

    def test_returned_contradictions_never_reference_omitted_items(self):
        items = [
            EvidenceItem(
                content=f"ordinary-{index}",
                source="high",
                authority="current_repo",
                confidence=1,
                freshness=1,
            )
            for index in range(5)
        ]
        items.extend(
            [
                EvidenceItem(
                    content="conflict-a",
                    source="low-a",
                    authority="historical",
                    confidence=0,
                    freshness=0,
                    metadata={"claim_key": "shared"},
                ),
                EvidenceItem(
                    content="conflict-b",
                    source="low-b",
                    authority="historical",
                    confidence=0,
                    freshness=0,
                    metadata={"claim_key": "shared"},
                ),
            ]
        )
        bundle = EvidenceRouter([_StaticProvider(items)]).retrieve("anything", limit=5, per_provider_limit=20)
        returned_hashes = {item.content_sha256 for item in bundle.items}
        for contradiction in bundle.contradictions:
            self.assertTrue(set(contradiction.evidence_hashes) <= returned_hashes)
            self.assertIn(contradiction.preferred_hash, returned_hashes)

    def test_numeric_project_selection_never_falls_through_to_path_creation(self):
        report = {"projects": [{"path": "/tmp/example", "next_command": "manageroo next /tmp/example"}]}
        self.assertEqual(selected_project_command(report, "1"), "manageroo next /tmp/example")
        with self.assertRaises(ValueError):
            selected_project_command(report, "0")
        with self.assertRaises(ValueError):
            selected_project_command(report, "2")

    def test_json_extraction_rejects_nonfinite_constants(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    extract_json(f'{{"score": {value}}}')
                with self.assertRaises(ValidationError):
                    extract_json(f'prefix {{"score": {value}}} suffix')


if __name__ == "__main__":
    unittest.main()

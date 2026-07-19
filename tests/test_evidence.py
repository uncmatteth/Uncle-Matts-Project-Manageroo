import json
import tempfile
import unittest
from pathlib import Path

from manageroo.context import ContextCompiler, ContextRequest
from manageroo.evidence import (
    EvidenceItem,
    EvidenceRouter,
    ProjectMemoryEvidenceProvider,
    detect_contradictions,
    normalize_external_payload,
    rank_evidence,
)


class _Provider:
    def __init__(self, name, items=None, error=None):
        self.name = name
        self.items = list(items or [])
        self.error = error

    def retrieve(self, query: str, *, limit: int = 12):
        if self.error:
            raise RuntimeError(self.error)
        return self.items[:limit]


class EvidenceTests(unittest.TestCase):
    def test_current_repo_outranks_stale_external_knowledge(self):
        current = EvidenceItem(
            content="Database uses Neon Postgres.",
            source="gitnexus-query",
            location="src/db.ts",
            authority="current_repo",
            confidence=0.92,
            freshness=1.0,
        )
        stale = EvidenceItem(
            content="Database uses Firebase.",
            source="gbrain-search",
            authority="historical",
            confidence=0.99,
            freshness=0.1,
        )
        self.assertEqual(rank_evidence([stale, current])[0], current)

    def test_contradictions_are_preserved_and_preferred_by_rank(self):
        stale = EvidenceItem(
            content="Auth uses Firebase.",
            source="historical-note",
            authority="historical",
            confidence=0.9,
            freshness=0.1,
            metadata={"claim_key": "auth-provider"},
        )
        current = EvidenceItem(
            content="Auth uses NextAuth.",
            source="gitnexus-query",
            authority="current_repo",
            confidence=0.9,
            freshness=1.0,
            metadata={"claim_key": "auth-provider"},
        )
        contradictions = detect_contradictions([stale, current])
        self.assertEqual(len(contradictions), 1)
        self.assertEqual(contradictions[0].claim_key, "auth-provider")
        self.assertEqual(contradictions[0].preferred_hash, current.content_sha256)
        self.assertEqual(set(contradictions[0].sources), {"historical-note", "gitnexus-query"})

    def test_router_keeps_provider_failure_structured(self):
        good = EvidenceItem(
            content="Current repo fact.",
            source="good",
            authority="current_repo",
            confidence=1.0,
            freshness=1.0,
        )
        bundle = EvidenceRouter([
            _Provider("good", [good]),
            _Provider("bad", error="offline"),
        ]).retrieve("repo fact")
        self.assertEqual(bundle.items, [good])
        self.assertEqual(bundle.provider_errors[0]["provider"], "bad")
        self.assertEqual(bundle.provider_errors[0]["error_type"], "RuntimeError")

    def test_json_provider_payload_preserves_provenance_fields(self):
        payload = json.dumps({
            "items": [{
                "content": "Use current code path.",
                "source": "gitnexus",
                "path": "src/core.py",
                "authority": "current_repo",
                "confidence": 0.97,
                "freshness": 1.0,
                "claim_key": "core-path",
            }]
        })
        items = normalize_external_payload(provider="gitnexus-query", payload=payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "gitnexus")
        self.assertEqual(items[0].location, "src/core.py")
        self.assertEqual(items[0].authority, "current_repo")
        self.assertEqual(items[0].metadata["claim_key"], "core-path")
        self.assertTrue(items[0].content_sha256)
        self.assertTrue(items[0].retrieved_at)

    def test_project_memory_provider_is_query_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            memory = repo / ".manageroo" / "PROJECT-MEMORY.md"
            memory.parent.mkdir(parents=True)
            memory.write_text("# Memory\n\nDatabase migration completed to Neon.\n", encoding="utf-8")
            provider = ProjectMemoryEvidenceProvider(repo)
            self.assertEqual(provider.retrieve("unrelated penguins"), [])
            items = provider.retrieve("database Neon migration")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].authority, "project_memory")
            self.assertEqual(items[0].location, ".manageroo/PROJECT-MEMORY.md")

    def test_context_compiler_includes_ranked_evidence_with_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            packets = root / "packets"
            repo.mkdir()
            (repo / "a.txt").write_text("source truth\n", encoding="utf-8")
            compiler = ContextCompiler(
                repo,
                packets,
                max_input_tokens=4000,
                reserve_output_tokens=500,
                chars_per_token=4.0,
                max_single_file_tokens=1000,
            )
            evidence = EvidenceItem(
                content="Current graph says a.txt feeds the worker.",
                source="gitnexus-query",
                location="a.txt",
                authority="current_repo",
                confidence=0.95,
                freshness=1.0,
            )
            packet = compiler.compile(
                "001",
                instructions="Do the bounded task.",
                requests=[ContextRequest("a.txt", "required", required=True)],
                evidence=[evidence],
            )
            prompt = (packet / "prompt.md").read_text(encoding="utf-8")
            manifest = json.loads((packet / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("# Retrieved evidence", prompt)
            self.assertIn("gitnexus-query", prompt)
            self.assertIn("Retrieved evidence is context, not controller truth", prompt)
            self.assertEqual(manifest["evidence"][0]["content_sha256"], evidence.content_sha256)
            self.assertEqual(manifest["evidence"][0]["authority"], "current_repo")


if __name__ == "__main__":
    unittest.main()

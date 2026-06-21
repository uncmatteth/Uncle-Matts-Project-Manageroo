import tempfile
import unittest
from pathlib import Path

from umsmfburasbofe.context import ContextCompiler, ContextRequest
from umsmfburasbofe.errors import ContextBudgetError, SafetyError
from umsmfburasbofe.util import read_json


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
        (self.repo / "big.txt").write_text("x" * 5000, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def compiler(self, max_tokens=200):
        return ContextCompiler(
            self.repo,
            self.root / "packets",
            max_input_tokens=max_tokens,
            reserve_output_tokens=20,
            chars_per_token=1.0,
            max_single_file_tokens=100,
        )

    def test_manifest_contains_hashes_and_lines(self):
        packet = self.compiler().compile(
            "p",
            instructions="do work",
            requests=[ContextRequest("a.txt", "test", required=True, start_line=2, end_line=3)],
        )
        manifest = read_json(packet / "manifest.json")
        self.assertEqual(manifest["entries"][0]["start_line"], 2)
        self.assertEqual(manifest["entries"][0]["end_line"], 3)
        self.assertTrue(manifest["entries"][0]["source_sha256"])

    def test_instructions_alone_cannot_overflow(self):
        with self.assertRaises(ContextBudgetError):
            self.compiler(max_tokens=30).compile(
                "instructions-too-large",
                instructions="x" * 100,
                requests=[],
            )

    def test_required_context_never_silently_truncates(self):
        with self.assertRaises(ContextBudgetError):
            self.compiler().compile(
                "too-big",
                instructions="x",
                requests=[ContextRequest("big.txt", "required", required=True)],
            )

    def test_optional_context_records_omission(self):
        packet = self.compiler().compile(
            "optional",
            instructions="x",
            requests=[ContextRequest("big.txt", "optional", required=False)],
        )
        manifest = read_json(packet / "manifest.json")
        self.assertEqual(manifest["omitted"][0]["reason"], "optional_slice_too_large")

    def test_summary_mode_includes_large_prose_without_full_text(self):
        packet = self.compiler().compile(
            "summary",
            instructions="x",
            requests=[ContextRequest("big.txt", "summary", required=True, mode="summary")],
        )
        prompt = (packet / "prompt.md").read_text(encoding="utf-8")
        manifest = read_json(packet / "manifest.json")
        self.assertEqual(manifest["entries"][0]["mode"], "summary")
        self.assertIn("Generated file summary", prompt)
        self.assertNotIn("x" * 1000, prompt)

    def test_stale_packet_is_rejected(self):
        packet = self.compiler().compile(
            "fresh",
            instructions="x",
            requests=[ContextRequest("a.txt", "required", required=True)],
        )
        manifest = read_json(packet / "manifest.json")
        (self.repo / "a.txt").write_text("changed\n", encoding="utf-8")
        with self.assertRaises(SafetyError):
            self.compiler().validate_freshness(manifest)

    def test_partition_is_stable(self):
        files = [
            {"path": "b", "estimated_tokens": 6},
            {"path": "a", "estimated_tokens": 6},
            {"path": "c", "estimated_tokens": 2},
        ]
        chunks = ContextCompiler.partition_paths(files, max_tokens=8)
        self.assertEqual([[item["path"] for item in chunk] for chunk in chunks], [["a"], ["b", "c"]])


if __name__ == "__main__":
    unittest.main()

import hashlib
import tempfile
import unittest
from pathlib import Path

from manageroo.context import ContextCompiler, ContextRequest
from manageroo.errors import ContextBudgetError, SafetyError
from manageroo.util import read_json


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

    def compiler(self, max_tokens=1000):
        return ContextCompiler(
            self.repo,
            self.root / "packets",
            max_input_tokens=max_tokens,
            reserve_output_tokens=20,
            chars_per_token=1.0,
            max_single_file_tokens=100,
        )

    def test_manifest_contains_exact_source_hash_and_lines(self):
        source = self.repo / "a.txt"
        expected_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        packet = self.compiler().compile(
            "p",
            instructions="do work",
            requests=[ContextRequest("a.txt", "test", required=True, start_line=2, end_line=3)],
        )
        manifest = read_json(packet / "manifest.json")
        self.assertEqual(manifest["entries"][0]["start_line"], 2)
        self.assertEqual(manifest["entries"][0]["end_line"], 3)
        self.assertEqual(manifest["entries"][0]["source_sha256"], expected_sha256)

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

    def test_stale_packet_is_rejected_for_same_size_content_change(self):
        source = self.repo / "a.txt"
        packet = self.compiler().compile(
            "fresh",
            instructions="x",
            requests=[ContextRequest("a.txt", "required", required=True)],
        )
        manifest = read_json(packet / "manifest.json")
        original_size = source.stat().st_size
        source.write_text("ONE\ntwo\nthree\n", encoding="utf-8")
        self.assertEqual(source.stat().st_size, original_size)
        with self.assertRaises(SafetyError):
            self.compiler().validate_freshness(manifest)

    def test_failed_compile_does_not_consume_packet_name(self):
        compiler = self.compiler()
        with self.assertRaises(ContextBudgetError):
            compiler.compile(
                "retryable",
                instructions="x",
                requests=[ContextRequest("missing.txt", "required", required=True)],
            )
        self.assertFalse((self.root / "packets" / "retryable").exists())

        (self.repo / "missing.txt").write_text("now present\n", encoding="utf-8")
        packet = compiler.compile(
            "retryable",
            instructions="x",
            requests=[ContextRequest("missing.txt", "required", required=True)],
        )
        self.assertTrue((packet / "manifest.json").is_file())

    def test_serialized_prompt_overhead_is_included_in_budget(self):
        for index in range(10):
            (self.repo / f"tiny-{index}.txt").write_text("x", encoding="utf-8")
        compiler = ContextCompiler(
            self.repo,
            self.root / "packets",
            max_input_tokens=420,
            reserve_output_tokens=20,
            chars_per_token=1.0,
            max_single_file_tokens=100,
        )
        packet = compiler.compile(
            "overhead",
            instructions="x",
            requests=[
                ContextRequest(f"tiny-{index}.txt", "optional", required=False)
                for index in range(10)
            ],
        )
        manifest = read_json(packet / "manifest.json")
        prompt = (packet / "prompt.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(prompt), manifest["usable_token_budget"])
        self.assertEqual(manifest["estimated_tokens"], len(prompt))
        self.assertTrue(manifest["omitted"])

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

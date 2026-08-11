from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.document_analysis_command import analyze_document_manifest


class DocumentAnalysisCommandTests(unittest.TestCase):
    def test_bounded_text_analysis_returns_headings_and_excerpts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            workspace.mkdir()
            document = workspace / "guide.md"
            document.write_text(
                "# Start Here\n\nKeep Tommy's exact wording.\n\n## Final Check\nDone.\n",
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "summary": {"document_files": 1},
                        "files": [
                            {
                                "path": "guide.md",
                                "content_kind": "prose",
                                "language": "markdown",
                                "bytes": document.stat().st_size,
                                "line_count": 6,
                                "long_document": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = analyze_document_manifest(manifest, workspace)

            self.assertTrue(result["ok"])
            self.assertEqual(result["summary"]["analyzed"], 1)
            self.assertEqual(result["documents"][0]["headings"], ["# Start Here", "## Final Check"])
            self.assertIn("Keep Tommy's exact wording.", result["documents"][0]["opening_excerpt"])

    def test_pdf_excerpt_uses_the_hashed_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            workspace.mkdir()
            document = workspace / "guide.pdf"
            original = b"original PDF bytes"
            replacement = b"replacement PDF bytes"
            document.write_bytes(original)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({"files": [{"path": "guide.pdf", "language": "pdf"}]}),
                encoding="utf-8",
            )

            def extract(argv, **kwargs):
                document.write_bytes(replacement)
                snapshot = kwargs.get("input")
                if snapshot is None:
                    snapshot = Path(argv[-2]).read_bytes()
                return subprocess.CompletedProcess(argv, 0, stdout=snapshot, stderr=b"")

            with patch("manageroo.document_analysis_command.subprocess.run", side_effect=extract):
                result = analyze_document_manifest(manifest, workspace)

            self.assertEqual(result["documents"][0]["opening_excerpt"], original.decode())


if __name__ == "__main__":
    unittest.main()

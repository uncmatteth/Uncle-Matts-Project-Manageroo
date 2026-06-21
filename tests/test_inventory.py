import base64
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from umsmfburasbofe.file_inspection import image_dimensions, pdf_page_count
from umsmfburasbofe.inventory import build_inventory, inventory_summary
from umsmfburasbofe.runner import CommandRunner


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGA"
    "WjR9awAAAABJRU5ErkJggg=="
)


class InventoryTests(unittest.TestCase):
    def test_media_and_large_prose_are_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("# Demo\n\nShort docs.\n", encoding="utf-8")
            (repo / "hero.png").write_bytes(PNG_1X1)
            (repo / "story.txt").write_text(("Chapter heading\n\n" + "words " * 400), encoding="utf-8")

            files = build_inventory(repo, CommandRunner(), chars_per_token=3.5)
            by_path = {item.path: item for item in files}

            self.assertEqual(by_path["hero.png"].content_kind, "media")
            self.assertEqual(by_path["hero.png"].language, "image")
            self.assertIn("1x1", by_path["hero.png"].summary)
            self.assertEqual(by_path["story.txt"].content_kind, "prose")
            self.assertGreater(by_path["story.txt"].line_count, 0)
            self.assertIn("Chapter heading", by_path["story.txt"].summary)

            summary = inventory_summary(files)
            self.assertEqual(summary["content_kinds"]["media"], 1)
            self.assertEqual(summary["content_kinds"]["prose"], 2)

    def test_media_metadata_reads_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "hero.png"
            image.write_bytes(PNG_1X1 + (b"x" * 1024))
            pdf = root / "book.pdf"
            pdf.write_bytes(b"%PDF-1.7\n/Type /Page\n" + (b"x" * 1024))
            with patch("pathlib.Path.read_bytes", side_effect=AssertionError("full read")):
                self.assertEqual(image_dimensions(image), (1, 1))
                self.assertEqual(pdf_page_count(pdf), 1)


if __name__ == "__main__":
    unittest.main()

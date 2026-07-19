import base64
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.file_inspection import image_dimensions, media_summary, pdf_page_count, prose_chunks
from manageroo.inventory import build_inventory, inventory_summary
from manageroo.runner import CommandResult, CommandRunner


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGA"
    "WjR9awAAAABJRU5ErkJggg=="
)


class _CountingReader:
    def __init__(self, handle, counter):
        self._handle = handle
        self._counter = counter

    def read(self, size=-1):
        data = self._handle.read(size)
        self._counter["bytes"] += len(data)
        return data

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._handle.__exit__(exc_type, exc, tb)

    def __getattr__(self, name):
        return getattr(self._handle, name)


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
            self.assertIn("Content chunks:", by_path["story.txt"].summary)

    def test_media_metadata_reads_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = root / "hero.png"
            image.write_bytes(PNG_1X1 + (b"x" * (2 * 1024 * 1024)))
            pdf = root / "book.pdf"
            pdf.write_bytes(b"%PDF-1.7\n/Type /Page\n" + (b"x" * (10 * 1024 * 1024)))
            counters = {image: {"bytes": 0}, pdf: {"bytes": 0}}
            original_open = Path.open

            def counted_open(path, *args, **kwargs):
                handle = original_open(path, *args, **kwargs)
                resolved = path.resolve()
                counter = next((value for key, value in counters.items() if key.resolve() == resolved), None)
                return _CountingReader(handle, counter) if counter is not None else handle

            with patch("pathlib.Path.open", new=counted_open):
                self.assertEqual(image_dimensions(image), (1, 1))
                self.assertEqual(pdf_page_count(pdf), 1)

            self.assertLessEqual(counters[image]["bytes"], 512 * 1024)
            self.assertLessEqual(counters[pdf]["bytes"], 8 * 1024 * 1024)
            self.assertLess(counters[image]["bytes"], image.stat().st_size)
            self.assertLess(counters[pdf]["bytes"], pdf.stat().st_size)

    def test_prose_chunks_preserve_line_ranges(self):
        text = "# Start\n\n" + ("alpha " * 120) + "\n\n## Next\n\n" + ("beta " * 120)
        chunks = prose_chunks(text, max_chars=200, max_chunks=6)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["start_line"], 1)
        self.assertIn("Start", chunks[0]["title"])
        self.assertTrue(all(chunk["end_line"] >= chunk["start_line"] for chunk in chunks))

    def test_media_summary_uses_local_extractors_when_available(self):
        class FakeRunner:
            def run(self, argv, *, cwd, timeout_seconds=1800, **kwargs):
                return CommandResult(
                    argv=list(argv),
                    cwd=str(cwd),
                    started_at="start",
                    finished_at="finish",
                    exit_code=0,
                    stdout="OCR OR PDF TEXT",
                    stderr="",
                )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pdf = root / "book.pdf"
            pdf.write_bytes(b"%PDF-1.7\n/Type /Page\n")
            image = root / "hero.png"
            image.write_bytes(PNG_1X1)
            with patch("manageroo.file_inspection.shutil.which", return_value="/usr/bin/tool"):
                pdf_text, _ = media_summary(pdf, "book.pdf", runner=FakeRunner())
                image_text, _ = media_summary(image, "hero.png", runner=FakeRunner())
            self.assertIn("Extracted text:", pdf_text)
            self.assertIn("OCR OR PDF TEXT", pdf_text)
            self.assertIn("OCR OR PDF TEXT", image_text)


if __name__ == "__main__":
    unittest.main()

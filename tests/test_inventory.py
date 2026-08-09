import base64
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.file_inspection import image_dimensions, media_summary, pdf_page_count, prose_chunks
from manageroo.inventory import build_inventory, inventory_summary
from manageroo.runner import CommandResult, CommandRunner
from manageroo.util import sha256_file


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
    def test_inventory_uses_safe_portable_descriptor_walk_without_linux_openat2(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "docs").mkdir()
            (repo / "docs" / "guide.md").write_text("# Portable\n", encoding="utf-8")

            with patch("manageroo.integrations._openat2_syscall_number", return_value=None):
                files = build_inventory(repo, CommandRunner())

            self.assertIn("docs/guide.md", {item.path for item in files})

    def test_portable_descriptor_walk_rejects_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            outside = root / "outside"
            outside.mkdir()
            (outside / "guide.md").write_text("EXTERNAL SECRET\n", encoding="utf-8")
            try:
                (repo / "docs").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable on this platform")

            with patch("manageroo.integrations._openat2_syscall_number", return_value=None):
                files = build_inventory(repo, CommandRunner())

            self.assertNotIn("docs/guide.md", {item.path for item in files})
            self.assertNotIn("EXTERNAL SECRET", "\n".join(item.summary for item in files))

    def test_inventory_record_stays_consistent_when_file_changes_during_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            target = repo / "README.md"
            original = "# OLD\n\nold body\n"
            replacement = "# NEW\n\nnew body\n"
            self.assertEqual(len(original), len(replacement))
            target.write_text(original, encoding="utf-8")
            replaced = False

            from manageroo.inventory import _copy_inventory_descriptor

            def copy_then_replace(source_fd, destination):
                nonlocal replaced
                digest = _copy_inventory_descriptor(source_fd, destination)
                if not replaced:
                    target.write_text(replacement, encoding="utf-8")
                    replaced = True
                return digest

            with patch(
                "manageroo.inventory._copy_inventory_descriptor",
                side_effect=copy_then_replace,
            ):
                files = build_inventory(repo, CommandRunner())

            item = next(item for item in files if item.path == "README.md")
            self.assertTrue(replaced)
            self.assertEqual(item.sha256, sha256_file(target))
            self.assertEqual(item.bytes, len(replacement.encode("utf-8")))
            self.assertIn("# NEW", item.summary)
            self.assertIn(item.sha256, item.summary)

    def test_inventory_never_reads_symlink_swapped_after_descriptor_open(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            target = repo / "README.md"
            target.write_text("# INSIDE\n", encoding="utf-8")
            outside = root / "outside.md"
            outside.write_text("EXTERNAL SECRET\n", encoding="utf-8")
            swapped = False

            from manageroo.inventory import _copy_inventory_descriptor

            def swap_then_copy(source_fd, destination):
                nonlocal swapped
                if not swapped:
                    target.unlink()
                    try:
                        target.symlink_to(outside)
                    except (OSError, NotImplementedError):
                        self.skipTest("file symlinks are unavailable on this platform")
                    swapped = True
                return _copy_inventory_descriptor(source_fd, destination)

            with patch(
                "manageroo.inventory._copy_inventory_descriptor",
                side_effect=swap_then_copy,
            ):
                files = build_inventory(repo, CommandRunner())

            self.assertTrue(swapped)
            self.assertNotIn("README.md", {item.path for item in files})
            self.assertNotIn("EXTERNAL SECRET", "\n".join(item.summary for item in files))

    def test_inventory_never_opens_detached_intermediate_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            docs = repo / "docs"
            docs.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (docs / "guide.md").write_text("# INSIDE\n", encoding="utf-8")
            outside = root / "outside"
            outside.mkdir()
            (outside / "guide.md").write_text("EXTERNAL SECRET\n", encoding="utf-8")
            moved = root / "docs-pinned"
            swapped = False

            from manageroo.inventory import _open_beneath

            def swap_then_open(root_fd, relative, flags, mode=0):
                nonlocal swapped
                if relative == "docs/guide.md" and not swapped:
                    docs.rename(moved)
                    try:
                        docs.symlink_to(outside, target_is_directory=True)
                    except (OSError, NotImplementedError):
                        self.skipTest("directory symlinks are unavailable on this platform")
                    swapped = True
                return _open_beneath(root_fd, relative, flags, mode)

            with patch(
                "manageroo.inventory._open_beneath",
                side_effect=swap_then_open,
            ):
                files = build_inventory(repo, CommandRunner())

            self.assertTrue(swapped)
            self.assertNotIn("docs/guide.md", {item.path for item in files})
            self.assertNotIn("EXTERNAL SECRET", "\n".join(item.summary for item in files))

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

    def test_nested_relative_media_paths_are_resolved_once_for_extractors(self):
        class PathCheckingRunner:
            def run(self, argv, *, cwd, timeout_seconds=1800, **kwargs):
                candidate = Path(argv[2] if argv[0] == "pdftotext" else argv[1])
                self.assert_target = candidate
                if not candidate.is_absolute() or not candidate.exists():
                    raise AssertionError(f"extractor target is not a valid absolute path: {candidate}")
                return CommandResult(
                    argv=list(argv),
                    cwd=str(cwd),
                    started_at="start",
                    finished_at="finish",
                    exit_code=0,
                    stdout="nested text",
                    stderr="",
                )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            docs = root / "docs"
            docs.mkdir()
            pdf = docs / "book.pdf"
            pdf.write_bytes(b"%PDF-1.7\n/Type /Page\n")
            runner = PathCheckingRunner()
            with patch("manageroo.file_inspection.shutil.which", return_value="/usr/bin/tool"):
                text, _ = media_summary(pdf, "docs/book.pdf", runner=runner)
            self.assertIn("nested text", text)


if __name__ == "__main__":
    unittest.main()

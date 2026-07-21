import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.inventory import build_inventory
from manageroo.runner import CommandRunner


class InventoryCacheTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        return repo

    def test_unchanged_file_reuses_cached_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            (repo / "story.txt").write_text("Chapter One\n\nLots of prose.\n", encoding="utf-8")
            cache_path = Path(temp) / "file-summaries.json"
            runner = CommandRunner()
            calls = {"count": 0}

            def fake_summary(path: Path, relative: str = ""):
                calls["count"] += 1
                return (f"summary for {relative}: {path.read_text(encoding='utf-8').strip()}", 3)

            with patch("manageroo.inventory.text_summary", side_effect=fake_summary):
                first = build_inventory(repo, runner, summary_cache_path=cache_path)
                second = build_inventory(repo, runner, summary_cache_path=cache_path)

            self.assertEqual(calls["count"], 1)
            self.assertIn("Chapter One", first[0].summary)
            self.assertEqual(first[0].summary, second[0].summary)

    def test_changed_file_invalidates_cached_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            story = repo / "story.txt"
            story.write_text("first version\n", encoding="utf-8")
            cache_path = Path(temp) / "file-summaries.json"
            runner = CommandRunner()
            calls = {"count": 0}

            def fake_summary(path: Path, relative: str = ""):
                calls["count"] += 1
                return (f"{relative}: {path.read_text(encoding='utf-8').strip()}", 1)

            with patch("manageroo.inventory.text_summary", side_effect=fake_summary):
                first = build_inventory(repo, runner, summary_cache_path=cache_path)
                story.write_text("second version with different size\n", encoding="utf-8")
                second = build_inventory(repo, runner, summary_cache_path=cache_path)

            self.assertEqual(calls["count"], 2)
            self.assertIn("first version", first[0].summary)
            self.assertIn("second version", second[0].summary)
            self.assertNotEqual(first[0].summary, second[0].summary)

    def test_same_size_same_mtime_content_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            story = repo / "story.txt"
            story.write_text("AAAA\n", encoding="utf-8")
            original_stat = story.stat()
            cache_path = Path(temp) / "file-summaries.json"
            runner = CommandRunner()
            calls = {"count": 0}

            def fake_summary(path: Path, relative: str = ""):
                calls["count"] += 1
                return (path.read_text(encoding="utf-8").strip(), 1)

            with patch("manageroo.inventory.text_summary", side_effect=fake_summary):
                first = build_inventory(repo, runner, summary_cache_path=cache_path)
                story.write_text("BBBB\n", encoding="utf-8")
                os.utime(story, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
                second = build_inventory(repo, runner, summary_cache_path=cache_path)

            self.assertEqual(story.stat().st_size, original_stat.st_size)
            self.assertEqual(calls["count"], 2)
            self.assertEqual(first[0].summary, "AAAA")
            self.assertEqual(second[0].summary, "BBBB")
            self.assertNotEqual(first[0].sha256, second[0].sha256)

    def test_malformed_cached_numeric_fields_are_recomputed(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            story = repo / "story.txt"
            story.write_text("stable content\n", encoding="utf-8")
            cache_path = Path(temp) / "file-summaries.json"
            runner = CommandRunner()
            first = build_inventory(repo, runner, summary_cache_path=cache_path)
            cache = json.loads(cache_path.read_text(encoding="utf-8"))

            for field, malformed in (
                ("bytes", "invalid"),
                ("estimated_tokens", "invalid"),
                ("line_count", "invalid"),
            ):
                with self.subTest(field=field):
                    damaged = json.loads(json.dumps(cache))
                    damaged["story.txt"][field] = malformed
                    cache_path.write_text(json.dumps(damaged), encoding="utf-8")
                    calls = {"count": 0}

                    def fake_summary(path: Path, relative: str = ""):
                        calls["count"] += 1
                        return ("recomputed", 1)

                    with patch("manageroo.inventory.text_summary", side_effect=fake_summary):
                        rebuilt = build_inventory(repo, runner, summary_cache_path=cache_path)

                    self.assertEqual(calls["count"], 1)
                    self.assertEqual(rebuilt[0].summary, "recomputed")
                    self.assertEqual(rebuilt[0].sha256, first[0].sha256)


if __name__ == "__main__":
    unittest.main()

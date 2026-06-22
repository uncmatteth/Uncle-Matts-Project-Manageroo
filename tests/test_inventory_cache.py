import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.inventory import build_inventory
from manageroo.runner import CommandRunner


class InventoryCacheTests(unittest.TestCase):
    def test_unchanged_file_reuses_cached_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "story.txt").write_text("Chapter One\n\nLots of prose.\n", encoding="utf-8")
            cache_path = Path(temp) / "file-summaries.json"
            runner = CommandRunner()

            calls = {"count": 0}

            def fake_summary(path: Path, relative: str = ""):
                calls["count"] += 1
                return (f"summary for {relative}", 3)

            with patch("manageroo.inventory.text_summary", side_effect=fake_summary):
                first = build_inventory(repo, runner, summary_cache_path=cache_path)
                second = build_inventory(repo, runner, summary_cache_path=cache_path)

            self.assertEqual(calls["count"], 1)
            self.assertEqual(first[0].summary, "summary for story.txt")
            self.assertEqual(second[0].summary, "summary for story.txt")


if __name__ == "__main__":
    unittest.main()

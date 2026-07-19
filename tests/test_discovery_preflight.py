import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.discovery_preflight import _repo_text, build_discovery_preflight


class DiscoveryPreflightTests(unittest.TestCase):
    def test_repo_signals_surface_relevant_unknown_unknown_categories(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "package.json").write_text(
                '{"dependencies":{"next":"latest","stripe":"latest"}}',
                encoding="utf-8",
            )
            (repo / "schema.sql").write_text("create table users(id integer);", encoding="utf-8")
            capacity = {
                "manageroo_core": {
                    "hardware_agnostic": True,
                    "auto_tunes_worker_concurrency_from_hardware": False,
                },
                "notes": [],
            }
            preflight = build_discovery_preflight(
                repo,
                "Add login and checkout without breaking production deployment.",
                capacity,
            )
        categories = {item["category"] for item in preflight["repo_signals"]}
        self.assertIn("identity-and-access", categories)
        self.assertIn("money-and-billing", categories)
        self.assertIn("data-and-migrations", categories)
        self.assertIn("deployment-and-runtime", categories)
        self.assertIn("user-facing-quality", categories)
        self.assertIn("does not automatically change Manageroo worker concurrency", preflight["capacity_notes"][0])

    def test_repo_text_prunes_skipped_directories_before_descent(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            src = repo / "src"
            src.mkdir()
            (src / "app.py").write_text("login = True\n", encoding="utf-8")

            def bounded_walk(root, topdown=True, followlinks=False):
                dirs = ["node_modules", "src"]
                yield str(repo), dirs, []
                if "node_modules" in dirs:
                    raise AssertionError("ignored tree was not pruned before descent")
                yield str(src), [], ["app.py"]

            with patch("manageroo.discovery_preflight.os.walk", bounded_walk):
                corpus = _repo_text(repo, max_files=10)
            self.assertIn("login = true", corpus)

    def test_repo_text_stops_at_file_cap(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            for index in range(5):
                (repo / f"file-{index}.txt").write_text(f"marker-{index}\n", encoding="utf-8")
            corpus = _repo_text(repo, max_files=2, max_chars=100_000)
            markers = [f"marker-{index}" for index in range(5) if f"marker-{index}" in corpus]
            self.assertEqual(len(markers), 2)

    def test_preflight_always_reviews_recovery_observability_proof_and_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            preflight = build_discovery_preflight(
                Path(temp),
                "Change one internal function.",
                {
                    "manageroo_core": {
                        "hardware_agnostic": True,
                        "auto_tunes_worker_concurrency_from_hardware": False,
                    },
                    "notes": [],
                },
            )
        categories = {item["category"] for item in preflight["always_review"]}
        self.assertEqual(
            categories,
            {
                "failure-and-recovery",
                "observability-and-support",
                "verification-strength",
                "scope-and-non-goals",
            },
        )
        self.assertIn("ask_only_when", preflight["decision_policy"])
        self.assertIn("do_not_block_for", preflight["decision_policy"])
        self.assertTrue(
            any(
                "Manageroo host having different CPU" in item
                for item in preflight["decision_policy"]["do_not_block_for"]
            )
        )


if __name__ == "__main__":
    unittest.main()

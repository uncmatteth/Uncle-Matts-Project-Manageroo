import tempfile
import unittest
from pathlib import Path

from manageroo.discovery_preflight import build_discovery_preflight


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
                "warnings": [],
                "recommendations": {
                    "capacity_class": "strong-general-purpose",
                    "max_parallel_agent_calls": 4,
                },
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

    def test_preflight_always_reviews_recovery_observability_proof_and_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            preflight = build_discovery_preflight(
                Path(temp),
                "Change one internal function.",
                {
                    "warnings": [],
                    "recommendations": {
                        "capacity_class": "standard-development",
                        "max_parallel_agent_calls": 2,
                    },
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


if __name__ == "__main__":
    unittest.main()

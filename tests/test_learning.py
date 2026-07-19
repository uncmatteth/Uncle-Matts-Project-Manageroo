import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from manageroo.adapters.mock import MockAdapter
from manageroo.cli import main
from manageroo.learning import (
    apply_learning_card,
    generate_learning_cards,
    get_learning_card,
    pending_root,
    save_pending_learning_cards,
)
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project
from manageroo.project_memory import project_memory_path
from manageroo.util import read_json

ROOT = Path(__file__).resolve().parents[1]


def _toml_array(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


class LearningLaneTests(unittest.TestCase):
    def _fixture_repo(self, root: Path) -> Path:
        repo = root / "product"
        repo.mkdir()
        for argv in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "config", "user.name", "MANAGEROO Tests"],
            ["git", "config", "user.email", "tests@local.invalid"],
        ):
            subprocess.run(argv, cwd=repo, check=True)
        (repo / "README.md").write_text("# Product\n", encoding="utf-8")
        (repo / "test_fixture.py").write_text(
            "import unittest\nfrom pathlib import Path\n\n"
            "class FixtureTest(unittest.TestCase):\n"
            "    def test_output(self):\n"
            "        self.assertEqual(Path('manageroo_fixture.txt').read_text(), 'MANAGEROO deterministic fixture completed\\n')\n\n"
            "if __name__ == '__main__': unittest.main()\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=repo, check=True)
        initialize_project(repo, agent="mock")
        config = repo / ".manageroo" / "config.toml"
        text = config.read_text(encoding="utf-8")
        text += (
            "\n[[verification.gates]]\n"
            'id = "fixture-check"\n'
            'kind = "test"\n'
            "required = true\n"
            "timeout_seconds = 60\n"
            f"argv = {_toml_array([sys.executable, '-m', 'unittest', 'discover'])}\n"
        )
        config.write_text(text, encoding="utf-8")
        brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
        brief.write_text("# Product request\n\nCreate the deterministic fixture file.\n", encoding="utf-8")
        return repo

    def test_completed_run_card_requires_approval_before_updating_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            result = {
                "run_id": "run-123", "status": "COMPLETE", "product_summary": "Build shipped.",
                "files_changed": ["app.py"], "evidence_paths": {"run_root": str(repo / ".manageroo" / "runs" / "run-123")},
            }
            cards = generate_learning_cards(repo=repo, result=result)
            memory_cards = [card for card in cards if card["destination"] == "project-memory"]
            self.assertEqual(len(memory_cards), 1)
            self.assertEqual(memory_cards[0]["risk"], "low")
            self.assertEqual(memory_cards[0]["apply_policy"], "approval_required")
            saved = save_pending_learning_cards(repo, cards)
            card_id = memory_cards[0]["id"]
            self.assertTrue((pending_root(repo) / f"{card_id}.json").is_file())
            unapproved = apply_learning_card(repo, card_id, approve=False)
            self.assertFalse(unapproved["ok"])
            self.assertTrue(unapproved["requires_approval"])
            approved = apply_learning_card(repo, card_id, approve=True)
            self.assertTrue(approved["ok"], approved)
            self.assertIn("run run-123 completed", project_memory_path(repo).read_text(encoding="utf-8"))
            self.assertEqual(get_learning_card(repo, card_id)["card"]["status"], "applied")
            self.assertEqual(saved[0]["recurrence_count"], 1)

    def test_completed_runs_get_independent_project_memory_cards_even_after_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            first_cards = generate_learning_cards(repo=repo, result={
                "run_id": "run-a", "status": "COMPLETE", "product_summary": "First release.",
                "files_changed": ["a.py"], "evidence_paths": {"run_root": "run-a-root"},
            })
            first = next(card for card in first_cards if card["destination"] == "project-memory")
            save_pending_learning_cards(repo, first_cards)
            self.assertTrue(apply_learning_card(repo, first["id"], approve=True)["ok"])

            second_cards = generate_learning_cards(repo=repo, result={
                "run_id": "run-b", "status": "COMPLETE", "product_summary": "Second release.",
                "files_changed": ["b.py"], "evidence_paths": {"run_root": "run-b-root"},
            })
            second = next(card for card in second_cards if card["destination"] == "project-memory")
            self.assertNotEqual(first["id"], second["id"])
            saved = save_pending_learning_cards(repo, second_cards)
            self.assertTrue(any(card["id"] == second["id"] for card in saved))
            self.assertEqual(get_learning_card(repo, second["id"])["card"]["status"], "pending")

    def test_repeated_blocker_card_is_bundled_as_recurrence_not_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            result = {"run_id": "run-abc", "status": "BLOCKED", "error_type": "ValidationError", "error": "Need a smaller plan.", "evidence_paths": {"run_root": "first-run"}}
            first = save_pending_learning_cards(repo, generate_learning_cards(repo=repo, result=result))
            result["run_id"] = "run-def"
            result["evidence_paths"] = {"run_root": "second-run"}
            second = save_pending_learning_cards(repo, generate_learning_cards(repo=repo, result=result))
            self.assertEqual(first[0]["id"], second[0]["id"])
            self.assertEqual(second[0]["recurrence_count"], 2)
            self.assertEqual(second[0]["last_seen_run_id"], "run-def")

    def test_cli_lists_shows_and_requires_approval_for_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            cards = generate_learning_cards(repo=repo, result={"run_id": "run-cli", "status": "COMPLETE", "files_changed": [], "evidence_paths": {"run_root": "run-root"}})
            card_id = save_pending_learning_cards(repo, cards)[0]["id"]
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["learning", "list", str(repo), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["cards"][0]["id"], card_id)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["learning", "show", card_id, "--repo", str(repo)])
            self.assertEqual(code, 0)
            self.assertIn("Evidence:", stdout.getvalue())
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["learning", "apply", card_id, "--repo", str(repo), "--json"])
            self.assertEqual(code, 2)
            self.assertTrue(json.loads(stdout.getvalue())["requires_approval"])

    def test_orchestrator_writes_run_and_pending_learning_cards(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._fixture_repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md", mode="build", apply_on_success=True,
            )
            self.assertEqual(result["status"], "COMPLETE")
            self.assertIn("learning", result)
            self.assertGreater(result["learning"]["pending_saved"], 0)
            run_root = Path(result["evidence_paths"]["run_root"])
            learning_artifact = read_json(run_root / "artifacts" / "learning" / "improvement-cards.json")
            self.assertGreaterEqual(len(learning_artifact["cards"]), 1)
            self.assertTrue(list(pending_root(repo).glob("*.json")))

    def test_docs_and_skill_explain_approval_gated_learning(self):
        docs = (ROOT / "docs" / "LEARNING_LANE.md").read_text(encoding="utf-8")
        skill = (ROOT / "src/manageroo/assets/skills/uncle-matts-project-manageroo/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("approval-gated", docs)
        self.assertIn("manual-only", docs)
        self.assertIn("learning apply", docs)
        self.assertIn("Do not apply learning cards without explicit approval", skill)


if __name__ == "__main__":
    unittest.main()

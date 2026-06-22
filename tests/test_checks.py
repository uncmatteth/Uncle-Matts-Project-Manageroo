import subprocess
import tempfile
import unittest
import json
from pathlib import Path

from umsmfburasbofe.checks import add_check_gate, list_check_gates, suggest_check_gates
from umsmfburasbofe.project import initialize_project


class CheckCommandTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        initialize_project(repo, agent="mock")
        return repo

    def test_adds_one_real_check_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = add_check_gate(
                repo,
                gate_id="smoke",
                argv=["python3", "-m", "unittest", "discover"],
            )
            gates = list_check_gates(repo)["gates"]
            self.assertTrue(result["ok"])
            self.assertEqual(gates[0]["id"], "smoke")
            self.assertEqual(gates[0]["argv"], ["python3", "-m", "unittest", "discover"])

    def test_duplicate_check_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            add_check_gate(repo, gate_id="smoke", argv=["python3", "-m", "unittest"])
            with self.assertRaises(ValueError):
                add_check_gate(repo, gate_id="smoke", argv=["python3", "-m", "unittest"])

    def test_suggests_detected_node_scripts_as_copyable_check_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"test": "vitest", "build": "vite build"}}),
                encoding="utf-8",
            )
            (repo / "package-lock.json").write_text("{}", encoding="utf-8")

            report = suggest_check_gates(repo)

            self.assertTrue(report["ok"])
            ids = [item["id"] for item in report["suggestions"]]
            self.assertEqual(ids, ["test", "build"])
            self.assertIn(
                "umsmfburasbofe checks add test -- npm run test",
                report["suggestions"][0]["add_command"],
            )

    def test_suggests_python_compile_smoke_when_no_tests_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")

            report = suggest_check_gates(repo)

            self.assertTrue(report["ok"])
            self.assertEqual(report["suggestions"][0]["id"], "python-compile")
            self.assertEqual(report["suggestions"][0]["argv"], ["python3", "-m", "compileall", "."])
            self.assertIn("catches Python syntax errors", report["suggestions"][0]["reason"])


if __name__ == "__main__":
    unittest.main()

import subprocess
import tempfile
import unittest
from pathlib import Path

from umsmfburasbofe.checks import add_check_gate, list_check_gates
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


if __name__ == "__main__":
    unittest.main()

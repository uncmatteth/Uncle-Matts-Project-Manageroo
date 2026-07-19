import json
import shlex
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from manageroo.checks import (
    add_check_gate,
    add_first_suggested_check_gate,
    list_check_gates,
    suggest_check_gates,
)
from manageroo.config import config_template
from manageroo.project import initialize_project


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
                argv=[sys.executable, "-m", "unittest", "discover"],
            )
            gates = list_check_gates(repo)["gates"]
            self.assertTrue(result["ok"])
            self.assertEqual(gates[0]["id"], "smoke")
            self.assertEqual(gates[0]["argv"], [sys.executable, "-m", "unittest", "discover"])

    def test_duplicate_check_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            add_check_gate(repo, gate_id="smoke", argv=[sys.executable, "-m", "unittest"])
            with self.assertRaises(ValueError):
                add_check_gate(repo, gate_id="smoke", argv=[sys.executable, "-m", "unittest"])

    def test_unsafe_gate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            for gate_id in ('bad"id', "bad;touch-pwned", "bad id", "bad\nnewline"):
                with self.subTest(gate_id=gate_id), self.assertRaises(ValueError):
                    add_check_gate(repo, gate_id=gate_id, argv=[sys.executable, "-V"])

    def test_config_template_toml_escapes_gate_strings_and_argv(self):
        text = config_template(
            "mock",
            [{
                "id": 'quoted"gate',
                "kind": "test",
                "argv": [sys.executable, "-c", 'print("hello world")'],
                "required": True,
            }],
        )
        parsed = tomllib.loads(text)
        gate = parsed["verification"]["gates"][0]
        self.assertEqual(gate["id"], 'quoted"gate')
        self.assertEqual(gate["argv"], [sys.executable, "-c", 'print("hello world")'])

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
            self.assertEqual(
                shlex.split(report["suggestions"][0]["add_command"]),
                ["manageroo", "checks", "add", "test", "--", "npm", "run", "test"],
            )

    def test_suggests_python_compile_smoke_when_no_tests_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")

            report = suggest_check_gates(repo)

            self.assertTrue(report["ok"])
            self.assertEqual(report["suggestions"][0]["id"], "python-compile")
            self.assertEqual(report["suggestions"][0]["argv"], [sys.executable, "-m", "compileall", "."])
            self.assertIn("catches Python syntax errors", report["suggestions"][0]["reason"])

    def test_add_first_suggested_check_gate_writes_first_detected_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")

            result = add_first_suggested_check_gate(repo)

            self.assertTrue(result["ok"])
            self.assertEqual(result["added"]["id"], "python-compile")
            gates = list_check_gates(repo)["gates"]
            self.assertEqual(gates[0]["id"], "python-compile")
            self.assertEqual(gates[0]["argv"], [sys.executable, "-m", "compileall", "."])


if __name__ == "__main__":
    unittest.main()

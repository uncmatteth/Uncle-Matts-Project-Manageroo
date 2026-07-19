import json
import sys
import tempfile
import unittest
from pathlib import Path

from manageroo.detector import detect_gates
from manageroo.errors import ConfigurationError


class DetectorTests(unittest.TestCase):
    def test_node_scripts(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "package.json").write_text(
                json.dumps({"scripts": {"lint": "eslint .", "test": "vitest"}}),
                encoding="utf-8",
            )
            (repo / "package-lock.json").write_text("{}", encoding="utf-8")
            gates = detect_gates(repo)
            self.assertEqual([item["id"] for item in gates], ["lint", "test"])

    def test_pyright_configuration_adds_required_typecheck_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "pyproject.toml").write_text(
                "[project]\nname = 'demo'\nversion = '0.0.1'\n\n[tool.pyright]\ntypeCheckingMode = 'strict'\n",
                encoding="utf-8",
            )
            gates = detect_gates(repo)
            pyright = next(item for item in gates if item["id"] == "pyright")
            self.assertEqual(pyright["kind"], "typecheck")
            self.assertEqual(pyright["argv"], [sys.executable, "-m", "pyright"])
            self.assertTrue(pyright["required"])

    def test_pyrightconfig_json_adds_required_typecheck_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "pyrightconfig.json").write_text("{}", encoding="utf-8")
            gates = detect_gates(repo)
            self.assertIn("pyright", [item["id"] for item in gates])

    def test_multiple_lockfiles_block(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "package.json").write_text("{}", encoding="utf-8")
            (repo / "package-lock.json").write_text("{}", encoding="utf-8")
            (repo / "yarn.lock").write_text("", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                detect_gates(repo)


if __name__ == "__main__":
    unittest.main()

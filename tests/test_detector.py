import json
import tempfile
import unittest
from pathlib import Path

from umsmfburasbofe.detector import detect_gates
from umsmfburasbofe.errors import ConfigurationError


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

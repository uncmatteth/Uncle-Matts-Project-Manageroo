import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("manageroo_release_driver", ROOT / "scripts" / "release.py")
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseDriverTests(unittest.TestCase):
    def test_failed_product_proof_never_runs_packaging(self):
        proof = {
            "argv": ["python", "-m", "manageroo", "prove"],
            "exit_code": 2,
            "output": json.dumps({"ok": False, "status": "PARTIAL"}),
        }
        output = io.StringIO()
        with patch.object(sys, "argv", ["release.py", "--json"]), patch.object(
            release, "run", return_value=proof
        ) as run, redirect_stdout(output):
            code = release.main()
        self.assertEqual(code, 2)
        self.assertEqual(run.call_count, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["release_created"])
        self.assertEqual(payload["stage"], "product-proof")

    def test_complete_product_proof_runs_package_pipeline(self):
        proof = {
            "argv": ["python", "-m", "manageroo", "prove", "--json"],
            "exit_code": 0,
            "output": json.dumps({"ok": True, "status": "COMPLETE"}),
        }
        package = {
            "argv": ["python", "scripts/package_release.py"],
            "exit_code": 0,
            "output": "release paths\n",
        }
        output = io.StringIO()
        with patch.object(sys, "argv", ["release.py", "--json"]), patch.object(
            release, "run", side_effect=[proof, package]
        ) as run, redirect_stdout(output):
            code = release.main()
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["release_created"])
        self.assertEqual(payload["stage"], "complete")


if __name__ == "__main__":
    unittest.main()

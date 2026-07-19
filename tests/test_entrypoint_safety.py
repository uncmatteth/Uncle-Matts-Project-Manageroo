import tempfile
import unittest
from pathlib import Path

from manageroo.entrypoint import _run_root
from manageroo.errors import SafetyError


class EntrypointSafetyTests(unittest.TestCase):
    def test_run_root_rejects_absolute_and_traversal_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            for run_id in ("../outside", "/tmp/outside", "nested/run", "..", ".", ""):
                with self.subTest(run_id=run_id), self.assertRaises(SafetyError):
                    _run_root(repo, run_id)

    def test_run_root_accepts_single_component_id_under_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            run_root = _run_root(repo, "run-123")
            self.assertEqual(run_root, (repo.resolve() / ".manageroo" / "runs" / "run-123"))


if __name__ == "__main__":
    unittest.main()

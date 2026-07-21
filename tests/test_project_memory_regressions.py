import tempfile
import unittest
from pathlib import Path

from manageroo.project_memory import PLACEHOLDERS, ensure_project_memory


class ProjectMemoryRegressionTests(unittest.TestCase):
    def test_real_values_remove_generated_placeholders(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / ".manageroo").mkdir()
            first = ensure_project_memory(repo)
            for placeholder in PLACEHOLDERS.values():
                self.assertIn(placeholder, first["content"])

            updated = ensure_project_memory(
                repo,
                project_summary="Manageroo controls bounded coding-agent work.",
                shipped=["Version 1 released."],
                must_not=["Do not weaken verification gates."],
                proof=["python3 scripts/release.py"],
            )
            content = updated["content"]
            self.assertIn("- Manageroo controls bounded coding-agent work.", content)
            self.assertIn("- Version 1 released.", content)
            self.assertIn("- Do not weaken verification gates.", content)
            self.assertIn("- python3 scripts/release.py", content)
            for placeholder in PLACEHOLDERS.values():
                self.assertNotIn(placeholder, content)


if __name__ == "__main__":
    unittest.main()

import subprocess
import tempfile
import unittest
from pathlib import Path

from umsmfburasbofe.project import initialize_project


class ProjectInitializationTests(unittest.TestCase):
    def test_initialization_is_editor_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")
            self.assertTrue((repo / ".umsmfburasbofe" / "config.toml").exists())
            self.assertTrue(
                (
                    repo
                    / ".agents"
                    / "skills"
                    / "uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition"
                    / "SKILL.md"
                ).exists()
            )
            self.assertFalse((repo / ".vscode").exists())


if __name__ == "__main__":
    unittest.main()

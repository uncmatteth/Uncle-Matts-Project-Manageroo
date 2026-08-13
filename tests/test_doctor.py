from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from manageroo.cli import main
from manageroo.doctor import doctor
from manageroo.project import initialize_project


class DoctorScopeTests(unittest.TestCase):
    def test_doctor_explicitly_has_no_release_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            initialize_project(repo, agent="mock")

            report = doctor(repo)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["doctor", str(repo)])

        self.assertNotEqual(code, 0)
        self.assertEqual(report["diagnostic_scope"], "local-environment")
        self.assertFalse(report["release_authority"])
        self.assertEqual(report["release_command"], "manageroo release-ready")
        self.assertIn("LOCAL DIAGNOSTIC", output.getvalue())
        self.assertIn("does not approve a release", output.getvalue())


if __name__ == "__main__":
    unittest.main()

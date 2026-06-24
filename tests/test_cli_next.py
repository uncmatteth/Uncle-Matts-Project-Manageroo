import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.checks import add_check_gate
from manageroo.cli import main
from manageroo.project import initialize_project


def _install_stack_probe_shims(repo: Path) -> Path:
    tools = repo.parent / "stack-probe-tools"
    tools.mkdir(exist_ok=True)
    gbrain = tools / "gbrain"
    gbrain.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"search\" ] || { [ \"$1\" = \"call\" ] && [ \"$2\" = \"query\" ]; }; then\n"
        "  printf '%s\\n' '{\"results\":[{\"source_id\":\"fixture\",\"text\":\"readiness-probe-ok\"}]}'\n"
        "else\n"
        "  printf '%s\\n' readiness-probe-ok\n"
        "fi\n",
        encoding="utf-8",
    )
    gbrain.chmod(0o755)
    gitnexus = tools / "gitnexus"
    gitnexus.write_text("#!/bin/sh\nprintf '%s\\n' readiness-probe-ok\n", encoding="utf-8")
    gitnexus.chmod(0o755)
    return tools


def _gbrain_status_for(repo: Path) -> dict:
    return {
        "ok": True,
        "status": {
            "source_count": 1,
            "sources": [{"id": "fixture", "path": str(repo)}],
        },
    }


class CliNextTests(unittest.TestCase):
    def _which_stack(self, name: str) -> str | None:
        if name == "git":
            return "/usr/bin/git"
        tools = getattr(self, "_stack_probe_tools", None)
        if name in {"gbrain", "gitnexus"} and tools is not None:
            return str(tools / name)
        return None

    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("fixture\n", encoding="utf-8")
        return repo

    def test_uninitialized_git_repo_points_to_solo_front_door(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            stdout = io.StringIO()
            with patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ), redirect_stdout(stdout):
                code = main(["next", str(repo)])
            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("NEXT ACTION", output)
            self.assertIn("Stage: needs-setup", output)
            self.assertEqual(output.count("\nCommand:"), 1, output)
            self.assertIn(f"manageroo solo {repo}", output)
            self.assertIn('--want "Describe the first useful version"', output)

    def test_initialized_repo_without_checks_points_to_checks_suggest(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            initialize_project(repo, agent="mock")
            tools = _install_stack_probe_shims(repo)
            self._stack_probe_tools = tools
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nBuild the useful thing.\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ), patch.dict(
                os.environ,
                {"PATH": f"{tools}:{os.environ.get('PATH', '')}"},
            ), redirect_stdout(stdout):
                code = main(["next", str(repo)])
            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("Stage: needs-checks", output)
            self.assertIn("manageroo checks suggest --apply-first", output)

    def test_ready_repo_json_points_to_run_command(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            initialize_project(repo, agent="mock")
            tools = _install_stack_probe_shims(repo)
            self._stack_probe_tools = tools
            (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
                "# Product brief\n\nRepair the login flow.\n",
                encoding="utf-8",
            )
            add_check_gate(
                repo,
                gate_id="smoke",
                argv=["python3", "-m", "compileall", "."],
            )
            stdout = io.StringIO()
            with patch(
                "manageroo.readiness.gbrain_setup_status",
                return_value=_gbrain_status_for(repo),
            ), patch(
                "manageroo.readiness.helper_skill_items",
                return_value=[],
            ), patch(
                "manageroo.readiness.shutil.which",
                side_effect=self._which_stack,
            ), patch.dict(
                os.environ,
                {"PATH": f"{tools}:{os.environ.get('PATH', '')}"},
            ), redirect_stdout(stdout):
                code = main(["next", str(repo), "--mode", "repair", "--no-apply", "--json"])
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["stage"], "ready-to-run")
            self.assertEqual(
                payload["command"],
                f"manageroo run --repo {repo} --mode repair --no-apply",
            )


if __name__ == "__main__":
    unittest.main()

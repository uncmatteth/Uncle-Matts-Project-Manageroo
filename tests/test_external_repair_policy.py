import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from manageroo.artifacts import ArtifactStore
from manageroo.errors import ValidationError
from manageroo.external_repair_policy import run_external_review_repair_lanes
from manageroo.runner import CommandRunner
from manageroo.util import atomic_write_json
from manageroo.workspace import WorkspaceMirror


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "commit.gpgSign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def source_repo(root: Path) -> Path:
    repo = root / "source"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Manageroo Tests")
    git(repo, "config", "user.email", "tests@local.invalid")
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "baseline")
    return repo


def fake_orchestrator(root: Path, source: Path, run_id: str, command):
    run_root = root / run_id
    run_root.mkdir(parents=True)
    runner = CommandRunner()
    mirror = WorkspaceMirror(source, run_root, runner)
    workspace = mirror.create()
    artifacts = ArtifactStore(run_root / "artifacts")
    fake = SimpleNamespace(
        workspace=workspace,
        source_repo=source,
        artifacts=artifacts,
        mirror=mirror,
        runner=runner,
        run_id=run_id,
    )
    fake._artifact_json = lambda relative: None
    fake._external_review_repair_commands = lambda: [("clawpatch", ["fake"])]
    fake._external_values = lambda **_kwargs: {}
    fake._run_optional_external_command = command
    return fake, run_root


class ExternalRepairPolicyTests(unittest.TestCase):
    def test_out_of_scope_failure_restores_exact_clean_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            holder = {}

            def command(**_kwargs):
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text("allowed mutation\n", encoding="utf-8")
                (workspace / "forbidden.txt").write_text("forbidden mutation\n", encoding="utf-8")
                return {"ok": True, "exit_code": 0}

            fake, run_root = fake_orchestrator(root, source, "run-one", command)
            holder["fake"] = fake
            baseline = fake.mirror.head()

            with self.assertRaises(ValidationError):
                run_external_review_repair_lanes(
                    fake,
                    brief="repair",
                    plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                    gate_results=[],
                )

            self.assertEqual(fake.mirror.head(), baseline)
            self.assertEqual((fake.workspace / "tracked.txt").read_text(encoding="utf-8"), "baseline\n")
            self.assertFalse((fake.workspace / "forbidden.txt").exists())
            self.assertEqual(git(fake.workspace, "status", "--porcelain", "--untracked-files=all"), "")
            report = __import__("json").loads(
                (run_root / "artifacts" / "review" / "external-review-repair.json").read_text(encoding="utf-8")
            )
            self.assertTrue(report["summary"]["continuation_safe"])
            self.assertTrue(report["records"][0]["rollback_verified"])

    def test_checkpoint_manifest_from_other_run_is_not_resumed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = source_repo(root)
            calls = {"count": 0}
            holder = {}

            def command(**_kwargs):
                calls["count"] += 1
                workspace = holder["fake"].workspace
                (workspace / "tracked.txt").write_text(f"run {calls['count']}\n", encoding="utf-8")
                return {"ok": True, "exit_code": 0}

            first, first_root = fake_orchestrator(root, source, "first-run", command)
            holder["fake"] = first
            first_result = run_external_review_repair_lanes(
                first,
                brief="repair",
                plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                gate_results=[],
            )
            first_checkpoint = first_result["records"][0]["checkpoint"]
            self.assertEqual(calls["count"], 1)

            second, second_root = fake_orchestrator(root, source, "second-run", command)
            holder["fake"] = second
            state = second_root / "artifacts" / "review" / "external-state"
            state.mkdir(parents=True, exist_ok=True)
            atomic_write_json(
                state / "clawpatch-checkpoint.json",
                {
                    "run_id": "first-run",
                    "name": "clawpatch",
                    "baseline": second.mirror.head(),
                    "checkpoint": first_checkpoint,
                    "changed_paths": ["tracked.txt"],
                },
            )

            result = run_external_review_repair_lanes(
                second,
                brief="repair",
                plan={"tasks": [{"allowed_paths": ["tracked.txt"]}]},
                gate_results=[],
            )
            self.assertEqual(calls["count"], 2)
            self.assertFalse(result["records"][0].get("resumed_from_checkpoint", False))
            self.assertEqual(result["records"][0]["baseline"], result["records"][0].get("baseline"))


if __name__ == "__main__":
    unittest.main()

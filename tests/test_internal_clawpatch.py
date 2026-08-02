import json
import tempfile
import unittest
from pathlib import Path

from manageroo.internal_clawpatch import run_internal_clawpatch
from manageroo.runner import CommandResult
from manageroo.util import atomic_write_json


class ScriptedRunner:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.calls = []
        self.changed = []
        self.responses = [
            (["clawpatch", "init", "--json"], {"initialized": True}),
            (
                ["clawpatch", "status", "--json"],
                {"openFindings": 0, "activeLocks": 0, "lockFiles": 0},
            ),
            (["clawpatch", "map", "--json"], {"features": 2}),
            (
                ["clawpatch", "review", "--limit", "2", "--since", "source-baseline", "--json"],
                {"reviewed": 2, "findings": 2},
            ),
            (
                [
                    "clawpatch",
                    "review",
                    "--limit",
                    "2",
                    "--since",
                    "source-baseline",
                    "--dry-run",
                    "--json",
                ],
                {"dryRun": True, "wouldReview": 0},
            ),
        ]
        for suffix in ("one", "two"):
            finding_id = f"fnd_{suffix}"
            patch_id = f"pat_{suffix}"
            self.responses.extend(
                [
                    (
                        ["clawpatch", "next", "--json"],
                        {
                            "finding": {"id": finding_id, "status": "open"},
                            "next": f"clawpatch show --finding {finding_id}",
                        },
                    ),
                    (
                        ["clawpatch", "show", "--finding", finding_id, "--json"],
                        {
                            "finding": {"id": finding_id, "status": "open"},
                            "validation": ["python -m unittest"],
                            "patchAttempts": [],
                        },
                    ),
                    (
                        ["clawpatch", "fix", "--finding", finding_id, "--json"],
                        {
                            "finding": finding_id,
                            "status": "applied",
                            "patchAttempt": patch_id,
                        },
                    ),
                    (
                        ["clawpatch", "show", "--finding", finding_id, "--json"],
                        {
                            "finding": {"id": finding_id, "status": "uncertain"},
                            "validation": ["python -m unittest"],
                            "patchAttempts": [
                                {
                                    "patchAttemptId": patch_id,
                                    "findingIds": [finding_id],
                                    "filesChanged": ["tracked.txt"],
                                }
                            ],
                        },
                    ),
                    (
                        ["clawpatch", "revalidate", "--finding", finding_id, "--json"],
                        {"finding": finding_id, "outcome": "fixed"},
                    ),
                ]
            )
        self.responses.extend(
            [
                (
                    ["clawpatch", "next", "--json"],
                    {"finding": None, "status": "open", "next": "clawpatch report --status open"},
                ),
                (
                    ["clawpatch", "revalidate", "--all", "--status", "open", "--json"],
                    {"checked": 0},
                ),
                (
                    ["clawpatch", "report", "--status", "open", "--json"],
                    {"total": 0, "items": []},
                ),
                (
                    ["clawpatch", "report", "--status", "uncertain", "--json"],
                    {"total": 0, "items": []},
                ),
                (
                    ["clawpatch", "status", "--json"],
                    {"openFindings": 0, "activeLocks": 0, "lockFiles": 0},
                ),
            ]
        )

    def run(self, argv, *, cwd, timeout_seconds=1800, env=None, **kwargs):
        expected, payload = self.responses.pop(0)
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "timeout_seconds": timeout_seconds,
                "env": dict(env or {}),
                "kill_process_group": kwargs.get("kill_process_group"),
            }
        )
        if list(argv) != expected:
            raise AssertionError(f"expected {expected!r}, received {list(argv)!r}")
        if argv[1] == "fix":
            self.changed[:] = ["tracked.txt"]
        return CommandResult(
            argv=list(argv),
            cwd=str(cwd),
            started_at="start",
            finished_at="finish",
            exit_code=0,
            stdout=json.dumps(payload),
            stderr="",
        )


class TimeoutOnceRunner(ScriptedRunner):
    def __init__(self, workspace: Path):
        super().__init__(workspace)
        self.timed_out_once = False

    def run(self, argv, *, cwd, timeout_seconds=1800, env=None, **kwargs):
        if len(argv) > 1 and argv[1] == "fix" and not self.timed_out_once:
            self.timed_out_once = True
            expected, _payload = self.responses[0]
            if list(argv) != expected:
                raise AssertionError(f"expected {expected!r}, received {list(argv)!r}")
            finding_id = argv[3]
            open_show = (
                    ["clawpatch", "show", "--finding", finding_id, "--json"],
                    {
                        "finding": {"id": finding_id, "status": "open"},
                        "validation": ["python -m unittest"],
                        "patchAttempts": [],
                    },
            )
            self.responses[0:0] = [
                open_show,
                (
                    ["clawpatch", "next", "--json"],
                    {
                        "finding": {"id": finding_id, "status": "open"},
                        "next": f"clawpatch show --finding {finding_id}",
                    },
                ),
                open_show,
            ]
            self.calls.append(
                {
                    "argv": list(argv),
                    "cwd": cwd,
                    "timeout_seconds": timeout_seconds,
                    "env": dict(env or {}),
                    "kill_process_group": kwargs.get("kill_process_group"),
                }
            )
            return CommandResult(
                argv=list(argv),
                cwd=str(cwd),
                started_at="start",
                finished_at="finish",
                exit_code=124,
                stdout="",
                stderr="timed out",
                timed_out=True,
            )
        return super().run(
            argv,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
            **kwargs,
        )


class RestartRunner(ScriptedRunner):
    def __init__(self, workspace: Path):
        super().__init__(workspace)
        original = list(self.responses)
        self.responses = [
            *original[:5],
            (
                ["clawpatch", "show", "--finding", "fnd_one", "--json"],
                {
                    "finding": {"id": "fnd_one", "status": "uncertain"},
                    "validation": ["python -m unittest"],
                    "patchAttempts": [],
                },
            ),
            (
                ["clawpatch", "revalidate", "--finding", "fnd_one", "--json"],
                {"finding": "fnd_one", "outcome": "fixed"},
            ),
            *original[10:],
        ]


class InternalClawpatchTests(unittest.TestCase):
    def test_processes_every_finding_sequentially_with_clawpatch_owned_fixes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            workspace.mkdir()
            state_dir = root / "state"
            runner = ScriptedRunner(workspace)
            checkpoints = []
            gate_runs = []

            def checkpoint(message):
                checkpoints.append(message)
                runner.changed.clear()
                return f"checkpoint-{len(checkpoints)}"

            report = run_internal_clawpatch(
                runner=runner,
                workspace=workspace,
                executable="clawpatch",
                state_dir=state_dir,
                since_ref="source-baseline",
                allowed_paths=["tracked.txt"],
                head=lambda: f"head-{len(checkpoints)}",
                changed_paths=lambda _baseline: list(runner.changed),
                checkpoint=checkpoint,
                run_gates=lambda: gate_runs.append("run") or [{"ok": True}],
                preserve_and_rollback=lambda **_kwargs: {},
            )

            self.assertTrue(report["ok"])
            self.assertEqual([item["finding_id"] for item in report["fixed"]], ["fnd_one", "fnd_two"])
            self.assertEqual(len(checkpoints), 2)
            self.assertEqual(len(gate_runs), 3)
            self.assertEqual(runner.responses, [])
            fix_calls = [call for call in runner.calls if call["argv"][1] == "fix"]
            self.assertEqual(len(fix_calls), 2)
            self.assertTrue(all(call["timeout_seconds"] == 900 for call in fix_calls))
            self.assertTrue(
                all(call["env"]["CLAWPATCH_CODEX_TIMEOUT_MS"] == "900000" for call in fix_calls)
            )
            self.assertTrue(
                all(call["env"]["CLAWPATCH_CODEX_SANDBOX"] == "workspace-write" for call in fix_calls)
            )
            self.assertTrue(
                all(call["env"]["CLAWPATCH_STATE_DIR"] == str(state_dir) for call in fix_calls)
            )
            read_only_calls = [
                call
                for call in runner.calls
                if call["argv"][1] in {"map", "review", "revalidate"}
            ]
            self.assertTrue(
                all(call["env"]["CLAWPATCH_CODEX_SANDBOX"] == "read-only" for call in read_only_calls)
            )

    def test_fix_timeout_is_reconciled_and_retried_instead_of_ending_the_lane(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            workspace.mkdir()
            runner = TimeoutOnceRunner(workspace)
            checkpoints = []

            def checkpoint(message):
                checkpoints.append(message)
                runner.changed.clear()
                return f"checkpoint-{len(checkpoints)}"

            report = run_internal_clawpatch(
                runner=runner,
                workspace=workspace,
                executable="clawpatch",
                state_dir=root / "state",
                since_ref="source-baseline",
                allowed_paths=["tracked.txt"],
                head=lambda: f"head-{len(checkpoints)}",
                changed_paths=lambda _baseline: list(runner.changed),
                checkpoint=checkpoint,
                run_gates=lambda: [{"ok": True}],
                preserve_and_rollback=lambda **_kwargs: {},
                retry_wait=lambda _seconds: None,
            )

            self.assertTrue(report["ok"])
            self.assertEqual([item["finding_id"] for item in report["fixed"]], ["fnd_one", "fnd_two"])
            fixes = [call for call in runner.calls if call["argv"][1] == "fix"]
            self.assertEqual(len(fixes), 3)
            self.assertTrue(fixes[0]["kill_process_group"])
            self.assertTrue(fixes[1]["kill_process_group"])
            self.assertEqual(report["retries"][0]["finding_id"], "fnd_one")
            self.assertEqual(report["retries"][0]["reason"], "timeout")

    def test_checkpointed_finding_resumes_after_controller_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            workspace.mkdir()
            state_dir = root / "state"
            progress_path = root / "clawpatch-progress.json"
            prior_record = {
                "finding_id": "fnd_one",
                "patch_attempt": "pat_one",
                "files_changed": ["tracked.txt"],
                "gates": [{"ok": True}],
                "checkpoint": "checkpoint-1",
            }
            atomic_write_json(
                progress_path,
                {
                    "phase": "repairing",
                    "since_ref": "source-baseline",
                    "commands": [],
                    "retries": [],
                    "fixed": [],
                    "active": {
                        "phase": "checkpointed",
                        "finding_id": "fnd_one",
                        "baseline": "head-0",
                        "checkpoint": "checkpoint-1",
                        "record": prior_record,
                    },
                },
            )
            runner = RestartRunner(workspace)
            checkpoints = ["checkpoint-1"]

            def checkpoint(_message):
                checkpoints.append(f"checkpoint-{len(checkpoints) + 1}")
                runner.changed.clear()
                return checkpoints[-1]

            report = run_internal_clawpatch(
                runner=runner,
                workspace=workspace,
                executable="clawpatch",
                state_dir=state_dir,
                since_ref="source-baseline",
                progress_path=progress_path,
                allowed_paths=["tracked.txt"],
                head=lambda: checkpoints[-1],
                changed_paths=lambda _baseline: list(runner.changed),
                checkpoint=checkpoint,
                run_gates=lambda: [{"ok": True}],
                preserve_and_rollback=lambda **_kwargs: {},
                retry_wait=lambda _seconds: None,
            )

            self.assertTrue(report["ok"])
            self.assertEqual([item["finding_id"] for item in report["fixed"]], ["fnd_one", "fnd_two"])
            self.assertTrue(report["fixed"][0]["resumed_after_controller_restart"])
            self.assertEqual(runner.responses, [])


if __name__ == "__main__":
    unittest.main()

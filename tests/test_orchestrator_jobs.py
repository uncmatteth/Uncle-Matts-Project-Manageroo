import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from manageroo.adapters.mock import MockAdapter
from manageroo.adapters.base import AgentAdapter, AgentRequest, AgentResponse
from manageroo.cli import main, parser
from manageroo.errors import AgentExecutionError, BlockingDecisionError, SafetyError, ValidationError
from manageroo.orchestrator import Orchestrator
from manageroo.project import initialize_project
from manageroo.util import read_json
from tests.stack_shims import (
    gbrain_capture_command,
    gbrain_search_command,
    gitnexus_analyze_command,
    gitnexus_status_command,
    text_command,
)


def _toml_array(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


class OrchestratorJobCliTests(unittest.TestCase):
    def setUp(self):
        self._gbrain_source_patch = patch(
            "manageroo.orchestrator.gbrain_repo_source_item",
            return_value={
                "name": "gbrain",
                "ok": True,
                "detail": "test repo-scoped source is mapped",
                "next": "",
                "required": True,
                "matched_sources": [{"id": "fixture"}],
            },
        )
        self._gbrain_source_patch.start()

    def tearDown(self):
        self._gbrain_source_patch.stop()

    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        for argv in (
            ["git", "init", "-q", "-b", "main"],
            ["git", "config", "user.name", "MANAGEROO Tests"],
            ["git", "config", "user.email", "tests@local.invalid"],
        ):
            subprocess.run(argv, cwd=repo, check=True)
        (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
        (repo / "test_fixture.py").write_text(
            "import unittest\n"
            "from pathlib import Path\n\n"
            "class FixtureTest(unittest.TestCase):\n"
            "    def test_output(self):\n"
            "        self.assertEqual(Path('manageroo_fixture.txt').read_text(), "
            "'MANAGEROO deterministic fixture completed\\n')\n\n"
            "if __name__ == '__main__': unittest.main()\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
        initialize_project(repo, agent="mock")
        probe_dir = root / "operator-bin"
        probe_dir.mkdir()
        gbrain_probe = probe_dir / "gbrain-readiness-probe"
        gitnexus_probe = probe_dir / "gitnexus-readiness-probe"
        for probe in (gbrain_probe, gitnexus_probe):
            probe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            probe.chmod(0o755)
        config = repo / ".manageroo" / "config.toml"
        text = config.read_text(encoding="utf-8")
        text = text.replace(
            "gbrain_readiness_probe_command = []",
            "gbrain_readiness_probe_command = " + _toml_array([str(gbrain_probe)]),
        )
        text = text.replace(
            "gitnexus_readiness_probe_command = []",
            "gitnexus_readiness_probe_command = " + _toml_array([str(gitnexus_probe)]),
        )
        text = text.replace(
            'gbrain_search_command = ["gbrain", "call", "query", "{gbrain_query_payload}"]',
            "gbrain_search_command = " + _toml_array(gbrain_search_command()),
        )
        text = text.replace(
            'gbrain_capture_command = ["gbrain", "capture", "--file", "{report_file}"]',
            "gbrain_capture_command = " + _toml_array(gbrain_capture_command()),
        )
        text = text.replace(
            'gitnexus_analyze_command = ["gitnexus", "analyze", "{workspace}", "--skip-agents-md", "--skip-skills"]',
            "gitnexus_analyze_command = " + _toml_array(gitnexus_analyze_command()),
        )
        text = text.replace(
            'gitnexus_status_command = ["gitnexus", "status"]',
            "gitnexus_status_command = " + _toml_array(gitnexus_status_command()),
        )
        text += (
            "\n[[verification.gates]]\n"
            'id = "fixture-check"\n'
            'kind = "test"\n'
            "required = true\n"
            "timeout_seconds = 60\n"
            f"argv = {_toml_array([sys.executable, '-m', 'unittest', 'discover'])}\n"
        )
        config.write_text(text, encoding="utf-8")
        (repo / ".manageroo" / "PRODUCT-BRIEF.md").write_text(
            "# Product request\n\nCreate the fixture file.\n",
            encoding="utf-8",
        )
        return repo

    def test_mock_run_creates_job_records_and_status_summary(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            run_root = Path(result["evidence_paths"]["run_root"])
            self.assertTrue((run_root / "controller" / "truth.json").is_file())
            self.assertTrue((run_root / "controller" / "phase-journal.jsonl").is_file())
            self.assertTrue(list((run_root / "jobs").glob("*.json")))
            self.assertTrue(list((run_root / "worker-attempts").glob("*/*.json")))

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["status", result["run_id"], "--repo", str(repo)])
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "COMPLETE")
            self.assertGreater(payload["jobs"]["completed_jobs"], 0)
            self.assertEqual(payload["jobs"]["failed_attempts"], 0)

    def test_run_continue_uses_continue_id_without_resume_command(self):
        help_stdout = io.StringIO()
        with redirect_stdout(help_stdout), self.assertRaises(SystemExit):
            parser().parse_args(["run", "--help"])
        commands = help_stdout.getvalue()
        self.assertIn("--continue", commands)
        self.assertNotIn("resume", commands.lower())

        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            calls: dict[str, object] = {}

            class FakeOrchestrator:
                def __init__(self, repo, *, run_id=None, continue_existing=False):
                    self.repo = repo
                    self.run_id = run_id
                    self.continuing = continue_existing
                    self.run_root = Path(repo) / ".manageroo" / "runs" / str(run_id)

                def run(self, *, brief_path, mode, apply_on_success=None):
                    calls["run_id"] = self.run_id
                    calls["continuing"] = self.continuing
                    return {
                        "run_id": self.run_id,
                        "status": "COMPLETE",
                        "evidence_paths": {"run_root": str(self.run_root)},
                    }

            with patch("manageroo.cli.Orchestrator", FakeOrchestrator):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    code = main([
                        "run",
                        "--repo",
                        str(repo),
                        "--continue",
                        "manageroo-existing-run",
                    ])

            self.assertEqual(code, 0)
            self.assertEqual(calls["run_id"], "manageroo-existing-run")
            self.assertTrue(calls["continuing"])

            stderr = io.StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit):
                parser().parse_args(["resume"])

    def test_continue_completed_run_returns_saved_result(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            class ExplodingAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    raise AssertionError("completed run should not launch workers")

            continued = Orchestrator(
                repo,
                adapter=ExplodingAdapter(),
                run_id=result["run_id"],
                continue_existing=True,
            ).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(continued["run_id"], result["run_id"])
            self.assertEqual(continued["status"], "COMPLETE")

    def test_continue_completed_applied_run_repairs_missing_capture_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=True,
            )
            run_root = Path(result["evidence_paths"]["run_root"])
            final_result_path = run_root / "delivery" / "final-result.json"
            capture_path = run_root / "artifacts" / "delivery" / "external-capture.json"
            saved = read_json(final_result_path)
            saved.pop("external_capture", None)
            final_result_path.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
            capture_path.unlink()

            class ExplodingAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    raise AssertionError("completed capture repair should not launch workers")

            continued = Orchestrator(
                repo,
                adapter=ExplodingAdapter(),
                run_id=result["run_id"],
                continue_existing=True,
            ).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=True,
            )

            self.assertEqual(continued["status"], "COMPLETE")
            self.assertTrue(continued["applied_to_source"])
            self.assertTrue(continued["external_capture"]["summary"]["passed"])
            self.assertTrue(capture_path.is_file())
            saved_after = read_json(final_result_path)
            self.assertTrue(saved_after["external_capture"]["summary"]["passed"])

    def test_continue_completed_unapplied_run_repairs_missing_capture_sidecar_before_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )
            run_root = Path(result["evidence_paths"]["run_root"])
            final_result_path = run_root / "delivery" / "final-result.json"
            capture_path = run_root / "artifacts" / "delivery" / "external-capture.json"
            self.assertTrue(read_json(final_result_path)["external_capture"]["summary"]["passed"])
            capture_path.unlink()

            class ExplodingAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    raise AssertionError("capture repair should not launch workers")

            continued = Orchestrator(
                repo,
                adapter=ExplodingAdapter(),
                run_id=result["run_id"],
                continue_existing=True,
            ).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=True,
            )

            self.assertEqual(continued["status"], "COMPLETE")
            self.assertTrue(continued["applied_to_source"])
            self.assertTrue(capture_path.is_file())
            self.assertTrue(read_json(final_result_path)["external_capture"]["summary"]["passed"])
            journal_path = run_root / "controller" / "phase-journal.jsonl"
            journal = [
                json.loads(line)
                for line in journal_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertFalse(
                any(event["reason"] == "Required external capture proof repaired" for event in journal)
            )
            apply_events = [
                event
                for event in journal
                if event["reason"] == "Previously completed delivery patch is applied to source"
            ]
            self.assertEqual(apply_events[-1]["from"], "DELIVERING")
            self.assertEqual(apply_events[-1]["to"], "COMPLETE")

    def test_continue_completed_unapplied_run_blocks_repo_local_capture_command(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )
            run_root = Path(result["evidence_paths"]["run_root"])
            capture_path = run_root / "artifacts" / "delivery" / "external-capture.json"
            capture_path.unlink()
            marker = repo / "repo-local-capture-ran.txt"
            evil = repo / "tools" / "evil-capture"
            evil.parent.mkdir(exist_ok=True)
            evil.write_text(
                "#!/bin/sh\n"
                f"printf ran > {marker}\n"
                "exit 0\n",
                encoding="utf-8",
            )
            evil.chmod(0o755)
            config = repo / ".manageroo" / "config.toml"
            text = config.read_text(encoding="utf-8")
            text = "\n".join(
                'gbrain_capture_command = ["tools/evil-capture", "{report_file}"]'
                if line.startswith("gbrain_capture_command = ")
                else line
                for line in text.splitlines()
            ) + "\n"
            config.write_text(text, encoding="utf-8")

            class ExplodingAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    raise AssertionError("capture safety failure should not launch workers")

            with self.assertRaisesRegex(ValidationError, "Required external capture lane failed"):
                Orchestrator(
                    repo,
                    adapter=ExplodingAdapter(),
                    run_id=result["run_id"],
                    continue_existing=True,
                ).run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=True,
                )
            self.assertFalse(marker.exists())
            self.assertTrue(capture_path.is_file())
            capture = read_json(capture_path)
            self.assertFalse(capture["summary"]["passed"])
            self.assertIn("operator-owned outside the target repo", capture["records"][0]["error"])

    def test_failed_completed_capture_repair_marks_run_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )
            run_root = Path(result["evidence_paths"]["run_root"])
            final_result_path = run_root / "delivery" / "final-result.json"
            capture_path = run_root / "artifacts" / "delivery" / "external-capture.json"
            capture_path.unlink()

            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                "\n".join(
                    "gbrain_capture_command = "
                    + _toml_array(text_command("gbrain-capture-fail", "GBRAIN CAPTURE FAIL", exit_code=7))
                    if line.startswith("gbrain_capture_command = ")
                    else line
                    for line in config.read_text(encoding="utf-8").splitlines()
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValidationError, "Required external capture lane failed"):
                Orchestrator(
                    repo,
                    adapter=MockAdapter(),
                    run_id=result["run_id"],
                    continue_existing=True,
                ).run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=False,
                )

            self.assertEqual(read_json(run_root / "state.json")["phase"], "BLOCKED")
            failure = read_json(run_root / "delivery" / "failure.json")
            self.assertEqual(failure["status"], "BLOCKED")
            capture = read_json(capture_path)
            self.assertFalse(capture["summary"]["passed"])

    def test_continue_blocked_worker_run_retries_from_disk(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "max_worker_attempts = 2",
                    "max_worker_attempts = 1",
                ),
                encoding="utf-8",
            )

            class FailingProductAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    if request.role == "product-analyst":
                        raise AgentExecutionError("simulated dead disposable worker")
                    return super().run(request)

            failed = Orchestrator(repo, adapter=FailingProductAdapter())
            with self.assertRaises(AgentExecutionError):
                failed.run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=False,
                )
            run_id = failed.run_id
            failed_attempts = list(
                (repo / ".manageroo" / "runs" / run_id / "worker-attempts").glob("*/*.json")
            )
            self.assertEqual(len(failed_attempts), 1)

            result = Orchestrator(
                repo,
                adapter=MockAdapter(),
                run_id=run_id,
                continue_existing=True,
            ).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(result["status"], "COMPLETE")
            product_attempts = sorted(
                (repo / ".manageroo" / "runs" / run_id / "worker-attempts" / "001-product-analyst").glob("*.json")
            )
            self.assertEqual([path.stem for path in product_attempts], ["001", "002"])

    def test_continue_waiting_for_product_decisions_does_not_proceed(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))

            class DecisionAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    if request.role == "product-analyst":
                        data = {
                            "product_name": "Fixture Product",
                            "goal": "Satisfy the supplied product brief.",
                            "personas": [{"name": "operator", "need": "a working product"}],
                            "capabilities": [{"id": "CAP-001", "name": "Risky capability", "description": "Needs choice."}],
                            "user_journeys": [],
                            "non_goals": [],
                            "constraints": [],
                            "acceptance_outcomes": ["Configured verification gates pass."],
                            "assumptions": [],
                            "blocking_decisions": [{
                                "id": "DEC-001",
                                "question": "Should this perform an irreversible migration?",
                                "category": "data",
                                "options": ["yes", "no"],
                                "recommended": "",
                                "reversible": False,
                                "chosen": "",
                            }],
                        }
                        return AgentResponse(role=request.role, data=data, raw_text="", command=["mock"])
                    return super().run(request)

            first = Orchestrator(repo, adapter=DecisionAdapter())
            with self.assertRaises(BlockingDecisionError):
                first.run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=False,
                )
            self.assertTrue(
                (
                    repo
                    / ".manageroo"
                    / "runs"
                    / first.run_id
                    / "artifacts"
                    / "planning"
                    / "blocking-decisions.json"
                ).is_file()
            )

            continued = Orchestrator(
                repo,
                adapter=MockAdapter(),
                run_id=first.run_id,
                continue_existing=True,
            )
            with self.assertRaisesRegex(BlockingDecisionError, "Resolve product decisions"):
                continued.run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=False,
                )

    def test_continue_after_later_worker_failure_reuses_original_job_id(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "max_worker_attempts = 2",
                    "max_worker_attempts = 1",
                ),
                encoding="utf-8",
            )

            class FailingPlanAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    if request.role == "plan-compiler":
                        raise AgentExecutionError("simulated later worker failure")
                    return super().run(request)

            failed = Orchestrator(repo, adapter=FailingPlanAdapter())
            with self.assertRaises(AgentExecutionError):
                failed.run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=False,
                )
            run_root = repo / ".manageroo" / "runs" / failed.run_id
            plan_jobs_before = [
                read_json(path)
                for path in sorted((run_root / "jobs").glob("*.json"))
                if read_json(path)["role"] == "plan-compiler"
            ]
            self.assertEqual(len(plan_jobs_before), 1)
            plan_job_id = plan_jobs_before[0]["id"]

            result = Orchestrator(
                repo,
                adapter=MockAdapter(),
                run_id=failed.run_id,
                continue_existing=True,
            ).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(result["status"], "COMPLETE")
            plan_jobs_after = [
                read_json(path)
                for path in sorted((run_root / "jobs").glob("*.json"))
                if read_json(path)["role"] == "plan-compiler"
            ]
            self.assertEqual([job["id"] for job in plan_jobs_after], [plan_job_id])
            attempts = sorted((run_root / "worker-attempts" / plan_job_id).glob("*.json"))
            self.assertEqual([path.stem for path in attempts], ["001", "002"])

    def test_resumed_worker_gets_new_retry_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))

            class AlwaysFailProductAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    if request.role == "product-analyst":
                        raise AgentExecutionError("first process cannot analyze")
                    return super().run(request)

            failed = Orchestrator(repo, adapter=AlwaysFailProductAdapter())
            with self.assertRaises(AgentExecutionError):
                failed.run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=False,
                )

            class FailOnceThenRecoverAdapter(MockAdapter):
                def __init__(self):
                    self.product_calls = 0

                def run(self, request: AgentRequest) -> AgentResponse:
                    if request.role == "product-analyst":
                        self.product_calls += 1
                        if self.product_calls == 1:
                            raise AgentExecutionError("first resumed attempt fails")
                    return super().run(request)

            result = Orchestrator(
                repo,
                adapter=FailOnceThenRecoverAdapter(),
                run_id=failed.run_id,
                continue_existing=True,
            ).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(result["status"], "COMPLETE")
            attempts = sorted(
                (
                    repo
                    / ".manageroo"
                    / "runs"
                    / failed.run_id
                    / "worker-attempts"
                    / "001-product-analyst"
                ).glob("*.json")
            )
            self.assertEqual([path.stem for path in attempts], ["001", "002", "003", "004"])

    def test_continue_completed_unapplied_run_applies_only_delivery_step(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )
            self.assertFalse((repo / "manageroo_fixture.txt").exists())

            class ExplodingAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    raise AssertionError("continuing unapplied delivery should not launch workers")

            continued = Orchestrator(
                repo,
                adapter=ExplodingAdapter(),
                run_id=result["run_id"],
                continue_existing=True,
            ).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=True,
            )

            self.assertEqual(continued["status"], "COMPLETE")
            self.assertTrue(continued["applied_to_source"])
            self.assertEqual(
                (repo / "manageroo_fixture.txt").read_text(encoding="utf-8"),
                "MANAGEROO deterministic fixture completed\n",
            )

    def test_continue_completed_unapplied_run_blocks_applied_patch_plus_source_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )
            patch_path = Path(result["evidence_paths"]["patch"])
            subprocess.run(["git", "apply", "--binary", str(patch_path)], cwd=repo, check=True)
            (repo / "README.md").write_text("# Fixture\noutside edit\n", encoding="utf-8")

            class ExplodingAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    raise AssertionError("contaminated delivery continue should not launch workers")

            with self.assertRaisesRegex(SafetyError, "Source tree does not match approved delivery patch"):
                Orchestrator(
                    repo,
                    adapter=ExplodingAdapter(),
                    run_id=result["run_id"],
                    continue_existing=True,
                ).run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=True,
                )

    def test_continue_completed_unapplied_run_blocks_applied_patch_plus_extra_file(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )
            patch_path = Path(result["evidence_paths"]["patch"])
            subprocess.run(["git", "apply", "--binary", str(patch_path)], cwd=repo, check=True)
            (repo / "outside.txt").write_text("outside edit\n", encoding="utf-8")

            class ExplodingAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    raise AssertionError("contaminated delivery continue should not launch workers")

            with self.assertRaisesRegex(SafetyError, "Source tree does not match approved delivery patch"):
                Orchestrator(
                    repo,
                    adapter=ExplodingAdapter(),
                    run_id=result["run_id"],
                    continue_existing=True,
                ).run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=True,
                )


if __name__ == "__main__":
    unittest.main()

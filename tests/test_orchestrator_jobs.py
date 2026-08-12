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
from manageroo.intent_lock import capture_intent_lock, read_intent_lock
from manageroo.orchestrator import Orchestrator, _compact_json, _partition_json_artifacts
from manageroo.project import initialize_project
from manageroo.util import atomic_write_json, read_json, sha256_file


def _toml_array(items):
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


class OrchestratorJobCliTests(unittest.TestCase):
    def test_system_map_reducer_inputs_are_partitioned_below_the_prompt_budget(self):
        parts = [
            {"chunk_id": f"chunk-{index}", "modules": [{"detail": "x" * 32_000}]}
            for index in range(8)
        ]

        batches = _partition_json_artifacts(parts, max_chars=80_000)

        self.assertGreater(len(batches), 1)
        self.assertEqual([item for batch in batches for item in batch], parts)
        self.assertTrue(all(len(_compact_json(batch)) <= 80_000 for batch in batches))

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
        config = repo / ".manageroo" / "config.toml"
        text = config.read_text(encoding="utf-8")
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
                code = main(
                    ["status", result["run_id"], "--repo", str(repo), "--json"]
                )
            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "COMPLETE")
            self.assertGreater(payload["jobs"]["completed_jobs"], 0)
            self.assertEqual(payload["jobs"]["failed_attempts"], 0)

    def test_obsidian_export_failure_cannot_leave_applied_source_or_complete_result(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            with patch(
                "manageroo.orchestrator.ObsidianIntegration.export",
                side_effect=RuntimeError("forced export failure"),
            ), self.assertRaisesRegex(RuntimeError, "forced export failure"):
                controller = Orchestrator(repo, adapter=MockAdapter())
                controller.run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=True,
                )
            self.assertFalse((repo / "manageroo_fixture.txt").exists())
            final = read_json(controller.run_root / "delivery" / "final-result.json")
            self.assertEqual(final["status"], "BLOCKED")
            self.assertFalse(final.get("applied_to_source", False))
            self.assertEqual(read_json(controller.state_path)["phase"], "BLOCKED")

    def test_late_complete_transition_failure_rolls_back_exact_applied_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            controller = Orchestrator(repo, adapter=MockAdapter())
            real_transition = controller._transition

            def fail_complete(phase, reason):
                if phase.value == "COMPLETE":
                    raise RuntimeError("forced receipt failure")
                return real_transition(phase, reason)

            with patch.object(controller, "_transition", side_effect=fail_complete), self.assertRaisesRegex(
                RuntimeError, "forced receipt failure"
            ):
                controller.run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=True,
                )
            self.assertFalse((repo / "manageroo_fixture.txt").exists())
            final = read_json(controller.run_root / "delivery" / "final-result.json")
            self.assertEqual(final["status"], "BLOCKED")
            self.assertFalse(final["applied_to_source"])

    def test_interrupted_apply_transaction_is_recovered_before_continuation(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )
            run_root = Path(result["evidence_paths"]["run_root"])
            patch_path = run_root / "delivery" / "final.patch"
            subprocess.run(
                ["git", "apply", "--binary", str(patch_path)], cwd=repo, check=True
            )
            atomic_write_json(
                run_root / "delivery" / "delivery-transaction.json",
                {
                    "status": "APPLYING",
                    "patch": str(patch_path),
                    "patch_sha256": sha256_file(patch_path),
                },
            )
            state = read_json(run_root / "state.json")
            state["phase"] = "DELIVERING"
            atomic_write_json(run_root / "state.json", state)

            controller = Orchestrator(
                repo,
                adapter=MockAdapter(),
                run_id=result["run_id"],
                continue_existing=True,
            )
            controller._recover_incomplete_delivery()

            self.assertFalse((repo / "manageroo_fixture.txt").exists())
            self.assertFalse(
                (run_root / "delivery" / "delivery-transaction.json").exists()
            )

    def test_exact_task_skips_model_discovery_mapping_and_planning(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            roles: list[str] = []

            class RecordingAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    roles.append(request.role)
                    return super().run(request)

            result = Orchestrator(repo, adapter=RecordingAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
                exact_task={
                    "targets": ["manageroo_fixture.txt"],
                    "sources": [],
                    "exclusions": ["Do not edit any other product file."],
                    "proofs": ["The deterministic fixture exists with the expected contents."],
                    "gate_ids": ["fixture-check"],
                },
            )

            self.assertEqual(result["status"], "COMPLETE")
            for skipped in (
                "product-analyst",
                "reuse-researcher",
                "repository-mapper",
                "map-reducer",
                "plan-compiler",
                "plan-reviewer",
            ):
                self.assertNotIn(skipped, roles)
            self.assertIn("implementer", roles)
            self.assertIn("reviewer", roles)

    def test_blocked_implementer_scope_expansion_stops_before_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))

            class ScopeExpansionAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    response = super().run(request)
                    if request.role == "implementer":
                        response.data["status"] = "blocked"
                        response.data["scope_expansion_requested"] = ["adjacent-system.py"]
                        atomic_write_json(request.output_path, response.data)
                    return response

            orchestrator = Orchestrator(repo, adapter=ScopeExpansionAdapter())
            with self.assertRaisesRegex(SafetyError, "scope expansion"):
                orchestrator.run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=False,
                )

            task_evidence = (
                repo
                / ".manageroo"
                / "runs"
                / orchestrator.run_id
                / "artifacts"
                / "implementation"
                / "tasks"
                / "TASK-001.json"
            )
            self.assertFalse(task_evidence.exists())

    def test_already_authorized_scope_request_repairs_worker_packet_without_operator(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))

            class PacketOmissionAdapter(MockAdapter):
                def __init__(self):
                    super().__init__()
                    self.implementer_calls = 0

                def run(self, request: AgentRequest) -> AgentResponse:
                    if request.role == "implementer":
                        self.implementer_calls += 1
                        if self.implementer_calls == 1:
                            data = {
                                "status": "blocked",
                                "summary": "The packet looked incomplete.",
                                "files_changed": [],
                                "commands_run": [],
                                "risks": [],
                                "scope_expansion_requested": ["manageroo_fixture.txt"],
                            }
                            atomic_write_json(request.output_path, data)
                            return AgentResponse(
                                role=request.role,
                                data=data,
                                raw_text=json.dumps(data),
                                command=["packet-omission"],
                            )
                    return super().run(request)

            adapter = PacketOmissionAdapter()
            result = Orchestrator(repo, adapter=adapter).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(adapter.implementer_calls, 2)
            repaired_prompts = [
                path.read_text(encoding="utf-8")
                for path in Path(result["evidence_paths"]["run_root"]).glob(
                    "packets/*implementer*/**/prompt.md"
                )
            ]
            self.assertTrue(any("# Controller packet repair" in text for text in repaired_prompts))
            self.assertTrue(all("Create the fixture file." in text for text in repaired_prompts))

    def test_locked_reuse_decision_blocks_custom_replacement_before_implementation(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "max_plan_review_cycles = 0", "max_plan_review_cycles = 1"
                ),
                encoding="utf-8",
            )

            class SubstitutingPlanAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    response = super().run(request)
                    if request.role == "plan-compiler":
                        response.data["reuse_bindings"][0]["implementation"] = "build-custom"
                        atomic_write_json(request.output_path, response.data)
                    if request.role == "implementer":
                        raise AssertionError("custom substitution must block before implementation")
                    return response

            with self.assertRaisesRegex(ValidationError, "Plan review did not converge"):
                Orchestrator(repo, adapter=SubstitutingPlanAdapter()).run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=False,
                )

    def test_operator_named_existing_source_blocks_before_plan_if_reuse_worker_omits_it(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
            brief.write_text(
                "Use the finished renderer already in tools/swipebot_motion.py; do not redraw it.\n",
                encoding="utf-8",
            )

            class OmissionAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    if request.role == "plan-compiler":
                        raise AssertionError("reuse omission must block before planning")
                    return super().run(request)

            with self.assertRaisesRegex(SafetyError, "operator-named existing source"):
                Orchestrator(repo, adapter=OmissionAdapter()).run(
                    brief_path=brief,
                    mode="repair",
                    apply_on_success=False,
                )

    def test_run_uses_only_the_explicit_brief_not_transcript_history(self):
        signature = __import__("inspect").signature(Orchestrator.run)
        self.assertNotIn("operator_context", signature.parameters)

    def test_run_binds_exact_brief_inside_run_without_creating_repo_intent(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            self.assertFalse(read_intent_lock(repo)["ok"])

            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            bound = read_json(
                Path(result["evidence_paths"]["run_root"])
                / "artifacts"
                / "intake"
                / "run-intent.json"
            )
            self.assertFalse(read_intent_lock(repo)["ok"])
            self.assertEqual(
                bound["current_request"],
                "# Product request\n\nCreate the fixture file.",
            )
            self.assertRegex(bound["request_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(bound["mode"], "build")
            self.assertEqual(bound["authority"], "current-run-request")

            prompts = list(Path(result["evidence_paths"]["run_root"]).glob("packets/**/prompt.md"))
            prompts.extend(
                Path(result["evidence_paths"]["run_root"]).glob(
                    "review-packets/**/prompt.md"
                )
            )
            self.assertTrue(prompts)
            for prompt in prompts:
                text = prompt.read_text(encoding="utf-8")
                self.assertIn("# Manageroo current-request contract", text)
                self.assertIn("Create the fixture file.", text)

            conformance = read_json(
                Path(result["evidence_paths"]["intent_conformance"])
            )
            self.assertEqual(conformance["status"], "passed")
            self.assertTrue(conformance["current_request_was_in_every_worker_packet"])
            self.assertTrue(conformance["operator_was_not_used_as_an_authorization_gate"])

    def test_newer_brief_automatically_supersedes_saved_run_instead_of_refusing(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
            first = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=brief,
                mode="build",
                apply_on_success=False,
            )

            brief.write_text(
                "# Product request\n\nCreate the fixture file. Latest correction: preserve the exact newline.\n",
                encoding="utf-8",
            )
            replacement = Orchestrator(
                repo,
                adapter=MockAdapter(),
                run_id=first["run_id"],
                continue_existing=True,
            ).run(
                brief_path=brief,
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(replacement["status"], "COMPLETE")
            self.assertNotEqual(replacement["run_id"], first["run_id"])
            self.assertEqual(replacement["supersedes_run_id"], first["run_id"])
            replacement_intent = read_json(
                Path(replacement["evidence_paths"]["run_root"])
                / "artifacts"
                / "intake"
                / "run-intent.json"
            )
            self.assertIn("Latest correction", replacement_intent["current_request"])

    def test_changed_mode_or_exact_contract_supersedes_saved_run(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
            first = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=brief,
                mode="build",
                apply_on_success=False,
            )
            replacement = Orchestrator(
                repo,
                adapter=MockAdapter(),
                run_id=first["run_id"],
                continue_existing=True,
            ).run(
                brief_path=brief,
                mode="repair",
                apply_on_success=False,
                exact_task={
                    "targets": ["manageroo_fixture.txt"],
                    "sources": [],
                    "exclusions": ["Do not touch anything else"],
                    "proofs": ["Fixture exists"],
                    "gate_ids": ["fixture-check"],
                },
            )
            self.assertNotEqual(replacement["run_id"], first["run_id"])
            self.assertEqual(replacement["supersedes_run_id"], first["run_id"])
            intent = read_json(
                Path(replacement["evidence_paths"]["run_root"])
                / "artifacts"
                / "intake"
                / "run-intent.json"
            )
            self.assertEqual(intent["mode"], "repair")
            self.assertEqual(intent["targets"], ["manageroo_fixture.txt"])

    def test_existing_repo_intent_does_not_block_new_current_run(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(
                repo,
                want="Create the fixture file.",
                must_not=["Do not alter the adjacent payment system."],
            )

            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )
            self.assertEqual(result["status"], "COMPLETE")

    def test_saved_installer_token_mode_is_injected_exactly_once_per_worker_packet(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            marker = "MANAGEROO-SAVED-TOKEN-MODE-MARKER"
            with patch("manageroo.orchestrator.token_mode_prompt", return_value=marker):
                result = Orchestrator(
                    repo,
                    adapter=MockAdapter(),
                    capability_roots=[],
                ).run(
                    brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                    mode="build",
                    apply_on_success=False,
                )

            run_root = Path(result["evidence_paths"]["run_root"])
            prompts = list((run_root / "packets").glob("**/prompt.md"))
            prompts.extend((run_root / "review-packets").glob("**/prompt.md"))
            self.assertTrue(prompts)
            for prompt in prompts:
                self.assertEqual(prompt.read_text(encoding="utf-8").count(marker), 1, prompt)

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

    def test_continue_allocates_call_name_after_saved_numeric_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            first = Orchestrator(repo, adapter=MockAdapter())
            first.mirror.create()
            first.job_store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Saved early-phase worker specification.",
            )

            continued = Orchestrator(
                repo,
                adapter=MockAdapter(),
                run_id=first.run_id,
                continue_existing=True,
            )

            self.assertEqual(continued._next_call_name("plan-compiler"), "002-plan-compiler")

    def test_continue_blocked_worker_run_retries_from_disk(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "max_worker_attempts = 0",
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

    def test_default_worker_retry_policy_does_not_stop_after_two_attempts(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))

            class RecoveringProductAdapter(MockAdapter):
                def __init__(self):
                    self.product_calls = 0

                def run(self, request: AgentRequest) -> AgentResponse:
                    if request.role == "product-analyst":
                        self.product_calls += 1
                        if self.product_calls <= 2:
                            raise AgentExecutionError("temporary worker failure")
                    return super().run(request)

            result = Orchestrator(repo, adapter=RecoveringProductAdapter()).run(
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
                    / result["run_id"]
                    / "worker-attempts"
                    / "001-product-analyst"
                ).glob("*.json")
            )
            self.assertEqual([path.stem for path in attempts], ["001", "002", "003"])

    def test_non_destructive_product_choice_uses_recommended_default(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))

            class ProductChoiceAdapter(MockAdapter):
                def run(self, request: AgentRequest) -> AgentResponse:
                    response = super().run(request)
                    if request.role == "product-analyst":
                        response.data["blocking_decisions"] = [
                            {
                                "id": "PRODUCT-001",
                                "question": "Which normal layout should be used?",
                                "why": "Both choices are safe and local.",
                                "category": "product",
                                "options": ["Use the existing layout", "Create a new layout"],
                                "recommended": "Use the existing layout",
                                "reversible": False,
                                "chosen": "",
                            }
                        ]
                        atomic_write_json(request.output_path, response.data)
                    return response

            result = Orchestrator(repo, adapter=ProductChoiceAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(result["status"], "COMPLETE")
            product = read_json(
                repo
                / ".manageroo"
                / "runs"
                / result["run_id"]
                / "artifacts"
                / "planning"
                / "product-model.json"
            )
            self.assertEqual(
                product["blocking_decisions"][0]["chosen"],
                "Use the existing layout",
            )

    def test_plan_review_continues_while_it_is_still_converging(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))

            class ConvergingPlanAdapter(MockAdapter):
                def __init__(self):
                    self.plan_reviews = 0

                def run(self, request: AgentRequest) -> AgentResponse:
                    response = super().run(request)
                    if request.role == "plan-reviewer":
                        self.plan_reviews += 1
                        if self.plan_reviews <= 4:
                            response.data = {
                                "status": "changes-required",
                                "summary": "The next plan revision is still improving.",
                                "findings": [
                                    {
                                        "id": f"PLAN-{self.plan_reviews}",
                                        "severity": "medium",
                                        "problem": "Revise the bounded plan once more.",
                                        "required_change": "Return the next complete plan.",
                                    }
                                ],
                            }
                            atomic_write_json(request.output_path, response.data)
                    return response

            result = Orchestrator(repo, adapter=ConvergingPlanAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(result["status"], "COMPLETE")

    def test_review_repair_can_run_more_than_two_cycles(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))

            class ConvergingReviewAdapter(MockAdapter):
                def __init__(self):
                    self.reviews = 0

                def run(self, request: AgentRequest) -> AgentResponse:
                    response = super().run(request)
                    if request.role == "reviewer":
                        self.reviews += 1
                        if self.reviews <= 3:
                            response.data = {
                                "status": "changes-required",
                                "summary": "One more verified review pass is needed.",
                                "findings": [
                                    {
                                        "id": f"REVIEW-{self.reviews}",
                                        "severity": "high",
                                        "category": "correctness",
                                        "path": "manageroo_fixture.txt",
                                        "start_line": 1,
                                        "end_line": 1,
                                        "quote": "MANAGEROO deterministic fixture completed",
                                        "reason": "Exercise the controller repair loop.",
                                        "action": "Run another bounded repair and review.",
                                        "blocking": True,
                                    }
                                ],
                            }
                            atomic_write_json(request.output_path, response.data)
                    elif request.role == "repairer":
                        response.data = {
                            "status": "implemented",
                            "summary": "No additional edit was required for this fixture pass.",
                            "files_changed": [],
                            "commands_run": [],
                            "risks": [],
                            "scope_expansion_requested": [],
                        }
                        atomic_write_json(request.output_path, response.data)
                    return response

            result = Orchestrator(repo, adapter=ConvergingReviewAdapter()).run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(result["status"], "COMPLETE")

    def test_stale_review_checkout_does_not_block_a_fresh_review_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            orchestrator = Orchestrator(repo, adapter=MockAdapter())
            stale = (
                orchestrator.run_root
                / "review-workspaces"
                / "review-000"
            )
            stale.mkdir(parents=True)
            (stale / "partial.txt").write_text(
                "interrupted old review\n", encoding="utf-8"
            )

            result = orchestrator.run(
                brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
                mode="build",
                apply_on_success=False,
            )

            self.assertEqual(result["status"], "COMPLETE")
            self.assertTrue(stale.is_dir())
            self.assertTrue(
                (
                    orchestrator.run_root
                    / "review-workspaces"
                    / "review-000-retry-001"
                ).is_dir()
            )

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
                    "max_worker_attempts = 0",
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
            config = repo / ".manageroo" / "config.toml"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "max_worker_attempts = 0",
                    "max_worker_attempts = 2",
                ),
                encoding="utf-8",
            )

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
            self.assertFalse(
                (
                    repo
                    / ".manageroo"
                    / "runs"
                    / result["run_id"]
                    / "delivery"
                    / "delivery-transaction.json"
                ).exists()
            )


if __name__ == "__main__":
    unittest.main()

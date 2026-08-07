import tempfile
import threading
import unittest
from pathlib import Path

from manageroo.context import ContextRequest
from manageroo.errors import SafetyError
from manageroo.jobs import AttemptStatus, JobStatus, JobStore
from manageroo.util import atomic_write_json, sha256_file


class JobStoreTests(unittest.TestCase):
    def test_running_attempt_rejects_sequential_second_begin(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JobStore(Path(temp))
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )

            first = store.begin_attempt(job.id)

            with self.assertRaisesRegex(SafetyError, "already has a running attempt"):
                store.begin_attempt(job.id)
            self.assertEqual(first.attempt_id, "001")
            self.assertEqual(len(store.attempts_for(job.id)), 1)

    def test_concurrent_begin_allows_exactly_one_running_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            barrier = threading.Barrier(3)
            attempts = []
            errors = []

            def begin() -> None:
                try:
                    contender = JobStore(run_root)
                    barrier.wait(timeout=5)
                    attempts.append(contender.begin_attempt(job.id))
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=begin) for _ in range(2)]
            for thread in threads:
                thread.start()
            barrier.wait(timeout=5)
            for thread in threads:
                thread.join(timeout=10)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(attempts), 1)
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], SafetyError)
            persisted = store.attempts_for(job.id)
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0].attempt_id, attempts[0].attempt_id)
            self.assertEqual(persisted[0].status, AttemptStatus.RUNNING.value)
            self.assertEqual(store.load_job(job.id).status, JobStatus.RUNNING.value)

    def test_concurrent_conflicting_creation_preserves_one_specification(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            barrier = threading.Barrier(3)
            jobs = []
            errors = []

            def create(instructions: str) -> None:
                try:
                    contender = JobStore(run_root)
                    barrier.wait(timeout=5)
                    jobs.append(
                        contender.create_or_load_job(
                            "001-product-analyst",
                            role="product-analyst",
                            schema="product-model.schema.json",
                            instructions=instructions,
                        )
                    )
                except BaseException as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=create, args=("Analyze first.",)),
                threading.Thread(target=create, args=("Analyze second.",)),
            ]
            for thread in threads:
                thread.start()
            barrier.wait(timeout=5)
            for thread in threads:
                thread.join(timeout=10)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(jobs), 1)
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], SafetyError)
            persisted = JobStore(run_root).load_job("001-product-analyst")
            self.assertEqual(jobs[0].spec_sha256, persisted.spec_sha256)
            self.assertEqual(jobs[0].instructions, persisted.instructions)

    def test_job_attempts_and_completion_are_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
                context=[ContextRequest("README.md", "brief", required=True)],
                sandbox="read-only",
                metadata={"phase": "planning"},
            )

            self.assertEqual(job.status, JobStatus.PENDING.value)
            self.assertTrue((run_root / "jobs" / "001-product-analyst.json").is_file())

            first = store.begin_attempt(job.id)
            self.assertEqual(first.attempt_id, "001")
            store.fail_attempt(job.id, first.attempt_id, RuntimeError("worker drifted"))

            second = store.begin_attempt(job.id)
            output = run_root / "agent-output" / job.id / "002.json"
            atomic_write_json(output, {"ok": True})
            artifact = run_root / "artifacts" / "agent" / "001-product-analyst.json"
            atomic_write_json(artifact, {"ok": True})
            store.complete_attempt(
                job.id,
                second.attempt_id,
                output_path=output,
                data={"ok": True},
                command=["mock"],
            )
            completed = store.complete_job(
                job.id,
                output_artifact="agent/001-product-analyst.json",
                data={"ok": True},
                artifact_path=artifact,
            )

            self.assertEqual(completed.status, JobStatus.COMPLETE.value)
            self.assertEqual(store.status_summary()["completed_jobs"], 1)
            self.assertEqual(store.status_summary()["failed_attempts"], 1)

            reloaded = JobStore(run_root).load_job(job.id)
            self.assertEqual(reloaded.output_artifact, "agent/001-product-analyst.json")
            self.assertEqual(len(JobStore(run_root).attempts_for(job.id)), 2)

    def test_completed_job_rejection_returns_job_to_pending_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            attempt = store.begin_attempt(job.id)
            output = run_root / "agent-output" / job.id / "001.json"
            atomic_write_json(output, {"ok": True})
            artifact = run_root / "artifacts" / "agent" / "001-product-analyst.json"
            atomic_write_json(artifact, {"ok": False})
            store.complete_attempt(
                job.id,
                attempt.attempt_id,
                output_path=output,
                data={"ok": True},
                command=["mock"],
            )

            with self.assertRaisesRegex(SafetyError, "does not match its result"):
                store.complete_job(
                    job.id,
                    output_artifact="agent/001-product-analyst.json",
                    data={"ok": True},
                    artifact_path=artifact,
                )

            rejected = store.load_job(job.id)
            self.assertEqual(rejected.status, JobStatus.PENDING.value)
            self.assertEqual(rejected.failure_type, "SafetyError")
            self.assertIn("does not match its result", rejected.failure)

            retry = store.begin_attempt(job.id)
            retry_output = run_root / "agent-output" / job.id / "002.json"
            atomic_write_json(retry_output, {"ok": True})
            atomic_write_json(artifact, {"ok": True})
            store.complete_attempt(
                job.id,
                retry.attempt_id,
                output_path=retry_output,
                data={"ok": True},
                command=["mock"],
            )
            completed = store.complete_job(
                job.id,
                output_artifact="agent/001-product-analyst.json",
                data={"ok": True},
                artifact_path=artifact,
            )

            self.assertEqual(retry.attempt_id, "002")
            self.assertEqual(completed.status, JobStatus.COMPLETE.value)
            self.assertEqual(completed.failure_type, "")
            self.assertEqual(completed.failure, "")

    def test_delayed_attempt_failure_cannot_downgrade_completed_state(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            attempt = store.begin_attempt(job.id)
            output = run_root / "agent-output" / job.id / "001.json"
            atomic_write_json(output, {"ok": True})
            artifact = run_root / "artifacts" / "agent" / "001-product-analyst.json"
            atomic_write_json(artifact, {"ok": True})
            store.complete_attempt(
                job.id,
                attempt.attempt_id,
                output_path=output,
                data={"ok": True},
                command=["mock"],
            )
            store.complete_job(
                job.id,
                output_artifact="agent/001-product-analyst.json",
                data={"ok": True},
                artifact_path=artifact,
            )

            with self.assertRaisesRegex(SafetyError, "no longer active"):
                store.fail_attempt(job.id, attempt.attempt_id, RuntimeError("delayed failure"))

            self.assertEqual(
                store.load_attempt(job.id, attempt.attempt_id).status,
                AttemptStatus.COMPLETE.value,
            )
            self.assertEqual(store.load_job(job.id).status, JobStatus.COMPLETE.value)

    def test_completed_job_rejects_changed_spec(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JobStore(Path(temp))
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            artifact = Path(temp) / "artifacts" / "agent" / "001-product-analyst.json"
            atomic_write_json(artifact, {"ok": True})
            store.complete_job(
                job.id,
                output_artifact="agent/001-product-analyst.json",
                data={"ok": True},
                artifact_path=artifact,
            )

            with self.assertRaises(SafetyError):
                store.create_or_load_job(
                    "001-product-analyst",
                    role="product-analyst",
                    schema="product-model.schema.json",
                    instructions="Analyze something else.",
                )

    def test_completed_job_without_artifact_hash_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            artifact = run_root / "artifacts" / "agent" / "001-product-analyst.json"
            atomic_write_json(artifact, {"ok": True})
            with self.assertRaises(SafetyError):
                store.complete_job(
                    job.id,
                    output_artifact="agent/001-product-analyst.json",
                    data={"ok": True},
                )
            job = store.load_job(job.id)
            job.status = JobStatus.COMPLETE.value
            job.output_artifact = "agent/001-product-analyst.json"
            job.output_artifact_sha256 = ""
            store.save_job(job)

            self.assertIsNone(store.completed_data(job.id, run_root / "artifacts"))
            self.assertEqual(store.load_job(job.id).status, JobStatus.PENDING.value)

    def test_completed_job_with_mutated_artifact_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            artifact = run_root / "artifacts" / "agent" / "001-product-analyst.json"
            atomic_write_json(artifact, {"ok": True})
            store.complete_job(
                job.id,
                output_artifact="agent/001-product-analyst.json",
                data={"ok": True},
                artifact_path=artifact,
            )

            atomic_write_json(artifact, {"ok": False, "tampered": True})

            self.assertIsNone(store.completed_data(job.id, run_root / "artifacts"))
            reloaded = store.load_job(job.id)
            self.assertEqual(reloaded.status, JobStatus.PENDING.value)
            self.assertEqual(reloaded.failure_type, "StaleArtifact")

    def test_completed_job_rejects_symlinked_artifact_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            shared = run_root / "artifacts" / "shared.json"
            atomic_write_json(shared, {"ok": True})
            artifact = run_root / "artifacts" / "agent" / "001-product-analyst.json"
            artifact.parent.mkdir(parents=True)
            try:
                artifact.symlink_to(shared)
            except (OSError, NotImplementedError):
                self.skipTest("file symlinks are unavailable on this platform")

            with self.assertRaises(SafetyError):
                store.complete_job(
                    job.id,
                    output_artifact="agent/001-product-analyst.json",
                    data={"ok": True},
                    artifact_path=artifact,
                )

            self.assertEqual(shared.read_text(encoding="utf-8"), '{\n  "ok": true\n}\n')

    def test_completed_job_rejects_symlinked_artifact_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            shared = run_root / "artifacts" / "shared"
            target = shared / "001-product-analyst.json"
            atomic_write_json(target, {"ok": True})
            parent = run_root / "artifacts" / "agent"
            try:
                parent.symlink_to(shared, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable on this platform")
            artifact = parent / "001-product-analyst.json"

            with self.assertRaises(SafetyError):
                store.complete_job(
                    job.id,
                    output_artifact="agent/001-product-analyst.json",
                    data={"ok": True},
                    artifact_path=artifact,
                )

            self.assertEqual(target.read_text(encoding="utf-8"), '{\n  "ok": true\n}\n')

    def test_completed_data_rejects_symlinked_artifact_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            artifact = run_root / "artifacts" / "agent" / "001-product-analyst.json"
            atomic_write_json(artifact, {"ok": True})
            store.complete_job(
                job.id,
                output_artifact="agent/001-product-analyst.json",
                data={"ok": True},
                artifact_path=artifact,
            )
            shared = run_root / "artifacts" / "shared.json"
            atomic_write_json(shared, {"ok": True})
            artifact.unlink()
            try:
                artifact.symlink_to(shared)
            except (OSError, NotImplementedError):
                self.skipTest("file symlinks are unavailable on this platform")

            self.assertIsNone(store.completed_data(job.id, run_root / "artifacts"))
            reloaded = store.load_job(job.id)
            self.assertEqual(reloaded.status, JobStatus.PENDING.value)
            self.assertEqual(reloaded.failure_type, "MissingArtifact")
            self.assertEqual(shared.read_text(encoding="utf-8"), '{\n  "ok": true\n}\n')

    def test_completed_data_rejects_symlinked_artifact_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            artifact = run_root / "artifacts" / "agent" / "001-product-analyst.json"
            atomic_write_json(artifact, {"ok": True})
            store.complete_job(
                job.id,
                output_artifact="agent/001-product-analyst.json",
                data={"ok": True},
                artifact_path=artifact,
            )
            artifact.parent.rename(run_root / "artifacts" / "original-agent")
            shared = run_root / "artifacts" / "shared"
            target = shared / artifact.name
            atomic_write_json(target, {"ok": True})
            try:
                artifact.parent.symlink_to(shared, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable on this platform")

            self.assertIsNone(store.completed_data(job.id, run_root / "artifacts"))
            reloaded = store.load_job(job.id)
            self.assertEqual(reloaded.status, JobStatus.PENDING.value)
            self.assertEqual(reloaded.failure_type, "MissingArtifact")
            self.assertEqual(target.read_text(encoding="utf-8"), '{\n  "ok": true\n}\n')

    def test_completed_data_rejects_artifact_that_conflicts_with_recorded_result(self):
        with tempfile.TemporaryDirectory() as temp:
            run_root = Path(temp)
            store = JobStore(run_root)
            job = store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            artifact = run_root / "artifacts" / "agent" / "001-product-analyst.json"
            atomic_write_json(artifact, {"ok": True})
            store.complete_job(
                job.id,
                output_artifact="agent/001-product-analyst.json",
                data={"ok": True},
                artifact_path=artifact,
            )
            atomic_write_json(artifact, {"ok": False})
            completed = store.load_job(job.id)
            completed.output_artifact_sha256 = sha256_file(artifact)
            store.save_job(completed)

            self.assertIsNone(store.completed_data(job.id, run_root / "artifacts"))
            reloaded = store.load_job(job.id)
            self.assertEqual(reloaded.status, JobStatus.PENDING.value)
            self.assertEqual(reloaded.failure_type, "MismatchedArtifactResult")

    def test_blocked_and_failed_jobs_outrank_pending_jobs_in_status(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JobStore(Path(temp))
            store.create_or_load_job(
                "001-product-analyst",
                role="product-analyst",
                schema="product-model.schema.json",
                instructions="Analyze this.",
            )
            blocked = store.create_or_load_job(
                "002-plan-compiler",
                role="plan-compiler",
                schema="task-plan.schema.json",
                instructions="Plan this.",
            )
            store.block_job(blocked.id, RuntimeError("Resolve product decisions before continuing."))

            summary = store.status_summary()
            self.assertEqual(summary["current_job"], blocked.id)
            self.assertIn("Resolve product decisions", summary["next_action"])


if __name__ == "__main__":
    unittest.main()

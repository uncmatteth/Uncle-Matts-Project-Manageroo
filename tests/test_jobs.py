import tempfile
import unittest
from pathlib import Path

from manageroo.context import ContextRequest
from manageroo.errors import SafetyError
from manageroo.jobs import JobStatus, JobStore
from manageroo.util import atomic_write_json


class JobStoreTests(unittest.TestCase):
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

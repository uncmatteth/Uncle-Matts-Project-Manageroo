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
            store.complete_job(job.id, output_artifact="agent/001-product-analyst.json", data={"ok": True})

            with self.assertRaises(SafetyError):
                store.create_or_load_job(
                    "001-product-analyst",
                    role="product-analyst",
                    schema="product-model.schema.json",
                    instructions="Analyze something else.",
                )


if __name__ == "__main__":
    unittest.main()

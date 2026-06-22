from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .errors import SafetyError
from .util import atomic_write_json, read_json, sha256_file, sha256_json, utc_now


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED = "blocked"


class AttemptStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    return value


def _tail(value: str, limit: int = 4000) -> str:
    return value[-limit:] if len(value) > limit else value


@dataclass
class Job:
    id: str
    role: str
    schema: str
    instructions: str
    context: list[dict[str, Any]] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    sandbox: str = "read-only"
    status: str = JobStatus.PENDING.value
    spec_sha256: str = ""
    output_artifact: str = ""
    output_artifact_sha256: str = ""
    result_sha256: str = ""
    failure_type: str = ""
    failure: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class JobAttempt:
    job_id: str
    attempt_id: str
    status: str = AttemptStatus.RUNNING.value
    started_at: str = ""
    finished_at: str = ""
    packet_path: str = ""
    packet_sha256: str = ""
    manifest_path: str = ""
    output_path: str = ""
    output_sha256: str = ""
    result_sha256: str = ""
    command: list[str] = field(default_factory=list)
    error_type: str = ""
    error: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""


class JobStore:
    def __init__(self, run_root: Path):
        self.run_root = run_root
        self.jobs_root = run_root / "jobs"
        self.attempts_root = run_root / "worker-attempts"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.attempts_root.mkdir(parents=True, exist_ok=True)

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_root / f"{job_id}.json"

    def _attempt_path(self, job_id: str, attempt_id: str) -> Path:
        return self.attempts_root / job_id / f"{attempt_id}.json"

    def _spec(
        self,
        *,
        role: str,
        schema: str,
        instructions: str,
        context: Iterable[Any],
        allowed_paths: Iterable[str],
        dependencies: Iterable[str],
        metadata: dict[str, Any],
        sandbox: str,
    ) -> dict[str, Any]:
        return {
            "role": role,
            "schema": schema,
            "instructions": instructions,
            "context": _jsonable(list(context)),
            "allowed_paths": sorted(set(allowed_paths)),
            "dependencies": list(dependencies),
            "metadata": _jsonable(metadata),
            "sandbox": sandbox,
        }

    def create_or_load_job(
        self,
        job_id: str,
        *,
        role: str,
        schema: str,
        instructions: str,
        context: Iterable[Any] = (),
        allowed_paths: Iterable[str] = (),
        dependencies: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
        sandbox: str = "read-only",
    ) -> Job:
        spec = self._spec(
            role=role,
            schema=schema,
            instructions=instructions,
            context=context,
            allowed_paths=allowed_paths,
            dependencies=dependencies,
            metadata=metadata or {},
            sandbox=sandbox,
        )
        spec_hash = sha256_json(spec)
        path = self._job_path(job_id)
        if path.exists():
            job = self.load_job(job_id)
            if job.spec_sha256 != spec_hash:
                raise SafetyError(f"Job spec changed since it was recorded: {job_id}")
            return job
        now = utc_now()
        job = Job(
            id=job_id,
            role=role,
            schema=schema,
            instructions=instructions,
            context=spec["context"],
            allowed_paths=spec["allowed_paths"],
            dependencies=spec["dependencies"],
            metadata=spec["metadata"],
            sandbox=sandbox,
            spec_sha256=spec_hash,
            created_at=now,
            updated_at=now,
        )
        self.save_job(job)
        return job

    def spec_sha256_for(
        self,
        *,
        role: str,
        schema: str,
        instructions: str,
        context: Iterable[Any] = (),
        allowed_paths: Iterable[str] = (),
        dependencies: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
        sandbox: str = "read-only",
    ) -> str:
        return sha256_json(
            self._spec(
                role=role,
                schema=schema,
                instructions=instructions,
                context=context,
                allowed_paths=allowed_paths,
                dependencies=dependencies,
                metadata=metadata or {},
                sandbox=sandbox,
            )
        )

    def job_exists(self, job_id: str) -> bool:
        return self._job_path(job_id).is_file()

    def find_matching_job(self, *, role: str, spec_sha256: str) -> Job | None:
        matches = [
            job
            for job in self.list_jobs()
            if job.role == role and job.spec_sha256 == spec_sha256
        ]
        if not matches:
            return None
        priority = {
            JobStatus.BLOCKED.value: 0,
            JobStatus.FAILED.value: 1,
            JobStatus.PENDING.value: 2,
            JobStatus.RUNNING.value: 3,
            JobStatus.COMPLETE.value: 4,
        }
        return sorted(matches, key=lambda job: (priority.get(job.status, 99), job.id))[0]

    def save_job(self, job: Job) -> None:
        job.updated_at = utc_now()
        atomic_write_json(self._job_path(job.id), asdict(job))

    def load_job(self, job_id: str) -> Job:
        return Job(**read_json(self._job_path(job_id)))

    def list_jobs(self) -> list[Job]:
        return [Job(**read_json(path)) for path in sorted(self.jobs_root.glob("*.json"))]

    def attempts_for(self, job_id: str) -> list[JobAttempt]:
        root = self.attempts_root / job_id
        if not root.exists():
            return []
        return [JobAttempt(**read_json(path)) for path in sorted(root.glob("*.json"))]

    def begin_attempt(self, job_id: str) -> JobAttempt:
        job = self.load_job(job_id)
        if job.status == JobStatus.COMPLETE.value:
            raise SafetyError(f"Completed job cannot start another attempt: {job_id}")
        attempt_id = f"{len(self.attempts_for(job_id)) + 1:03d}"
        attempt = JobAttempt(job_id=job_id, attempt_id=attempt_id, started_at=utc_now())
        job.status = JobStatus.RUNNING.value
        self.save_job(job)
        self.save_attempt(attempt)
        return attempt

    def save_attempt(self, attempt: JobAttempt) -> None:
        atomic_write_json(self._attempt_path(attempt.job_id, attempt.attempt_id), asdict(attempt))

    def load_attempt(self, job_id: str, attempt_id: str) -> JobAttempt:
        return JobAttempt(**read_json(self._attempt_path(job_id, attempt_id)))

    def record_packet(self, job_id: str, attempt_id: str, *, packet_path: Path) -> None:
        attempt = self.load_attempt(job_id, attempt_id)
        manifest = packet_path / "manifest.json"
        prompt = packet_path / "prompt.md"
        attempt.packet_path = str(packet_path)
        attempt.manifest_path = str(manifest)
        attempt.packet_sha256 = sha256_file(prompt) if prompt.exists() else ""
        self.save_attempt(attempt)

    def complete_attempt(
        self,
        job_id: str,
        attempt_id: str,
        *,
        output_path: Path,
        data: dict[str, Any],
        command: list[str],
        stdout: str = "",
        stderr: str = "",
    ) -> JobAttempt:
        attempt = self.load_attempt(job_id, attempt_id)
        attempt.status = AttemptStatus.COMPLETE.value
        attempt.finished_at = utc_now()
        attempt.output_path = str(output_path)
        attempt.output_sha256 = sha256_file(output_path) if output_path.exists() else ""
        attempt.result_sha256 = sha256_json(data)
        attempt.command = command
        attempt.stdout_tail = _tail(stdout)
        attempt.stderr_tail = _tail(stderr)
        self.save_attempt(attempt)
        return attempt

    def fail_attempt(self, job_id: str, attempt_id: str, exc: BaseException) -> JobAttempt:
        attempt = self.load_attempt(job_id, attempt_id)
        attempt.status = AttemptStatus.FAILED.value
        attempt.finished_at = utc_now()
        attempt.error_type = type(exc).__name__
        attempt.error = str(exc)
        self.save_attempt(attempt)
        job = self.load_job(job_id)
        job.status = JobStatus.PENDING.value
        job.failure_type = attempt.error_type
        job.failure = attempt.error
        self.save_job(job)
        return attempt

    def complete_job(
        self,
        job_id: str,
        *,
        output_artifact: str,
        data: dict[str, Any],
        artifact_path: Path | None = None,
    ) -> Job:
        if not artifact_path or not artifact_path.is_file():
            raise SafetyError(f"Completed job requires a written artifact: {job_id}")
        job = self.load_job(job_id)
        job.status = JobStatus.COMPLETE.value
        job.output_artifact = output_artifact
        job.output_artifact_sha256 = sha256_file(artifact_path)
        job.result_sha256 = sha256_json(data)
        job.failure_type = ""
        job.failure = ""
        self.save_job(job)
        return job

    def fail_job(self, job_id: str, exc: BaseException) -> Job:
        job = self.load_job(job_id)
        job.status = JobStatus.FAILED.value
        job.failure_type = type(exc).__name__
        job.failure = str(exc)
        self.save_job(job)
        return job

    def block_job(self, job_id: str, exc: BaseException) -> Job:
        job = self.load_job(job_id)
        job.status = JobStatus.BLOCKED.value
        job.failure_type = type(exc).__name__
        job.failure = str(exc)
        self.save_job(job)
        return job

    def completed_data(self, job_id: str, artifacts_root: Path) -> dict[str, Any] | None:
        job = self.load_job(job_id)
        if job.status != JobStatus.COMPLETE.value or not job.output_artifact:
            return None
        if not job.output_artifact_sha256:
            job.status = JobStatus.PENDING.value
            job.failure_type = "MissingArtifactHash"
            job.failure = f"Completed job artifact hash is missing: {job.output_artifact}"
            self.save_job(job)
            return None
        path = artifacts_root / job.output_artifact
        if not path.exists():
            job.status = JobStatus.PENDING.value
            job.failure_type = "MissingArtifact"
            job.failure = f"Completed job artifact is missing: {job.output_artifact}"
            self.save_job(job)
            return None
        if sha256_file(path) != job.output_artifact_sha256:
            job.status = JobStatus.PENDING.value
            job.failure_type = "StaleArtifact"
            job.failure = f"Completed job artifact changed: {job.output_artifact}"
            self.save_job(job)
            return None
        return read_json(path)

    def status_summary(self) -> dict[str, Any]:
        jobs = self.list_jobs()
        attempts = [attempt for job in jobs for attempt in self.attempts_for(job.id)]
        blocked = next((job for job in jobs if job.status == JobStatus.BLOCKED.value), None)
        failed = next((job for job in jobs if job.status == JobStatus.FAILED.value), None)
        pending_or_running = next(
            (job for job in jobs if job.status in {JobStatus.RUNNING.value, JobStatus.PENDING.value}),
            None,
        )
        current = blocked or failed or pending_or_running
        next_action = "No worker jobs have been created yet."
        if blocked:
            next_action = f"Fix blocked job {blocked.id}: {blocked.failure}"
        elif failed:
            next_action = f"Inspect failed job {failed.id}: {failed.failure}"
        elif current:
            next_action = f"Run disposable worker job {current.id}."
        elif jobs:
            next_action = "All recorded worker jobs are complete."
        return {
            "total_jobs": len(jobs),
            "completed_jobs": sum(1 for job in jobs if job.status == JobStatus.COMPLETE.value),
            "pending_jobs": sum(1 for job in jobs if job.status == JobStatus.PENDING.value),
            "running_jobs": sum(1 for job in jobs if job.status == JobStatus.RUNNING.value),
            "failed_jobs": sum(1 for job in jobs if job.status == JobStatus.FAILED.value),
            "blocked_jobs": sum(1 for job in jobs if job.status == JobStatus.BLOCKED.value),
            "failed_attempts": sum(1 for attempt in attempts if attempt.status == AttemptStatus.FAILED.value),
            "current_job": current.id if current else "",
            "blocking_reason": (blocked.failure if blocked else failed.failure if failed else ""),
            "next_action": next_action,
        }

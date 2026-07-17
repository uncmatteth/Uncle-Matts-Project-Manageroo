from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from .errors import SafetyError
from .intent_lock import audit_compaction_text, capture_intent_lock
from .jobs import JobStatus, JobStore
from .policy import CommandPolicy, ScopePolicy
from .runner import CommandRunner
from .selftest import run_self_test


def _proof(name: str, ok: bool, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "detail": detail,
        "evidence": evidence or {},
    }


def _run_case(name: str, case: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = case()
        return _proof(name, bool(result.get("ok")), str(result.get("detail") or ""), result)
    except Exception as exc:
        return _proof(
            name,
            False,
            f"{type(exc).__name__}: {exc}",
            {"exception_type": type(exc).__name__, "exception": str(exc)},
        )


def _git_fixture(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    runner = CommandRunner()
    for argv in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "MANAGEROO Product Proof"],
        ["git", "config", "user.email", "prove@local.invalid"],
    ):
        result = runner.run(argv, cwd=repo, timeout_seconds=30)
        if not result.passed:
            raise RuntimeError(result.stderr or result.stdout)
    (repo / "README.md").write_text("# Product proof fixture\n", encoding="utf-8")
    for argv in (["git", "add", "-A"], ["git", "commit", "-m", "fixture"]):
        result = runner.run(argv, cwd=repo, timeout_seconds=30)
        if not result.passed:
            raise RuntimeError(result.stderr or result.stdout)
    return repo


def _full_lifecycle_case() -> dict[str, Any]:
    result = run_self_test()
    return {
        "ok": bool(result.get("ok") and result.get("status") == "COMPLETE"),
        "detail": "controller completed a fixture run and applied the verified result",
        "run": result,
    }


def _intent_preservation_case() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="manageroo-prove-intent-") as temp:
        repo = _git_fixture(Path(temp))
        locked = capture_intent_lock(
            repo,
            want="Keep checkout behavior exact",
            outcomes=["One verified payment path"],
            must_not=["Do not change admin order export"],
            proof=["Run checkout tests"],
            source="manageroo prove",
            force=True,
        )
        bad = audit_compaction_text(repo, "We are improving checkout and everything is ready.")
        good_text = "\n".join(
            [
                "Keep checkout behavior exact",
                "One verified payment path",
                "Do not change admin order export",
                "Run checkout tests",
            ]
        )
        good = audit_compaction_text(repo, good_text)
        ok = locked.get("ok") is True and bad.get("ok") is False and good.get("ok") is True
        return {
            "ok": ok,
            "detail": "intent drift was rejected while exact locked intent was accepted",
            "bad_summary_status": bad.get("status"),
            "bad_missing": bad.get("missing", []),
            "good_summary_status": good.get("status"),
        }


def _scope_and_command_case() -> dict[str, Any]:
    ScopePolicy(("src/app.py",)).validate_paths(["src/app.py"])
    scope_blocked = False
    try:
        ScopePolicy(("src/app.py",)).validate_paths(["docs/secret.md"])
    except SafetyError:
        scope_blocked = True

    command_policy = CommandPolicy(("python",))
    command_policy.validate(["python", "-m", "unittest"])
    path_spoof_blocked = False
    try:
        command_policy.validate(["/tmp/python", "-m", "unittest"])
    except SafetyError:
        path_spoof_blocked = True

    return {
        "ok": scope_blocked and path_spoof_blocked,
        "detail": "out-of-scope edits and executable-path spoofing were blocked",
        "scope_blocked": scope_blocked,
        "path_spoof_blocked": path_spoof_blocked,
    }


def _durable_state_case() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="manageroo-prove-state-") as temp:
        run_root = Path(temp) / "run"
        store = JobStore(run_root)
        job = store.create_or_load_job(
            "implement-001",
            role="implementer",
            schema="implementation",
            instructions="Make the exact requested change.",
            allowed_paths=["src/app.py"],
        )
        attempt = store.begin_attempt(job.id)
        artifact = run_root / "artifact.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps({"ok": True}) + "\n", encoding="utf-8")
        store.complete_attempt(
            job.id,
            attempt.attempt_id,
            output_path=artifact,
            data={"ok": True},
            command=["mock-worker"],
        )
        store.complete_job(
            job.id,
            output_artifact=str(artifact),
            artifact_path=artifact,
            data={"ok": True},
        )

        reloaded = JobStore(run_root).load_job(job.id)
        replay_blocked = False
        try:
            JobStore(run_root).begin_attempt(job.id)
        except SafetyError:
            replay_blocked = True

        drift_blocked = False
        try:
            JobStore(run_root).create_or_load_job(
                job.id,
                role="implementer",
                schema="implementation",
                instructions="A changed assignment that must not replace saved truth.",
                allowed_paths=["src/app.py"],
            )
        except SafetyError:
            drift_blocked = True

        return {
            "ok": (
                reloaded.status == JobStatus.COMPLETE.value
                and bool(reloaded.output_artifact_sha256)
                and replay_blocked
                and drift_blocked
            ),
            "detail": "completed worker state survived reload and rejected replay or changed job truth",
            "reloaded_status": reloaded.status,
            "artifact_hash_recorded": bool(reloaded.output_artifact_sha256),
            "completed_replay_blocked": replay_blocked,
            "changed_spec_blocked": drift_blocked,
        }


def _source_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "tests").is_dir() and (candidate / "pyproject.toml").is_file():
        return candidate
    return None


def _run_regression_patterns(patterns: tuple[str, ...]) -> dict[str, Any]:
    root = _source_root()
    if root is None:
        return {
            "ok": False,
            "detail": "source regression evidence is unavailable from this installation",
            "available": False,
            "patterns": list(patterns),
        }

    runs: list[dict[str, Any]] = []
    for pattern in patterns:
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            timeout=600,
        )
        output = completed.stdout or ""
        runs.append(
            {
                "pattern": pattern,
                "exit_code": completed.returncode,
                "output_tail": output[-8000:],
            }
        )
        if completed.returncode != 0:
            return {
                "ok": False,
                "detail": f"adversarial regression failed: {pattern}",
                "available": True,
                "patterns": list(patterns),
                "runs": runs,
            }
    return {
        "ok": True,
        "detail": "all mapped adversarial regressions passed",
        "available": True,
        "patterns": list(patterns),
        "runs": runs,
    }


def _regression_case(patterns: tuple[str, ...]) -> Callable[[], dict[str, Any]]:
    return lambda: _run_regression_patterns(patterns)


def run_product_proof(*, include_regression: bool = True) -> dict[str, Any]:
    checks = [
        _run_case("Whole-project lifecycle", _full_lifecycle_case),
        _run_case("Intent preservation and compaction defense", _intent_preservation_case),
        _run_case("Scope and command enforcement", _scope_and_command_case),
        _run_case("Durable worker state and drift rejection", _durable_state_case),
    ]

    regression_lanes = [
        ("Context overflow, omission, and stale-packet defense", ("test_context.py",)),
        ("Worker retry isolation and artifact integrity", ("test_job_runner.py", "test_jobs.py")),
        ("Interrupted-run continuation and saved-queue replay", ("test_orchestrator_jobs.py",)),
        ("Dishonest or insufficient acceptance evidence rejection", ("test_acceptance_evidence.py",)),
        ("Intent-lock adversarial regression", ("test_intent_lock.py",)),
        ("Policy enforcement adversarial regression", ("test_policy.py",)),
        (
            "Review, release, and truthful completion gates",
            ("test_release_ready.py", "test_cli_release_ready.py", "test_truth_contract.py"),
        ),
    ]

    if include_regression:
        for name, patterns in regression_lanes:
            checks.append(_run_case(name, _regression_case(patterns)))
        checks.append(_run_case("Full repository regression suite", _regression_case(("test_*.py",))))
    else:
        checks.append(
            _proof(
                "Source-level adversarial regression evidence",
                False,
                "skipped by operator; COMPLETE certification is therefore forbidden",
                {"skipped": True},
            )
        )

    ok = all(item["ok"] for item in checks)
    status = "COMPLETE" if ok else "PARTIAL"
    blockers = [item["name"] for item in checks if not item["ok"]]
    return {
        "ok": ok,
        "status": status,
        "proof_version": 1,
        "checks": checks,
        "blockers": blockers,
        "completion_rule": "COMPLETE is emitted only when every required machine-checked proof lane passes.",
    }


def format_product_proof(report: dict[str, Any]) -> str:
    lines = ["MANAGEROO PRODUCT PROOF", ""]
    for item in report.get("checks", []):
        label = "PASS" if item.get("ok") else "FAIL"
        lines.append(f"{label:<4}  {item.get('name')}")
        detail = str(item.get("detail") or "").strip()
        if detail:
            lines.append(f"      {detail}")
    lines.extend(["", f"RESULT: {report.get('status', 'PARTIAL')}"])
    blockers = report.get("blockers") or []
    if blockers:
        lines.append("BLOCKERS: " + ", ".join(blockers))
    return "\n".join(lines) + "\n"

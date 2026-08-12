from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from .adapters.factory import build_adapter
from .config import load_config
from .errors import SafetyError
from .intent_lock import audit_compaction_text, capture_intent_lock
from .jobs import JobStatus, JobStore
from .orchestrator import Orchestrator
from .policy import CommandPolicy, ScopePolicy
from .project import initialize_project
from .runner import CommandRunner
from .selftest import run_self_test

LIVE_AGENT_CHOICES = ("codex",)
_LIVE_PROOF_GIT_ENTRY_LIMIT = 10_000
_LIVE_PROOF_GIT_BYTE_LIMIT = 64 * 1024 * 1024


def _proof(name: str, ok: bool, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail, "evidence": evidence or {}}


def _run_case(name: str, case: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = case()
        return _proof(name, bool(result.get("ok")), str(result.get("detail") or ""), result)
    except Exception as exc:
        return _proof(name, False, f"{type(exc).__name__}: {exc}", {"exception_type": type(exc).__name__, "exception": str(exc)})


def _git_fixture(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    runner = CommandRunner()
    for argv in (["git", "init", "-b", "main"], ["git", "config", "user.name", "MANAGEROO Product Proof"], ["git", "config", "user.email", "prove@local.invalid"]):
        result = runner.run(argv, cwd=repo, timeout_seconds=30)
        if not result.passed:
            raise RuntimeError(result.stderr or result.stdout)
    (repo / "README.md").write_text("# Product proof fixture\n", encoding="utf-8")
    for argv in (["git", "add", "-A"], ["git", "commit", "-m", "fixture"]):
        result = runner.run(argv, cwd=repo, timeout_seconds=30)
        if not result.passed:
            raise RuntimeError(result.stderr or result.stdout)
    return repo


def _configure_proof_project(repo: Path, *, agent: str) -> Path:
    initialize_project(repo, agent=agent)
    config_path = repo / ".manageroo" / "config.toml"
    text = config_path.read_text(encoding="utf-8")
    if "[[verification.gates]]" not in text:
        text += ("\n[[verification.gates]]\n" 'id = "product-proof-check"\n' 'kind = "test"\n' "required = true\n" "timeout_seconds = 60\n" "argv = [" + json.dumps(sys.executable) + ', "-m", "unittest", "discover"]\n')
    config_path.write_text(text, encoding="utf-8")
    (repo / "manageroo_live_agent_proof.txt").write_text("MANAGEROO live agent proof pending\n", encoding="utf-8")
    (repo / "test_product_proof.py").write_text(
        "import unittest\nfrom pathlib import Path\n\nclass ProductProofFixture(unittest.TestCase):\n    def test_expected_result(self):\n        self.assertEqual(\n            Path('manageroo_live_agent_proof.txt').read_text(encoding='utf-8'),\n            'MANAGEROO live agent proof completed\\n',\n        )\n\nif __name__ == '__main__': unittest.main()\n",
        encoding="utf-8",
    )
    brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
    brief.write_text(
        "# Product request\n\nUpdate exactly one file named `manageroo_live_agent_proof.txt`.\nIts exact contents must be `MANAGEROO live agent proof completed` followed by one newline.\nDo not modify the existing test file.\nThe work is complete only when the configured unittest gate passes and independent review approves it.\n",
        encoding="utf-8",
    )
    return brief


def _remove_disposable_config_locks(repo: Path) -> None:
    """Remove closed advisory locks before the transactional proof begins."""
    cache = repo / ".manageroo" / "cache"
    for name in (
        "PROJECT-MEMORY.md.manageroo.lock",
        "config.toml.manageroo.lock",
    ):
        path = cache / name
        if not path.exists():
            continue
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Unsafe disposable proof lock entry: {path}")
        path.unlink()


def _full_lifecycle_case() -> dict[str, Any]:
    result = run_self_test()
    return {"ok": bool(result.get("ok") and result.get("status") == "COMPLETE"), "detail": "controller completed a fixture run and applied the verified result", "run": result}


def _live_proof_git_value(repo: Path, runner: CommandRunner, argv: list[str]) -> str:
    result = runner.run(argv, cwd=repo, timeout_seconds=30)
    if not result.passed:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def _live_proof_tree_inventory(
    root: Path,
    *,
    excluded_roots: set[str] | None = None,
) -> dict[str, tuple[str, int, str]]:
    entries: dict[str, tuple[str, int, str]] = {}
    total_bytes = 0
    excluded = excluded_roots or set()
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as children:
            for child in children:
                path = Path(child.path)
                relative_path = path.relative_to(root)
                if relative_path.parts[0] in excluded:
                    continue
                if len(entries) >= _LIVE_PROOF_GIT_ENTRY_LIMIT:
                    raise RuntimeError("Live-agent proof inventory exceeds the bounded entry limit.")
                state = child.stat(follow_symlinks=False)
                mode = stat.S_IMODE(state.st_mode)
                relative = relative_path.as_posix()
                if stat.S_ISREG(state.st_mode):
                    total_bytes += state.st_size
                    if total_bytes > _LIVE_PROOF_GIT_BYTE_LIMIT:
                        raise RuntimeError("Live-agent proof inventory exceeds the bounded byte limit.")
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    entries[relative] = ("file", mode, digest)
                elif stat.S_ISDIR(state.st_mode):
                    entries[relative] = ("directory", mode, "")
                    pending.append(path)
                elif stat.S_ISLNK(state.st_mode):
                    entries[relative] = ("symlink", mode, path.readlink().as_posix())
                else:
                    entries[relative] = ("other", mode, "")
    return entries


def _live_proof_git_metadata(repo: Path, runner: CommandRunner) -> dict[str, tuple[str, int, str]]:
    git_dir = Path(
        _live_proof_git_value(repo, runner, ["git", "rev-parse", "--absolute-git-dir"])
    )
    return _live_proof_tree_inventory(git_dir, excluded_roots={"index"})


def _live_proof_git_identity(repo: Path, runner: CommandRunner) -> dict[str, Any]:
    return {
        "metadata": _live_proof_git_metadata(repo, runner),
        "head": _live_proof_git_value(repo, runner, ["git", "rev-parse", "HEAD"]),
        "head_tree": _live_proof_git_value(repo, runner, ["git", "rev-parse", "HEAD^{tree}"]),
        "index_tree": _live_proof_git_value(repo, runner, ["git", "write-tree"]),
        "history": _live_proof_git_value(repo, runner, ["git", "rev-list", "--all", "--parents"]),
        "refs": _live_proof_git_value(
            repo,
            runner,
            ["git", "for-each-ref", "--format=%(refname)%00%(objectname)"],
        ),
    }


def _live_agent_case(agent: str) -> dict[str, Any]:
    if agent not in LIVE_AGENT_CHOICES:
        return {"ok": False, "detail": f"unsupported live-agent proof choice: {agent}", "agent": agent}
    with tempfile.TemporaryDirectory(prefix=f"manageroo-prove-{agent}-") as temp:
        root = Path(temp)
        repo = _git_fixture(root)
        _configure_proof_project(repo, agent=agent)
        _remove_disposable_config_locks(repo)
        runner = CommandRunner(root / "logs")
        for argv in (["git", "add", "-A"], ["git", "commit", "-m", "configure live proof"]):
            result = runner.run(argv, cwd=repo, timeout_seconds=30)
            if not result.passed:
                raise RuntimeError(result.stderr or result.stdout)
        config = load_config(repo)
        adapter = build_adapter(config, runner)
        doctor = adapter.doctor(repo)
        if not doctor.get("ok"):
            return {"ok": False, "detail": f"{agent} failed adapter compatibility checks", "agent": agent, "doctor": doctor}
        result = Orchestrator(repo, adapter=adapter).run(
            brief_path=repo / ".manageroo" / "PRODUCT-BRIEF.md",
            mode="build",
            apply_on_success=True,
            exact_task={
                "targets": ["manageroo_live_agent_proof.txt"],
                "sources": ["test_product_proof.py"],
                "exclusions": ["Do not modify any other path."],
                "proofs": ["The configured product-proof-check passes."],
                "gate_ids": ["product-proof-check"],
            },
        )
        target = repo / "manageroo_live_agent_proof.txt"
        expected = "MANAGEROO live agent proof completed\n"
        actual = target.read_text(encoding="utf-8") if target.is_file() else None
        declared = sorted(set(str(item) for item in result.get("files_changed", [])))
        gate_ok = any(
            item.get("id") == "product-proof-check" and item.get("passed")
            for item in result.get("gates", [])
        )
        review_ok = result.get("review", {}).get("status") == "approved"
        ok = (
            result.get("status") == "COMPLETE"
            and result.get("applied_to_source") is True
            and declared == ["manageroo_live_agent_proof.txt"]
            and actual == expected
            and gate_ok
            and review_ok
        )
        detail = (
            f"{agent} completed one bounded disposable write through the production adapter"
            if ok
            else f"{agent} failed bounded live-agent repository identity checks"
        )
        return {
            "ok": ok,
            "detail": detail,
            "agent": agent,
            "doctor": doctor,
            "run_id": result.get("run_id"),
            "run_status": result.get("status"),
            "applied_to_source": result.get("applied_to_source"),
            "declared_files": declared,
            "target_exists": target.is_file(),
            "target_exact": actual == expected,
            "gate_passed": gate_ok,
            "independent_review_approved": review_ok,
            "evidence_paths": result.get("evidence_paths", {}),
        }


def _intent_preservation_case() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="manageroo-prove-intent-") as temp:
        repo = _git_fixture(Path(temp))
        locked = capture_intent_lock(repo, want="Keep checkout behavior exact", outcomes=["One verified payment path"], must_not=["Do not change admin order export"], proof=["Run checkout tests"], source="manageroo prove", force=True)
        bad = audit_compaction_text(repo, "We are improving checkout and everything is ready.")
        good_text = "\n".join(["Keep checkout behavior exact", "One verified payment path", "Do not change admin order export", "Run checkout tests"])
        good = audit_compaction_text(repo, good_text)
        ok = (
            locked.get("ok") is True
            and bad.get("ok") is True
            and bad.get("status") == "repaired"
            and bad.get("repair_applied") is True
            and "Do not change admin order export" in bad.get("repaired_summary", "")
            and good.get("ok") is True
        )
        return {
            "ok": ok,
            "detail": "compacted intent was restored automatically while complete intent passed unchanged",
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
    return {"ok": scope_blocked and path_spoof_blocked, "detail": "out-of-scope edits and executable-path spoofing were blocked", "scope_blocked": scope_blocked, "path_spoof_blocked": path_spoof_blocked}


def _durable_state_case() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="manageroo-prove-state-") as temp:
        run_root = Path(temp) / "run"
        store = JobStore(run_root)
        job = store.create_or_load_job("implement-001", role="implementer", schema="implementation", instructions="Make the exact requested change.", allowed_paths=["src/app.py"])
        attempt = store.begin_attempt(job.id)
        attempt_output = run_root / "worker-output.json"
        attempt_output.write_text(json.dumps({"ok": True}) + "\n", encoding="utf-8")
        store.complete_attempt(job.id, attempt.attempt_id, output_path=attempt_output, data={"ok": True}, command=["mock-worker"])
        artifact = run_root / "artifacts" / "artifact.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps({"ok": True}) + "\n", encoding="utf-8")
        store.complete_job(job.id, output_artifact="artifact.json", artifact_path=artifact, data={"ok": True})
        reloaded = JobStore(run_root).load_job(job.id)
        replay_blocked = False
        try:
            JobStore(run_root).begin_attempt(job.id)
        except SafetyError:
            replay_blocked = True
        drift_blocked = False
        try:
            JobStore(run_root).create_or_load_job(job.id, role="implementer", schema="implementation", instructions="A changed assignment that must not replace saved truth.", allowed_paths=["src/app.py"])
        except SafetyError:
            drift_blocked = True
        return {"ok": reloaded.status == JobStatus.COMPLETE.value and bool(reloaded.output_artifact_sha256) and replay_blocked and drift_blocked, "detail": "completed worker state survived reload and rejected replay or changed job truth", "reloaded_status": reloaded.status, "artifact_hash_recorded": bool(reloaded.output_artifact_sha256), "completed_replay_blocked": replay_blocked, "changed_spec_blocked": drift_blocked}


def _source_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "tests").is_dir() and (candidate / "pyproject.toml").is_file():
        return candidate
    return None


def _run_regression_patterns(patterns: tuple[str, ...]) -> dict[str, Any]:
    root = _source_root()
    if root is None:
        return {"ok": False, "detail": "source regression evidence is unavailable from this installation", "available": False, "patterns": list(patterns)}
    runs: list[dict[str, Any]] = []
    for pattern in patterns:
        completed = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern, "-v"], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, timeout=600)
        output = completed.stdout or ""
        runs.append({"pattern": pattern, "exit_code": completed.returncode, "output_tail": output[-8000:]})
        if completed.returncode != 0:
            return {"ok": False, "detail": f"adversarial regression failed: {pattern}", "available": True, "patterns": list(patterns), "runs": runs}
    return {"ok": True, "detail": "all mapped adversarial regressions passed", "available": True, "patterns": list(patterns), "runs": runs}


def _regression_case(patterns: tuple[str, ...]) -> Callable[[], dict[str, Any]]:
    return lambda: _run_regression_patterns(patterns)


def run_product_proof(*, include_regression: bool = True, live_agent: str | None = None) -> dict[str, Any]:
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
        ("Optional-tool failure degrades without corrupting controller truth", ("test_external_intelligence.py",)),
        ("Intent-lock adversarial regression", ("test_intent_lock.py",)),
        ("Policy enforcement adversarial regression", ("test_policy.py",)),
        ("Bounded retry, review, release, and truthful completion gates", ("test_job_runner.py", "test_orchestrator_jobs.py", "test_release_ready.py", "test_cli_release_ready.py", "test_truth_contract.py")),
    ]
    if include_regression:
        for name, patterns in regression_lanes:
            checks.append(_run_case(name, _regression_case(patterns)))
        checks.append(_run_case("Full repository regression suite", _regression_case(("test_*.py",))))
    else:
        checks.append(_proof("Source-level adversarial regression evidence", False, "skipped by operator; COMPLETE certification is therefore forbidden", {"skipped": True}))
    if live_agent:
        checks.append(_run_case(f"Live coding-agent integration ({live_agent})", lambda: _live_agent_case(live_agent)))
    else:
        checks.append(_proof("Live coding-agent integration", False, "no live agent selected; run `manageroo prove --live-agent codex`", {"skipped": True, "choices": list(LIVE_AGENT_CHOICES)}))
    ok = all(item["ok"] for item in checks)
    status = "COMPLETE" if ok else "PARTIAL"
    blockers = [item["name"] for item in checks if not item["ok"]]
    return {"ok": ok, "status": status, "proof_version": 1, "live_agent": live_agent or "", "checks": checks, "blockers": blockers, "completion_rule": "COMPLETE is emitted only when every required machine-checked proof lane passes, including one live coding-agent run."}


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

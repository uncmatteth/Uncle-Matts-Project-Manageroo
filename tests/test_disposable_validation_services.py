from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from manageroo.errors import SafetyError
from manageroo.validation_services import provision_disposable_validation_environment


class _DockerFixture:
    def __init__(
        self,
        *,
        ready: bool = True,
        existing_labels: dict[str, str] | None = None,
        remove_error: str | None = None,
    ) -> None:
        self.calls: list[list[str]] = []
        self.ready = ready
        self.existing_labels = existing_labels
        self.remove_error = remove_error

    def __call__(
        self,
        argv: list[str],
        *,
        cwd: Path,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, timeout
        self.calls.append(list(argv))
        if argv[:3] == ["docker", "compose", "config"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(
                    {
                        "services": {
                            "postgres": {"image": "postgres:17-alpine"},
                            "web": {"image": "example.invalid/web:dev"},
                        }
                    }
                ),
                "",
            )
        if argv[:3] == ["docker", "container", "inspect"]:
            if self.existing_labels is None:
                return subprocess.CompletedProcess(argv, 1, "", "No such object")
            return subprocess.CompletedProcess(
                argv,
                0,
                json.dumps(self.existing_labels) + "\n",
                "",
            )
        if argv[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(argv, 0, "a" * 64 + "\n", "")
        if argv[:2] == ["docker", "port"]:
            return subprocess.CompletedProcess(argv, 0, "127.0.0.1:49152\n", "")
        if argv[:2] == ["docker", "exec"]:
            return subprocess.CompletedProcess(
                argv,
                0 if self.ready else 1,
                "accepting connections\n" if self.ready else "",
                "" if self.ready else "not ready",
            )
        if argv[:3] == ["docker", "rm", "-f"]:
            if self.remove_error is not None:
                return subprocess.CompletedProcess(argv, 1, "", self.remove_error)
            return subprocess.CompletedProcess(argv, 0, argv[-1] + "\n", "")
        raise AssertionError(f"Unexpected Docker command: {argv!r}")


def _postgres_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "docker-compose.yml").write_text(
        "services:\n"
        "  postgres:\n"
        "    image: postgres:17-alpine\n"
        "    volumes:\n"
        "      - project_database:/var/lib/postgresql/data\n",
        encoding="utf-8",
    )
    (repo / "tests" / "database.test.mjs").write_text(
        "const enabled = process.env.TEST_DATABASE_URL "
        "&& process.env.BTT_ALLOW_DATABASE_RESET === 'true';\n",
        encoding="utf-8",
    )
    return repo


class DisposableValidationServiceTests(unittest.TestCase):
    def test_owned_postgres_is_ephemeral_scoped_and_always_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _postgres_repo(Path(temp))
            before = {
                path.relative_to(repo): path.read_bytes()
                for path in repo.rglob("*")
                if path.is_file()
            }
            docker = _DockerFixture()
            events: list[dict] = []

            with provision_disposable_validation_environment(
                repo,
                run=docker,
                progress=events.append,
                sleep=lambda _seconds: None,
                password_factory=lambda: "manageroo-test-password",
            ) as child_env:
                self.assertEqual(
                    child_env["TEST_DATABASE_URL"],
                    "postgresql://manageroo:manageroo-test-password@127.0.0.1:49152/manageroo_test",
                )
                self.assertEqual(child_env["BTT_ALLOW_DATABASE_RESET"], "true")
                self.assertNotIn("TEST_DATABASE_URL", os.environ)
                self.assertNotIn("BTT_ALLOW_DATABASE_RESET", os.environ)
                self.assertFalse(any(call[:3] == ["docker", "rm", "-f"] for call in docker.calls))

            run_call = next(call for call in docker.calls if call[:2] == ["docker", "run"])
            self.assertIn("--rm", run_call)
            self.assertIn("--mount", run_call)
            self.assertIn("type=tmpfs,destination=/var/lib/postgresql/data", run_call)
            self.assertIn("127.0.0.1::5432", run_call)
            self.assertNotIn("project_database", run_call)
            self.assertEqual(
                sum(call[:3] == ["docker", "rm", "-f"] for call in docker.calls),
                1,
            )
            self.assertEqual([event["phase"] for event in events], [
                "validation-service-start",
                "validation-service-ready",
                "validation-service-cleanup",
            ])
            after = {
                path.relative_to(repo): path.read_bytes()
                for path in repo.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)

    def test_cleanup_runs_when_supervised_work_raises(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _postgres_repo(Path(temp))
            docker = _DockerFixture()

            with self.assertRaisesRegex(RuntimeError, "child failed"):
                with provision_disposable_validation_environment(
                    repo,
                    run=docker,
                    sleep=lambda _seconds: None,
                ):
                    raise RuntimeError("child failed")

            self.assertEqual(
                sum(call[:3] == ["docker", "rm", "-f"] for call in docker.calls),
                1,
            )

    def test_cleanup_failure_is_reported_after_successful_supervised_work(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _postgres_repo(Path(temp))
            docker = _DockerFixture(remove_error="daemon refused cleanup")

            with self.assertRaisesRegex(
                SafetyError,
                "could not remove its disposable PostgreSQL container",
            ):
                with provision_disposable_validation_environment(
                    repo,
                    run=docker,
                    sleep=lambda _seconds: None,
                ):
                    pass

    def test_cleanup_failure_does_not_replace_original_supervisor_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _postgres_repo(Path(temp))
            docker = _DockerFixture(remove_error="daemon refused cleanup")

            with self.assertRaisesRegex(RuntimeError, "child failed") as caught:
                with provision_disposable_validation_environment(
                    repo,
                    run=docker,
                    sleep=lambda _seconds: None,
                ):
                    raise RuntimeError("child failed")

            self.assertTrue(
                any("cleanup also failed" in note for note in getattr(caught.exception, "__notes__", [])),
                getattr(caught.exception, "__notes__", []),
            )

    def test_unrecognized_or_unversioned_database_service_is_not_executed(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _postgres_repo(Path(temp))
            docker = _DockerFixture()

            (repo / "docker-compose.yml").write_text(
                "services:\n  postgres:\n    image: attacker.invalid/postgres:latest\n",
                encoding="utf-8",
            )
            with provision_disposable_validation_environment(repo, run=docker) as child_env:
                self.assertEqual(child_env, {})

            self.assertEqual(docker.calls, [])

    def test_database_url_without_explicit_reset_guard_is_not_provisioned(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _postgres_repo(Path(temp))
            docker = _DockerFixture()
            (repo / "tests" / "database.test.mjs").write_text(
                "const url = process.env.TEST_DATABASE_URL;\n",
                encoding="utf-8",
            )

            with provision_disposable_validation_environment(repo, run=docker) as child_env:
                self.assertEqual(child_env, {})

            self.assertEqual(docker.calls, [])

    def test_required_disposable_database_reports_missing_docker_before_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _postgres_repo(Path(temp))

            def missing_docker(
                argv: list[str], *, cwd: Path, timeout: int
            ) -> subprocess.CompletedProcess[str]:
                del argv, cwd, timeout
                raise FileNotFoundError("docker")

            with self.assertRaisesRegex(
                SafetyError,
                "requires Docker to create its disposable PostgreSQL validation database",
            ):
                with provision_disposable_validation_environment(repo, run=missing_docker):
                    self.fail("the queue must not start without its required test database")

    def test_exact_stale_owned_container_is_removed_before_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _postgres_repo(Path(temp))
            from manageroo.validation_services import _repository_identity

            docker = _DockerFixture(
                existing_labels={
                    "manageroo.validation-service": "postgresql",
                    "manageroo.repository": _repository_identity(repo.resolve()),
                }
            )

            with provision_disposable_validation_environment(
                repo,
                run=docker,
                sleep=lambda _seconds: None,
            ):
                pass

            inspect_index = next(
                index
                for index, call in enumerate(docker.calls)
                if call[:3] == ["docker", "container", "inspect"]
            )
            remove_indexes = [
                index
                for index, call in enumerate(docker.calls)
                if call[:3] == ["docker", "rm", "-f"]
            ]
            run_index = next(
                index
                for index, call in enumerate(docker.calls)
                if call[:2] == ["docker", "run"]
            )
            self.assertEqual(len(remove_indexes), 2)
            self.assertLess(inspect_index, remove_indexes[0])
            self.assertLess(remove_indexes[0], run_index)

    def test_similarly_named_unowned_container_is_never_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = _postgres_repo(Path(temp))
            docker = _DockerFixture(
                existing_labels={
                    "manageroo.validation-service": "postgresql",
                    "manageroo.repository": "different-repository",
                }
            )

            with self.assertRaisesRegex(
                SafetyError,
                "does not carry this repository's exact ownership labels",
            ):
                with provision_disposable_validation_environment(repo, run=docker):
                    self.fail("an unowned container must block before the queue")

            self.assertFalse(any(call[:3] == ["docker", "rm", "-f"] for call in docker.calls))
            self.assertFalse(any(call[:2] == ["docker", "run"] for call in docker.calls))


if __name__ == "__main__":
    unittest.main()

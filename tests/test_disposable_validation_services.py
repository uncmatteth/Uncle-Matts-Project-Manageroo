from __future__ import annotations

import json
import os
import subprocess
import sys
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
    def test_src_layout_project_is_installed_in_disposable_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            (repo / "src" / "example").mkdir(parents=True)
            (repo / "tests").mkdir()
            (repo / "pyproject.toml").write_text(
                "[build-system]\n"
                "requires = []\n"
                "build-backend = 'fixture_backend'\n"
                "backend-path = ['.']\n"
                "\n"
                "[project]\n"
                "name = 'example-fixture'\n"
                "version = '1'\n"
                "dependencies = []\n"
                "\n"
                "[tool.pytest.ini_options]\n"
                "testpaths = ['tests']\n",
                encoding="utf-8",
            )
            (repo / "src" / "example" / "__init__.py").write_text(
                "VALUE = 42\n",
                encoding="utf-8",
            )
            (repo / "tests" / "test_import.py").write_text(
                "from example import VALUE\n\nassert VALUE == 42\n",
                encoding="utf-8",
            )
            (repo / "fixture_backend.py").write_text(
                "from pathlib import Path\n"
                "from zipfile import ZIP_DEFLATED, ZipFile\n\n"
                "def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):\n"
                "    name = 'example_fixture-1-py3-none-any.whl'\n"
                "    wheel = Path(wheel_directory) / name\n"
                "    with ZipFile(wheel, 'w', ZIP_DEFLATED) as archive:\n"
                "        archive.write('src/example/__init__.py', 'example/__init__.py')\n"
                "        archive.writestr('example_fixture-1.dist-info/METADATA', "
                "'Metadata-Version: 2.1\\nName: example-fixture\\nVersion: 1\\n')\n"
                "        archive.writestr('example_fixture-1.dist-info/WHEEL', "
                "'Wheel-Version: 1.0\\nGenerator: fixture\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n')\n"
                "        archive.writestr('example_fixture-1.dist-info/RECORD', '')\n"
                "    return name\n",
                encoding="utf-8",
            )

            def offline_runner(
                argv: list[str], *, cwd: Path, timeout: int
            ) -> subprocess.CompletedProcess[str]:
                if argv[1:4] == ["-m", "pip", "install"] and "pytest>=8,<10" in argv:
                    return subprocess.CompletedProcess(argv, 0, "", "")
                return subprocess.run(
                    argv,
                    cwd=cwd,
                    timeout=timeout,
                    text=True,
                    capture_output=True,
                    check=False,
                    shell=False,
                )

            with provision_disposable_validation_environment(
                repo,
                run=offline_runner,
            ) as child_env:
                environment = os.environ.copy()
                environment.update(child_env)
                environment.pop("PYTHONPATH", None)
                result = subprocess.run(
                    ["python", "tests/test_import.py"],
                    cwd=repo,
                    env=environment,
                    timeout=30,
                    text=True,
                    capture_output=True,
                    check=False,
                    shell=False,
                )

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_pep621_pytest_project_gets_disposable_dependency_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            (repo / "tests").mkdir(parents=True)
            (repo / "pyproject.toml").write_text(
                "[project]\n"
                "name = 'fixture'\n"
                "version = '1'\n"
                "dependencies = ['Pillow>=10']\n"
                "\n"
                "[tool.pytest.ini_options]\n"
                "testpaths = ['tests']\n",
                encoding="utf-8",
            )
            (repo / "tests" / "test_image.py").write_text(
                "from PIL import Image\n",
                encoding="utf-8",
            )
            before = {
                path.relative_to(repo): path.read_bytes()
                for path in repo.rglob("*")
                if path.is_file()
            }
            calls: list[list[str]] = []
            events: list[dict] = []
            created_environment: Path | None = None

            def runner(
                argv: list[str], *, cwd: Path, timeout: int
            ) -> subprocess.CompletedProcess[str]:
                nonlocal created_environment
                del timeout
                self.assertEqual(cwd, repo)
                calls.append(list(argv))
                if argv[:3] == [sys.executable, "-m", "venv"]:
                    created_environment = Path(argv[3])
                    executable_dir = created_environment / (
                        "Scripts" if os.name == "nt" else "bin"
                    )
                    executable_dir.mkdir(parents=True)
                    python_name = "python.exe" if os.name == "nt" else "python"
                    (executable_dir / python_name).write_text("fixture", encoding="utf-8")
                    return subprocess.CompletedProcess(argv, 0, "", "")
                return subprocess.CompletedProcess(argv, 0, "installed\n", "")

            with provision_disposable_validation_environment(
                repo,
                run=runner,
                progress=events.append,
            ) as child_env:
                self.assertIsNotNone(created_environment)
                assert created_environment is not None
                executable_dir = created_environment / (
                    "Scripts" if os.name == "nt" else "bin"
                )
                self.assertTrue(created_environment.is_dir())
                self.assertEqual(child_env["VIRTUAL_ENV"], str(created_environment))
                self.assertEqual(child_env["PYTHONNOUSERSITE"], "1")
                self.assertEqual(
                    child_env["PATH"].split(os.pathsep)[0],
                    str(executable_dir),
                )
                self.assertNotIn("VIRTUAL_ENV", os.environ)

            assert created_environment is not None
            self.assertFalse(created_environment.exists())
            self.assertEqual(calls[0][:3], [sys.executable, "-m", "venv"])
            self.assertEqual(calls[1][1:4], ["-m", "pip", "install"])
            self.assertIn("pytest>=8,<10", calls[1])
            self.assertIn("Pillow>=10", calls[1])
            self.assertLess(calls[1].index("--"), calls[1].index("Pillow>=10"))
            self.assertEqual(
                [event["phase"] for event in events],
                [
                    "validation-environment-start",
                    "validation-environment-ready",
                    "validation-environment-cleanup",
                ],
            )
            after = {
                path.relative_to(repo): path.read_bytes()
                for path in repo.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)

    def test_python_dependency_failure_stops_before_queue_and_cleans_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\n"
                "name = 'fixture'\n"
                "version = '1'\n"
                "dependencies = ['missing-package==1']\n"
                "\n"
                "[tool.pytest.ini_options]\n",
                encoding="utf-8",
            )
            events: list[dict] = []
            created_environment: Path | None = None

            def runner(
                argv: list[str], *, cwd: Path, timeout: int
            ) -> subprocess.CompletedProcess[str]:
                nonlocal created_environment
                del cwd, timeout
                if argv[:3] == [sys.executable, "-m", "venv"]:
                    created_environment = Path(argv[3])
                    executable_dir = created_environment / (
                        "Scripts" if os.name == "nt" else "bin"
                    )
                    executable_dir.mkdir(parents=True)
                    python_name = "python.exe" if os.name == "nt" else "python"
                    (executable_dir / python_name).write_text("fixture", encoding="utf-8")
                    return subprocess.CompletedProcess(argv, 0, "", "")
                return subprocess.CompletedProcess(
                    argv,
                    1,
                    "",
                    "No matching distribution found for missing-package==1",
                )

            with self.assertRaisesRegex(
                SafetyError,
                "dependency installation failed with exit code 1",
            ) as caught:
                with provision_disposable_validation_environment(
                    repo,
                    run=runner,
                    progress=events.append,
                ):
                    self.fail("the queue must not start without declared dependencies")

            assert created_environment is not None
            self.assertFalse(created_environment.exists())
            self.assertIn("missing-package==1", str(caught.exception))
            self.assertEqual(
                [event["phase"] for event in events],
                [
                    "validation-environment-start",
                    "validation-environment-cleanup",
                ],
            )

    def test_static_test_and_dev_optional_dependencies_are_installed(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\n"
                "name = 'fixture'\n"
                "version = '1'\n"
                "dependencies = ['runtime-package==1']\n"
                "\n"
                "[project.optional-dependencies]\n"
                "test = ['test-package==2']\n"
                "dev = ['dev-package==3']\n"
                "docs = ['docs-package==4']\n"
                "\n"
                "[tool.pytest.ini_options]\n",
                encoding="utf-8",
            )
            calls: list[list[str]] = []

            def runner(
                argv: list[str], *, cwd: Path, timeout: int
            ) -> subprocess.CompletedProcess[str]:
                del cwd, timeout
                calls.append(list(argv))
                if argv[:3] == [sys.executable, "-m", "venv"]:
                    environment = Path(argv[3])
                    executable_dir = environment / (
                        "Scripts" if os.name == "nt" else "bin"
                    )
                    executable_dir.mkdir(parents=True)
                    python_name = "python.exe" if os.name == "nt" else "python"
                    (executable_dir / python_name).write_text("fixture", encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "", "")

            with provision_disposable_validation_environment(repo, run=runner):
                pass

            install = calls[1]
            self.assertIn("runtime-package==1", install)
            self.assertIn("test-package==2", install)
            self.assertIn("dev-package==3", install)
            self.assertNotIn("docs-package==4", install)

    def test_malformed_python_dependency_manifest_stops_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\n"
                "name = 'fixture'\n"
                "version = '1'\n"
                "dependencies = 'Pillow>=10'\n"
                "\n"
                "[tool.pytest.ini_options]\n",
                encoding="utf-8",
            )
            calls: list[list[str]] = []

            def runner(
                argv: list[str], *, cwd: Path, timeout: int
            ) -> subprocess.CompletedProcess[str]:
                del cwd, timeout
                calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "", "")

            with self.assertRaisesRegex(
                SafetyError,
                "project.dependencies must be a bounded string list",
            ):
                with provision_disposable_validation_environment(repo, run=runner):
                    self.fail("the queue must not start from a malformed manifest")

            self.assertEqual(calls, [])

    def test_option_like_python_dependency_stops_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            (repo / "pyproject.toml").write_text(
                "[project]\n"
                "name = 'fixture'\n"
                "version = '1'\n"
                "dependencies = ['--target=/tmp/manageroo-escape', 'example-package']\n"
                "\n"
                "[tool.pytest.ini_options]\n",
                encoding="utf-8",
            )
            calls: list[list[str]] = []

            def runner(
                argv: list[str], *, cwd: Path, timeout: int
            ) -> subprocess.CompletedProcess[str]:
                del cwd, timeout
                calls.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, "", "")

            with self.assertRaisesRegex(
                SafetyError,
                "project.dependencies contains an unsafe requirement",
            ):
                with provision_disposable_validation_environment(repo, run=runner):
                    self.fail("pip options from project dependencies must be rejected")

            self.assertEqual(calls, [])

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

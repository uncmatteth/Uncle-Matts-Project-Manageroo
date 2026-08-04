from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import quote

from .errors import SafetyError


_COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
_IGNORED_DIRECTORIES = frozenset(
    {".git", ".clawpatch", ".manageroo", "node_modules", "dist", "build", "target", ".venv", "venv"}
)
_TEST_SUFFIXES = frozenset(
    {".cjs", ".js", ".jsx", ".mjs", ".py", ".rb", ".ts", ".tsx"}
)
_OFFICIAL_POSTGRES_IMAGE = re.compile(
    r"^(?:(?:docker\.io/)?library/)?postgres:"
    r"(?:[1-9][0-9]*(?:\.[0-9]+)?(?:-[A-Za-z0-9_.-]+)?|sha256:[0-9a-f]{64})$"
)
_IMAGE_LINE = re.compile(r"(?m)^\s*image:\s*['\"]?([^\s#'\"]+)['\"]?\s*(?:#.*)?$")
_RESET_ENV = re.compile(r"\b([A-Z][A-Z0-9_]*ALLOW_DATABASE_RESET)\b")
_CONTAINER_ID = re.compile(r"^[0-9a-f]{12,64}$")
_MAX_TEST_SOURCE_BYTES = 24 * 1024 * 1024
_DEFAULT_READY_SECONDS = 90


@dataclass(frozen=True)
class PostgresTestContract:
    compose_file: Path
    image: str
    url_env: str
    reset_envs: tuple[str, ...]


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
Progress = Callable[[dict[str, object]], None]


def _run_command(
    argv: list[str], *, cwd: Path, timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        timeout=timeout,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )


def _repository_identity(repo: Path) -> str:
    return hashlib.sha256(os.fsencode(str(repo.resolve()))).hexdigest()


def _recover_stale_owned_container(
    repo: Path,
    container_name: str,
    repository_identity: str,
    *,
    run: RunCommand,
) -> None:
    try:
        result = run(
            [
                "docker",
                "container",
                "inspect",
                "--format",
                "{{json .Config.Labels}}",
                container_name,
            ],
            cwd=repo,
            timeout=30,
        )
    except (FileNotFoundError, OSError) as exc:
        raise SafetyError(
            "This repository requires Docker to create its disposable PostgreSQL "
            "validation database. Install and start Docker, then resume the stopped finding."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SafetyError("Disposable PostgreSQL ownership inspection timed out.") from exc
    if result.returncode != 0:
        missing = (result.stderr or "").casefold()
        if "no such object" in missing or "no such container" in missing:
            return
        raise SafetyError(
            "Manageroo could not inspect prior disposable PostgreSQL ownership: "
            + (result.stderr or result.stdout or "unknown Docker error")[-2000:]
        )
    try:
        labels = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SafetyError("Docker returned malformed disposable PostgreSQL ownership labels.") from exc
    expected = {
        "manageroo.validation-service": "postgresql",
        "manageroo.repository": repository_identity,
    }
    if not isinstance(labels, dict) or any(labels.get(key) != value for key, value in expected.items()):
        raise SafetyError(
            "The existing disposable PostgreSQL container name does not carry this "
            "repository's exact ownership labels. Manageroo left it untouched."
        )
    _remove_container(repo, container_name, run=run)


def _test_contract_envs(repo: Path) -> tuple[str, tuple[str, ...]] | None:
    total = 0
    reset_envs: set[str] = set()
    found_url = False
    for root, directories, files in os.walk(repo):
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in _IGNORED_DIRECTORIES
        )
        root_path = Path(root)
        for name in sorted(files):
            path = root_path / name
            if path.suffix.lower() not in _TEST_SUFFIXES or path.is_symlink():
                continue
            relative = path.relative_to(repo).as_posix().lower()
            if "test" not in relative and "spec" not in relative:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            total += size
            if total > _MAX_TEST_SOURCE_BYTES:
                raise SafetyError(
                    "Manageroo refused unbounded disposable-database contract discovery."
                )
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "TEST_DATABASE_URL" not in text:
                continue
            local_reset_envs = set(_RESET_ENV.findall(text))
            if not local_reset_envs:
                continue
            found_url = True
            reset_envs.update(local_reset_envs)
    if not found_url or not reset_envs:
        return None
    return "TEST_DATABASE_URL", tuple(sorted(reset_envs))


def _compose_contract(repo: Path) -> PostgresTestContract | None:
    compose_files = [repo / name for name in _COMPOSE_FILES if (repo / name).is_file()]
    if len(compose_files) != 1:
        return None
    compose_file = compose_files[0]
    if compose_file.is_symlink() or compose_file.resolve().parent != repo.resolve():
        return None
    try:
        raw = compose_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    raw_images = sorted(set(_IMAGE_LINE.findall(raw)))
    postgres_images = [image for image in raw_images if _OFFICIAL_POSTGRES_IMAGE.fullmatch(image)]
    if len(postgres_images) != 1:
        return None
    env_contract = _test_contract_envs(repo)
    if env_contract is None:
        return None
    url_env, reset_envs = env_contract
    return PostgresTestContract(
        compose_file=compose_file,
        image=postgres_images[0],
        url_env=url_env,
        reset_envs=reset_envs,
    )


def _checked(
    run: RunCommand,
    argv: list[str],
    *,
    repo: Path,
    timeout: int,
    action: str,
) -> subprocess.CompletedProcess[str]:
    try:
        result = run(argv, cwd=repo, timeout=timeout)
    except (FileNotFoundError, OSError) as exc:
        raise SafetyError(
            "This repository requires Docker to create its disposable PostgreSQL "
            "validation database. Install and start Docker, then resume the stopped finding."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SafetyError(f"Disposable PostgreSQL {action} timed out.") from exc
    if result.returncode != 0:
        output = "\n".join(value for value in (result.stdout, result.stderr) if value)
        raise SafetyError(
            f"Disposable PostgreSQL {action} failed with exit code {result.returncode}: "
            f"{output[-2000:]}"
        )
    return result


def _verified_postgres_image(
    repo: Path,
    contract: PostgresTestContract,
    *,
    run: RunCommand,
) -> str:
    result = _checked(
        run,
        ["docker", "compose", "config", "--format", "json"],
        repo=repo,
        timeout=60,
        action="compose inspection",
    )
    try:
        payload = json.loads(result.stdout)
        services = payload["services"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SafetyError("Docker Compose did not return a valid service definition.") from exc
    images = sorted(
        {
            str(service.get("image", ""))
            for service in services.values()
            if isinstance(service, dict)
            and _OFFICIAL_POSTGRES_IMAGE.fullmatch(str(service.get("image", "")))
        }
    )
    if images != [contract.image]:
        raise SafetyError(
            "The resolved Docker Compose PostgreSQL image does not match the exact "
            "official versioned image declared by the repository."
        )
    return contract.image


def _published_port(
    repo: Path,
    container_id: str,
    *,
    run: RunCommand,
) -> int:
    result = _checked(
        run,
        ["docker", "port", container_id, "5432/tcp"],
        repo=repo,
        timeout=30,
        action="port inspection",
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    loopback = [line for line in lines if line.startswith("127.0.0.1:")]
    if len(loopback) != 1:
        raise SafetyError("Disposable PostgreSQL did not publish exactly one loopback port.")
    try:
        port = int(loopback[0].rsplit(":", 1)[1])
    except (IndexError, ValueError) as exc:
        raise SafetyError("Disposable PostgreSQL returned an invalid loopback port.") from exc
    if not 1 <= port <= 65535:
        raise SafetyError("Disposable PostgreSQL returned an out-of-range loopback port.")
    return port


def _remove_container(
    repo: Path,
    container_id: str,
    *,
    run: RunCommand,
) -> None:
    try:
        result = run(["docker", "rm", "-f", container_id], cwd=repo, timeout=60)
    except (FileNotFoundError, OSError) as exc:
        raise SafetyError(
            "Manageroo could not remove its disposable PostgreSQL container because "
            "Docker is unavailable."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise SafetyError(
            "Manageroo timed out removing its disposable PostgreSQL container."
        ) from exc
    if result.returncode != 0:
        output = "\n".join(value for value in (result.stdout, result.stderr) if value)
        raise SafetyError(
            "Manageroo could not remove its disposable PostgreSQL container: "
            + output[-2000:]
        )


@contextmanager
def provision_disposable_validation_environment(
    repo: Path,
    *,
    run: RunCommand = _run_command,
    progress: Progress | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    password_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
) -> Iterator[dict[str, str]]:
    root = repo.expanduser().resolve()
    contract = _compose_contract(root)
    if contract is None:
        yield {}
        return
    if os.environ.get(contract.url_env) and all(
        os.environ.get(name) == "true" for name in contract.reset_envs
    ):
        yield {}
        return

    if progress is not None:
        progress(
            {
                "phase": "validation-service-start",
                "current": "?",
                "total": "?",
                "command": "create owned disposable PostgreSQL validation database",
                "attempt": 1,
                "max_attempts": 1,
            }
        )
    image = _verified_postgres_image(root, contract, run=run)
    password = password_factory()
    if not password or "\x00" in password:
        raise SafetyError("Disposable PostgreSQL generated an invalid password.")
    repository_identity = _repository_identity(root)
    container_name = f"manageroo-validation-postgres-{repository_identity[:16]}"
    _recover_stale_owned_container(
        root,
        container_name,
        repository_identity,
        run=run,
    )
    result = _checked(
        run,
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            container_name,
            "--label",
            "manageroo.validation-service=postgresql",
            "--label",
            f"manageroo.repository={repository_identity}",
            "--mount",
            "type=tmpfs,destination=/var/lib/postgresql/data",
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_DB=manageroo_test",
            "--env",
            "POSTGRES_USER=manageroo",
            "--env",
            f"POSTGRES_PASSWORD={password}",
            "--pull=missing",
            image,
        ],
        repo=root,
        timeout=180,
        action="startup",
    )
    container_id = result.stdout.strip()
    if not _CONTAINER_ID.fullmatch(container_id):
        raise SafetyError("Docker returned an invalid disposable PostgreSQL container ID.")

    body_error: BaseException | None = None
    try:
        port = _published_port(root, container_id, run=run)
        deadline = monotonic() + _DEFAULT_READY_SECONDS
        while True:
            try:
                ready = run(
                    [
                        "docker",
                        "exec",
                        container_id,
                        "pg_isready",
                        "-U",
                        "manageroo",
                        "-d",
                        "manageroo_test",
                    ],
                    cwd=root,
                    timeout=15,
                )
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
                ready = subprocess.CompletedProcess([], 1, "", "not ready")
            if ready.returncode == 0:
                break
            if monotonic() >= deadline:
                raise SafetyError(
                    "Disposable PostgreSQL did not become healthy within 90 seconds."
                )
            sleep(1)
        child_env = {
            contract.url_env: (
                "postgresql://manageroo:"
                + quote(password, safe="")
                + f"@127.0.0.1:{port}/manageroo_test"
            ),
            **{name: "true" for name in contract.reset_envs},
        }
        if progress is not None:
            progress(
                {
                    "phase": "validation-service-ready",
                    "current": "?",
                    "total": "?",
                    "detail": "owned disposable PostgreSQL validation database ready",
                }
            )
        yield child_env
    except BaseException as exc:
        body_error = exc
        raise
    finally:
        try:
            _remove_container(root, container_id, run=run)
        except SafetyError as cleanup_error:
            if body_error is None:
                raise
            body_error.add_note(f"Disposable PostgreSQL cleanup also failed: {cleanup_error}")
        else:
            if progress is not None:
                progress(
                    {
                        "phase": "validation-service-cleanup",
                        "current": "?",
                        "total": "?",
                        "detail": "owned disposable PostgreSQL validation database removed",
                    }
                )

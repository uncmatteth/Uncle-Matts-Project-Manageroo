from __future__ import annotations

import os
import json
import platform
import secrets
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from .base import AgentAdapter, AgentRequest, AgentResponse
from ..branding import FULL_NAME
from ..errors import AgentExecutionError
from ..runner import CommandRunner
from ..schema import extract_json, load_schema, validate
from ..util import atomic_write_json


_BWRAP_LOOPBACK_FAILURE = "bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted"
_DANGER_FALLBACK_ENV = "MANAGEROO_CODEX_DANGER_FULL_ACCESS_FALLBACK"
_CODEX_SANDBOX_REFERENCE = "https://learn.chatgpt.com/docs/sandboxing"
_MAX_PROFILE_SKILLS = 512
_MAX_PROFILE_BYTES = 1_000_000


def _sandbox_helper_name(system_name: str | None = None) -> str | None:
    return {
        "linux": "linux",
        "darwin": "macos",
        "windows": "windows",
    }.get((system_name or platform.system()).strip().lower())


def _sandbox_failure_guidance(system_name: str, argv: list[str]) -> dict[str, Any]:
    normalized = system_name.strip().lower()
    rerun = subprocess.list2cmdline(argv) if normalized == "windows" else shlex.join(argv)
    if normalized == "linux":
        guidance = (
            "OpenAI Codex on Linux and WSL2 requires bubblewrap, seccomp, and usable "
            "unprivileged user namespaces. Ubuntu 24.04 may also require the "
            "bwrap-userns-restrict AppArmor profile. If Codex is intentionally running "
            "inside an outer container, that container must provide the isolation boundary."
        )
        try:
            release = platform.freedesktop_os_release()
        except OSError:
            release = {}
        distro = str(release.get("ID", "")).casefold()
        version = str(release.get("VERSION_ID", ""))
        if distro == "ubuntu" and version.startswith("24.04"):
            next_commands = [
                "sudo apt install bubblewrap apparmor-profiles apparmor-utils",
                "sudo install -m 0644 /usr/share/apparmor/extra-profiles/bwrap-userns-restrict /etc/apparmor.d/bwrap-userns-restrict",
                "sudo apparmor_parser -r /etc/apparmor.d/bwrap-userns-restrict",
                rerun,
            ]
        elif shutil.which("apt-get"):
            next_commands = ["sudo apt install bubblewrap", rerun]
        elif shutil.which("dnf"):
            next_commands = ["sudo dnf install bubblewrap", rerun]
        elif shutil.which("yum"):
            next_commands = ["sudo yum install bubblewrap", rerun]
        elif shutil.which("pacman"):
            next_commands = ["sudo pacman -S --needed bubblewrap", rerun]
        elif shutil.which("zypper"):
            next_commands = ["sudo zypper install bubblewrap", rerun]
        else:
            next_commands = [rerun]
    elif normalized == "darwin":
        guidance = (
            "OpenAI Codex uses the built-in macOS Seatbelt sandbox. No Linux bubblewrap "
            "setup applies; repair or update the Codex installation, then rerun the native "
            "macOS sandbox diagnostic."
        )
        next_commands = [rerun]
    else:
        guidance = (
            "OpenAI Codex uses its native Windows sandbox from PowerShell, or the Linux "
            "sandbox under WSL2. Use the elevated native Windows sandbox when available; "
            "WSL1 is unsupported by current Codex releases."
        )
        next_commands = [rerun]
    return {
        "guidance": guidance,
        "next_commands": next_commands,
        "reference": _CODEX_SANDBOX_REFERENCE,
    }


def codex_sandbox_preflight(
    executable: str,
    runner: CommandRunner,
    cwd: Path,
    *,
    system_name: str | None = None,
) -> dict[str, Any]:
    """Exercise the native Codex sandbox before a real worker is launched."""
    helper = _sandbox_helper_name(system_name)
    if helper is None:
        return {
            "ok": False,
            "platform": system_name or platform.system(),
            "error": "Codex sandbox preflight supports Linux, macOS, and Windows only.",
        }
    argv = [
        executable,
        "sandbox",
        "--permission-profile",
        ":workspace",
        "-C",
        str(cwd),
        "--",
        sys.executable,
        "-c",
        "pass",
    ]
    result = runner.run(argv, cwd=cwd, timeout_seconds=30)
    report = {
        "ok": result.passed,
        "platform": system_name or platform.system(),
        "helper": helper,
        "argv": result.argv,
        "exit_code": result.exit_code,
        "output": (result.stdout + result.stderr)[-4000:].strip(),
    }
    if not result.passed:
        report.update(_sandbox_failure_guidance(system_name or platform.system(), argv))
    return report


def _codex_compatible_schema(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            node_type = node.get("type")
            properties = node.get("properties")
            if node_type == "object" or isinstance(properties, dict):
                node["additionalProperties"] = False
                if isinstance(properties, dict):
                    node["required"] = list(properties.keys())
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(normalized)
    return normalized


def _danger_fallback_enabled() -> bool:
    return os.environ.get(_DANGER_FALLBACK_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_exact_host_bwrap_failure(request: AgentRequest, result: Any) -> bool:
    """Recognize only the pre-worker host sandbox bootstrap failure.

    Agent-controlled output must not be able to request privilege escalation. The known
    bubblewrap failure occurs before a worker output file exists, produces no stdout, and
    emits only the exact host error line on stderr.
    """
    if result.passed or request.output_path.exists() or (result.stdout or "").strip():
        return False
    stderr_lines = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]
    return stderr_lines == [_BWRAP_LOOPBACK_FAILURE]


class CodexAdapter(AgentAdapter):
    """Runs one fresh Codex process per role.

    Workspace-write is always attempted first. A second danger-full-access launch is permitted
    only when the operator explicitly opted in before launch *and* the first process failed with
    the exact known host bubblewrap initialization error. Successful or unrelated worker output
    can never authorize escalation.
    """

    REQUIRED_FLAGS = ("--output-schema", "--output-last-message", "--sandbox", "--profile")

    @property
    def requires_host_capability_catalog(self) -> bool:
        return True

    def __init__(self, executable: str, runner: CommandRunner, model: str = ""):
        self.executable = executable
        self.runner = runner
        self.model = model
        self._before_worker_launch: Callable[[AgentRequest], AgentRequest] | None = None

    def set_before_worker_launch(self, callback: Callable[[AgentRequest], AgentRequest]) -> None:
        """Install a controller-owned hook that runs before every concrete Codex process."""
        self._before_worker_launch = callback

    def doctor(self, cwd: Path) -> dict:
        found = shutil.which(self.executable)
        if not found:
            return {
                "ok": False,
                "adapter": "codex",
                "executable": self.executable,
                "error": "Codex executable not found on PATH.",
            }
        version = self.runner.run([self.executable, "--version"], cwd=cwd, timeout_seconds=30)
        help_result = self.runner.run([self.executable, "exec", "--help"], cwd=cwd, timeout_seconds=30)
        missing = [flag for flag in self.REQUIRED_FLAGS if flag not in help_result.stdout]
        sandbox_preflight = codex_sandbox_preflight(self.executable, self.runner, cwd)
        return {
            "ok": version.passed and help_result.passed and not missing and sandbox_preflight["ok"],
            "adapter": "codex",
            "path": found,
            "version": version.stdout.strip() or version.stderr.strip(),
            "missing_required_flags": missing,
            "danger_full_access_fallback_opted_in": _danger_fallback_enabled(),
            "stderr_triggered_escalation": False,
            "task_scoped_skill_catalog": True,
            "sandbox_preflight": sandbox_preflight,
        }

    @staticmethod
    def _skill_catalog_entries(request: AgentRequest) -> tuple[list[str], list[str]]:
        entries = request.metadata.get("capability_catalog", [])
        if not entries:
            route = request.metadata.get("capability_route", {})
            entries = route.get("catalog_entries", []) if isinstance(route, dict) else []
        names: set[str] = set()
        paths: set[str] = set()
        for item in entries if isinstance(entries, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            path = str(item.get("path", "")).strip()
            if name:
                names.add(name.casefold())
            if path:
                paths.add(path)
        fallback_paths = request.metadata.get("capability_catalog_paths", [])
        if not fallback_paths:
            route = request.metadata.get("capability_route", {})
            fallback_paths = route.get("catalog_paths", []) if isinstance(route, dict) else []
        for value in fallback_paths if isinstance(fallback_paths, list) else []:
            path = str(value).strip()
            if path:
                paths.add(path)
                names.add(Path(path).parent.name.casefold())
        return sorted(names), sorted(paths)

    @contextmanager
    def _ephemeral_skill_profile(self, request: AgentRequest):
        names, paths = self._skill_catalog_entries(request)
        if not names and not paths:
            yield ""
            return
        identity_count = len(names) + len(paths)
        if identity_count > _MAX_PROFILE_SKILLS:
            raise AgentExecutionError(
                f"Refusing to create a Codex task profile with {identity_count} skill identities; "
                f"the safety limit is {_MAX_PROFILE_SKILLS}."
            )
        codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
        if not codex_home.is_dir():
            raise AgentExecutionError(f"Codex home is not an existing directory: {codex_home}")
        profile_name = f"manageroo-{secrets.token_hex(12)}"
        profile_path = codex_home / f"{profile_name}.config.toml"
        body = "".join(
            "[[skills.config]]\n"
            f"name = {json.dumps(name, ensure_ascii=False)}\n"
            "enabled = false\n\n"
            for name in names
        ) + "".join(
            "[[skills.config]]\n"
            f"path = {json.dumps(path, ensure_ascii=False)}\n"
            "enabled = false\n\n"
            for path in paths
        )
        encoded = body.encode("utf-8")
        if len(encoded) > _MAX_PROFILE_BYTES:
            raise AgentExecutionError(
                f"Refusing to create a {len(encoded)}-byte Codex task profile; "
                f"the safety limit is {_MAX_PROFILE_BYTES} bytes."
            )
        created = False
        try:
            with profile_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(body)
            created = True
            try:
                profile_path.chmod(0o600)
            except OSError:
                pass
            yield profile_name
        except OSError as exc:
            raise AgentExecutionError(f"Could not create isolated Codex task profile: {exc}") from exc
        finally:
            try:
                if created and (profile_path.is_file() or profile_path.is_symlink()):
                    profile_path.unlink()
            except OSError as exc:
                raise AgentExecutionError(f"Could not remove isolated Codex task profile: {exc}") from exc

    def _argv(
        self,
        request: AgentRequest,
        codex_schema_path: Path,
        *,
        sandbox: str,
        profile_name: str = "",
    ) -> list[str]:
        argv = [self.executable, "exec"]
        if profile_name:
            argv.extend(["--profile", profile_name])
        argv.extend([
            "--json",
            "--sandbox",
            sandbox,
            "--output-schema",
            str(codex_schema_path),
            "--output-last-message",
            str(request.output_path),
            "-C",
            str(request.cwd),
        ])
        if self.model:
            argv.extend(["--model", self.model])
        argv.append("-")
        return argv

    def _run_codex(self, request: AgentRequest, *, prompt: str, codex_schema_path: Path, sandbox: str):
        bounded_request = request
        if bounded_request.before_launch is not None:
            bounded_request = bounded_request.before_launch(bounded_request, True)
        with self._ephemeral_skill_profile(bounded_request) as profile_name:
            if self._before_worker_launch is not None:
                bounded_request = self._before_worker_launch(bounded_request)
            argv = self._argv(
                bounded_request,
                codex_schema_path,
                sandbox=sandbox,
                profile_name=profile_name,
            )
            result = self.runner.run(
                argv,
                cwd=bounded_request.cwd,
                timeout_seconds=bounded_request.timeout_seconds,
                input_text=prompt,
                log_name=f"agent-{bounded_request.output_path.parent.name}-{bounded_request.output_path.stem}",
            )
        return bounded_request, argv, result

    @staticmethod
    def _clear_prior_outputs(request: AgentRequest) -> None:
        for path in (request.output_path, request.output_path.with_suffix(".validated.json")):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            except OSError as exc:
                raise AgentExecutionError(f"Could not clear stale Codex output before launch: {path}: {exc}") from exc

    def run(self, request: AgentRequest) -> AgentResponse:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_prior_outputs(request)
        packet_text = request.prompt_path.read_text(encoding="utf-8", errors="replace")
        prompt = (
            f"You are a role inside {FULL_NAME}.\n"
            "The following packet is complete and authoritative. Do not rely on prior chat context. "
            "Follow it exactly. Return only JSON conforming to the supplied schema. "
            "Do not commit, push, switch branches, alter .git, or edit controller files.\n\n"
            "Do not create or update external resources, send messages, publish, deploy, "
            "open issues or pull requests, purchase anything, or perform account actions.\n\n"
            + packet_text
        )
        source_schema = load_schema(request.schema_path)
        codex_schema_path = request.output_path.with_suffix(".codex-schema.json")
        atomic_write_json(codex_schema_path, _codex_compatible_schema(source_schema))

        active_request, argv, result = self._run_codex(
            request,
            prompt=prompt,
            codex_schema_path=codex_schema_path,
            sandbox=request.sandbox,
        )

        if (
            request.sandbox == "workspace-write"
            and _is_exact_host_bwrap_failure(active_request, result)
        ):
            if not _danger_fallback_enabled():
                raise AgentExecutionError(
                    "Codex could not initialize its workspace-write bubblewrap sandbox on this host. "
                    "Manageroo refused to escalate automatically. To explicitly allow one unrestricted "
                    f"retry after this exact host-sandbox initialization failure, set {_DANGER_FALLBACK_ENV}=1 for this run."
                )
            self._clear_prior_outputs(request)
            active_request, argv, result = self._run_codex(
                request,
                prompt=prompt,
                codex_schema_path=codex_schema_path,
                sandbox="danger-full-access",
            )

        if not result.passed:
            stdout_tail = (result.stdout or "")[-8000:].strip()
            stderr_tail = (result.stderr or "")[-4000:].strip()
            details = []
            if stdout_tail:
                details.append("stdout:\n" + stdout_tail)
            if stderr_tail:
                details.append("stderr:\n" + stderr_tail)
            if not details:
                details.append("Codex produced no stdout or stderr diagnostics.")
            raise AgentExecutionError(
                f"Codex role {request.role!r} failed with exit code {result.exit_code}:\n" + "\n\n".join(details)
            )
        if not request.output_path.is_file() or request.output_path.is_symlink():
            raise AgentExecutionError(f"Codex did not create a fresh regular output-last-message file for role {request.role}.")
        raw = request.output_path.read_text(encoding="utf-8", errors="replace")
        data = extract_json(raw)
        validate(data, source_schema)
        atomic_write_json(request.output_path.with_suffix(".validated.json"), data)
        return AgentResponse(
            role=request.role,
            data=data,
            raw_text=raw,
            command=argv,
            stdout=result.stdout,
            stderr=result.stderr,
        )

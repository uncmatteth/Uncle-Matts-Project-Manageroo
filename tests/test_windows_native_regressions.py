from __future__ import annotations

import io
import importlib.util
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from manageroo.artifacts import ArtifactStore
from manageroo.branding import status_line
from manageroo.config import config_template
from manageroo.errors import SafetyError
from manageroo.release_ready_policy import _hold_release_head
from manageroo.runner import _platform_argv


ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_REPOSITORY = "uncmatteth/clawpatch-supervise"
SUPERVISOR_COMMIT = "b58cf4df9f973cbe2dfd42e2a84ea505b3c91727"
SUPERVISOR_SOURCE = (
    f"git+https://github.com/{SUPERVISOR_REPOSITORY}.git@{SUPERVISOR_COMMIT}"
)


def _active_supervisor_source(text: str, installer_name: str) -> str | None:
    powershell = installer_name.endswith(".ps1")
    if powershell:
        commit_prefix = '$SupervisorCommit = "'
        source_prefix = '$SupervisorSource = "'
        install_prefix = "& $VenvPython -m pip install "
        source_argument = "$SupervisorSource"
        commit_reference = "$SupervisorCommit"
    else:
        commit_prefix = 'SUPERVISOR_COMMIT="'
        source_prefix = 'SUPERVISOR_SOURCE="'
        install_prefix = '"${VENV_PYTHON}" -m pip install '
        source_argument = '"${SUPERVISOR_SOURCE}"'
        commit_reference = "${SUPERVISOR_COMMIT}"

    commit = ""
    source = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(commit_prefix) and line.endswith('"'):
            commit = line[len(commit_prefix) : -1]
            continue
        if line.startswith(source_prefix) and line.endswith('"'):
            source = line[len(source_prefix) : -1]
            continue
        if line.startswith(install_prefix):
            if not line.endswith(source_argument):
                return None
            return source.replace(commit_reference, commit)
    return None


class _RecordingBinaryInput:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, value: bytes) -> int:
        if not isinstance(value, bytes):
            raise TypeError("Git update-ref input must be bytes")
        self.data.extend(value)
        return len(value)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeTransaction:
    def __init__(self) -> None:
        self.stdin = _RecordingBinaryInput()
        self.stdout = io.BytesIO(b"start: ok\nprepare: ok\nabort: ok\n")
        self.stderr = io.BytesIO()
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = -9


class WindowsNativeRegressionTests(unittest.TestCase):
    def test_default_config_allows_the_native_windows_npm_shim(self):
        config = tomllib.loads(config_template("mock", []))

        self.assertIn("npm.cmd", config["safety"]["allowed_programs"])

    def test_windows_pid_probe_does_not_treat_invalid_pid_as_live(self):
        with (
            patch("manageroo.artifacts.os.name", "nt"),
            patch.object(ArtifactStore, "_windows_pid_is_live", return_value=False) as probe,
        ):
            self.assertFalse(ArtifactStore._pid_is_live(99_999_999))
        probe.assert_called_once_with(99_999_999)

    def test_release_head_transaction_writes_exact_lf_binary_protocol(self):
        transaction = _FakeTransaction()
        release_ready = SimpleNamespace(
            _git_output=lambda _repo, argv: (
                "refs/heads/main" if "symbolic-ref" in argv else "a" * 40
            )
        )

        with patch(
            "manageroo.release_ready_policy.subprocess.Popen",
            return_value=transaction,
        ) as popen:
            with _hold_release_head(release_ready, Path("repo")) as head:
                self.assertEqual(head, "a" * 40)

        self.assertEqual(
            bytes(transaction.stdin.data),
            (
                b"start\n"
                + b"update refs/heads/main "
                + (b"a" * 40)
                + b" "
                + (b"a" * 40)
                + b"\nprepare\nabort\n"
            ),
        )
        self.assertFalse(popen.call_args.kwargs.get("text", False))

    def test_status_line_falls_back_to_ascii_for_cp1252_stream(self):
        buffer = io.BytesIO()
        stream = io.TextIOWrapper(buffer, encoding="cp1252", write_through=True)

        status_line("RUN", "ready", stream=stream)

        rendered = buffer.getvalue().decode("cp1252")
        self.assertEqual(rendered, "* RUN - ready\n")

    def test_windows_supervisor_installer_selects_one_compatible_node_and_matching_npm(self):
        text = (ROOT / "Install-ClawPatch-Supervisor-Windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("function Resolve-NativeCommands", text)
        self.assertIn("Select-CompatibleNode", text)
        self.assertIn("Sort-Object -Property Version -Descending", text)
        self.assertIn("if ($candidate.Major -ge 22)", text)
        self.assertIn('Join-Path (Split-Path -Parent $NodeExe) "npm.cmd"', text)

    def test_windows_supervisor_launcher_pins_the_node_runtime_verified_by_installer(self):
        text = (ROOT / "Install-ClawPatch-Supervisor-Windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("$NodeRuntime = Split-Path -Parent $NodeExe", text)
        self.assertIn('set `"NODE_RUNTIME=$NodeRuntime`"', text)
        self.assertIn('if not exist `"$NodeExe`" (', text)
        self.assertIn("%NODE_RUNTIME%", text)
        self.assertIn('set `"PYTHONUTF8=1`"', text)
        self.assertIn('set `"PYTHONIOENCODING=utf-8`"', text)

    def test_macos_supervisor_installer_finds_standard_homebrew_locations(self):
        text = (ROOT / "Install-ClawPatch-Supervisor-macOS.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("/opt/homebrew/bin/brew /usr/local/bin/brew", text)
        self.assertIn('export PATH="$(dirname "${candidate}"):${PATH}"', text)

    def test_native_supervisor_installers_use_the_standalone_public_pin(self):
        for name in (
            "Install-ClawPatch-Supervisor-Windows.ps1",
            "Install-ClawPatch-Supervisor-macOS.sh",
        ):
            with self.subTest(installer=name):
                text = (ROOT / name).read_text(encoding="utf-8")
                self.assertEqual(_active_supervisor_source(text, name), SUPERVISOR_SOURCE)

    def test_native_supervisor_installer_pin_validation_rejects_comment_only_pins(self):
        fixtures = {
            "Install-ClawPatch-Supervisor-Windows.ps1": (
                f"# {SUPERVISOR_SOURCE}\n"
                '$SupervisorCommit = "main"\n'
                f'$SupervisorSource = "git+https://github.com/{SUPERVISOR_REPOSITORY}.git@'
                '$SupervisorCommit"\n'
                "& $VenvPython -m pip install --upgrade $SupervisorSource\n"
            ),
            "Install-ClawPatch-Supervisor-macOS.sh": (
                f"# {SUPERVISOR_SOURCE}\n"
                'SUPERVISOR_COMMIT="main"\n'
                f'SUPERVISOR_SOURCE="git+https://github.com/{SUPERVISOR_REPOSITORY}.git@'
                '${SUPERVISOR_COMMIT}"\n'
                '"${VENV_PYTHON}" -m pip install --upgrade "${SUPERVISOR_SOURCE}"\n'
            ),
        }

        for name, text in fixtures.items():
            with self.subTest(installer=name):
                self.assertNotEqual(_active_supervisor_source(text, name), SUPERVISOR_SOURCE)

    def test_release_verifier_allows_the_native_windows_suite_full_watchdog(self):
        spec = importlib.util.spec_from_file_location(
            "manageroo_verify_release_windows_regression",
            ROOT / "scripts" / "verify_release.py",
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertEqual(module.UNIT_TEST_TIMEOUT_SECONDS, 900)

    def test_windows_command_runner_launches_cmd_shims_through_comspec_without_shell(self):
        with (
            patch("manageroo.runner.os.name", "nt"),
            patch(
                "manageroo.runner.shutil.which",
                return_value=r"C:\Program Files\nodejs\codex.cmd",
            ),
        ):
            argv = _platform_argv(
                ["codex", "--version"],
                {"PATH": r"C:\Program Files\nodejs", "COMSPEC": r"C:\Windows\System32\cmd.exe"},
            )

        self.assertEqual(argv[:4], [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c"])
        self.assertEqual(argv[4], '"C:\\Program Files\\nodejs\\codex.cmd" --version')

    def test_windows_command_runner_rejects_cmd_metacharacters_in_shim_arguments(self):
        hostile_arguments = (
            "value&whoami",
            "value|whoami",
            "value<input",
            "value>output",
            "%PATH%",
            "value^escape",
            "value!expand",
            "(whoami)",
            'value"quoted',
            "value\rwhoami",
            "value\nwhoami",
        )
        with (
            patch("manageroo.runner.os.name", "nt"),
            patch(
                "manageroo.runner.shutil.which",
                return_value=r"C:\Program Files\nodejs\codex.cmd",
            ),
        ):
            for argument in hostile_arguments:
                with self.subTest(argument=argument), self.assertRaises(SafetyError):
                    _platform_argv(
                        ["codex", argument],
                        {
                            "PATH": r"C:\Program Files\nodejs",
                            "COMSPEC": r"C:\Windows\System32\cmd.exe",
                        },
                    )

    def test_windows_command_runner_keeps_safe_spaces_in_shim_arguments(self):
        with (
            patch("manageroo.runner.os.name", "nt"),
            patch(
                "manageroo.runner.shutil.which",
                return_value=r"C:\Program Files\nodejs\codex.cmd",
            ),
        ):
            argv = _platform_argv(
                ["codex", "value with spaces"],
                {
                    "PATH": r"C:\Program Files\nodejs",
                    "COMSPEC": r"C:\Windows\System32\cmd.exe",
                },
            )

        self.assertEqual(argv[4], '"C:\\Program Files\\nodejs\\codex.cmd" "value with spaces"')


if __name__ == "__main__":
    unittest.main()

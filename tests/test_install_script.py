import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from manageroo.install_status import launcher_is_manageroo_owned


ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = ROOT / "scripts" / "install.py"


def load_install_script():
    spec = importlib.util.spec_from_file_location("manageroo_install_script", INSTALL_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load installer script: {INSTALL_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _powershell_forwarding_map(text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    pattern = re.compile(
        r'^if \(\$(?P<parameter>[A-Za-z0-9]+)\) \{ \$InstallArgs \+= @\("(?P<flag>--[a-z0-9-]+)", \$(?P=parameter)\) \}$',
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        parameter = match.group("parameter")
        if parameter in mapping:
            raise AssertionError(f"PowerShell installer forwards {parameter} more than once")
        mapping[parameter] = match.group("flag")
    return mapping


class InstallScriptTests(unittest.TestCase):
    def test_autoreview_install_refuses_incomplete_existing_directory_without_backup(self):
        install = load_install_script()
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            destination = home / ".agents" / "skills" / "autoreview"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text("existing partial install\n", encoding="utf-8")

            def fake_checkout(**kwargs):
                source = kwargs["destination"] / "skills" / "autoreview"
                (source / "scripts").mkdir(parents=True)
                (source / "SKILL.md").write_text("downloaded\n", encoding="utf-8")
                (source / "scripts" / "autoreview").write_text("tool\n", encoding="utf-8")
                return {"resolved_commit": kwargs["commit"]}

            with patch.object(install.Path, "home", return_value=home), patch.object(
                install.shutil,
                "which",
                return_value="/usr/bin/git",
            ), patch.object(install, "_checkout_pinned_git_source", side_effect=fake_checkout):
                result = install.install_autoreview([], home / "prefix")

            self.assertFalse(result["installed"])
            self.assertIn("left it untouched", result["error"])
            self.assertEqual(
                (destination / "SKILL.md").read_text(encoding="utf-8"),
                "existing partial install\n",
            )
            self.assertEqual(
                list(destination.parent.glob("autoreview.manageroo-backup-*")),
                [],
            )

    def test_generated_launchers_have_verified_manageroo_ownership(self):
        install = load_install_script()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            python = root / "python"
            app_root = root / "app"
            prefix = root / "prefix"
            launcher = install.install_launcher(root / "posix-bin", python, app_root, prefix)
            self.assertTrue(launcher_is_manageroo_owned(launcher))

            with patch.object(install.os, "name", "nt"):
                launcher = install.install_launcher(root / "windows-bin", python, app_root, prefix)
            self.assertTrue(launcher_is_manageroo_owned(launcher))

    def test_windows_launcher_rejects_percent_expansion_in_each_interpolated_path(self):
        install = load_install_script()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            safe = root / "safe"
            path_arguments = {
                "python": (root / "%TESTVAR%" / "python.exe", safe, safe),
                "app_root": (safe, root / "%TESTVAR%" / "app", safe),
                "prefix": (safe, safe, root / "%TESTVAR%" / "prefix"),
            }
            for name, arguments in path_arguments.items():
                with self.subTest(path=name), patch.object(install.os, "name", "nt"):
                    with self.assertRaisesRegex(SystemExit, "unsafe for a Windows command launcher"):
                        install.install_launcher(root / name / "bin", *arguments)

    def test_agent_detection_reports_supported_coding_tools_already_on_the_machine(self):
        install = load_install_script()
        paths = {
            "codex": "/tools/codex",
            "claude": "/tools/claude",
            "gemini": None,
        }
        with patch.object(install.shutil, "which", side_effect=lambda name: paths.get(name)):
            self.assertEqual(
                install.detect_coding_agents(),
                [
                    {
                        "preset": "codex",
                        "name": "Codex",
                        "executable": "codex",
                        "path": "/tools/codex",
                    },
                    {
                        "preset": "claude-code",
                        "name": "Claude Code",
                        "executable": "claude",
                        "path": "/tools/claude",
                    },
                ],
            )

    def test_agent_setup_uses_the_only_detected_tool_without_an_extra_question(self):
        install = load_install_script()
        detected = [
            {
                "preset": "gemini",
                "name": "Gemini CLI",
                "executable": "gemini",
                "path": "/tools/gemini",
            }
        ]
        output = io.StringIO()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input") as prompt:
                with redirect_stdout(output):
                    result = install.choose_agent_setup("ask", False, False, detected)
        self.assertEqual(result, {"preference": "auto", "install_codex": False})
        prompt.assert_not_called()
        self.assertIn("Found Gemini CLI", output.getvalue())
        self.assertIn("use it automatically", output.getvalue())

    def test_agent_setup_lets_people_choose_when_multiple_tools_are_detected(self):
        install = load_install_script()
        detected = [
            {"preset": "codex", "name": "Codex", "executable": "codex", "path": "/tools/codex"},
            {
                "preset": "claude-code",
                "name": "Claude Code",
                "executable": "claude",
                "path": "/tools/claude",
            },
        ]
        output = io.StringIO()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value="3"):
                with redirect_stdout(output):
                    result = install.choose_agent_setup("ask", False, False, detected)
        self.assertEqual(result, {"preference": "claude-code", "install_codex": False})
        self.assertIn("Automatic selection (recommended)", output.getvalue())
        self.assertIn("Claude Code", output.getvalue())

    def test_agent_setup_offers_codex_when_no_supported_tool_is_found(self):
        install = load_install_script()
        output = io.StringIO()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value=""):
                with redirect_stdout(output):
                    result = install.choose_agent_setup("ask", False, False, [])
        self.assertEqual(result, {"preference": "codex", "install_codex": True})
        self.assertIn("did not find a supported coding-agent CLI", output.getvalue())

    def test_agent_setup_noninteractive_does_not_silently_install_codex(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=False):
            result = install.choose_agent_setup("ask", False, False, [])
        self.assertEqual(result, {"preference": "auto", "install_codex": False})

    def test_agent_setup_honors_explicit_agent_and_codex_flags(self):
        install = load_install_script()
        self.assertEqual(
            install.choose_agent_setup("gemini", False, False, []),
            {"preference": "gemini", "install_codex": False},
        )
        self.assertEqual(
            install.choose_agent_setup("codex", True, False, []),
            {"preference": "codex", "install_codex": True},
        )

    def test_existing_agent_is_recorded_as_detected_instead_of_skipped(self):
        install = load_install_script()
        detected = [
            {
                "preset": "codex",
                "name": "Codex",
                "executable": "codex",
                "path": "/tools/codex",
            }
        ]

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            bin_dir = root / "bin"

            def create_venv(venv_root):
                python = Path(venv_root) / "bin" / "python"
                python.parent.mkdir(parents=True)
                python.write_text("fixture\n", encoding="utf-8")

            argv = [
                str(INSTALL_SCRIPT),
                "--prefix",
                str(prefix),
                "--bin-dir",
                str(bin_dir),
                "--skip-tests",
                "--skip-self-test",
                "--skip-stack",
                "--skip-skill-pack",
                "--token-mode",
                "off",
                "--agent",
                "auto",
                "--stack-doctor",
                "skip",
                "--project-discovery",
                "skip",
                "--no-music",
                "--no-animation",
            ]
            command_result = SimpleNamespace(stdout="manageroo fixture\n")
            sandbox = {"configured": True, "next_commands": []}
            with (
                patch.object(install.sys, "argv", argv),
                patch.object(install, "print_banner", return_value=None),
                patch.object(install, "ThemePlayback", return_value=nullcontext()),
                patch.object(install, "prepend_tool_paths"),
                patch.object(install.shutil, "which", return_value="/usr/bin/git"),
                patch.object(install, "detect_coding_agents", return_value=detected),
                patch.object(install, "command_version", return_value="codex fixture"),
                patch.object(
                    install,
                    "codex_sandbox_install_status",
                    return_value=sandbox,
                ),
                patch.object(
                    install,
                    "set_token_mode",
                    return_value={"mode": "off"},
                ),
                patch.object(install.venv.EnvBuilder, "create", side_effect=create_venv),
                patch.object(install, "run", return_value=command_result),
                patch.object(install, "tree_hash", return_value="a" * 64),
                patch.object(install, "uninstall_plan", return_value={"paths": []}),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(install.main(), 0)

            lock = json.loads((prefix / "install-lock.json").read_text(encoding="utf-8"))
            self.assertEqual(lock["detected_coding_agents"], detected)
            self.assertEqual(
                lock["external_tools"][0],
                {
                    "name": "codex",
                    "display_name": "Codex",
                    "path": "/tools/codex",
                    "version": "codex fixture",
                    "detected": True,
                    **sandbox,
                },
            )
            self.assertFalse(lock["external_tools"][0].get("skipped", False))

    def test_codex_install_status_requires_native_sandbox_preflight(self):
        install = load_install_script()
        failed = {
            "ok": False,
            "platform": "Windows",
            "guidance": "Use the native Windows sandbox from PowerShell.",
            "next_commands": ["codex sandbox windows -- python -c pass"],
            "reference": "https://learn.chatgpt.com/docs/sandboxing",
        }
        with patch.object(install, "codex_sandbox_preflight", return_value=failed):
            status = install.codex_sandbox_install_status("codex")

        self.assertFalse(status["configured"])
        self.assertEqual(status["sandbox_preflight"], failed)
        self.assertEqual(status["next_commands"], failed["next_commands"])

    @unittest.skipIf(os.name == "nt", "POSIX installer behavior")
    def test_unix_launcher_fails_with_guidance_when_requirements_are_missing_noninteractively(self):
        install = load_install_script()
        with tempfile.TemporaryDirectory() as temp:
            bin_dir = Path(temp) / "bin"
            bin_dir.mkdir()
            dirname = install.shutil.which("dirname")
            self.assertIsNotNone(dirname)
            (bin_dir / "dirname").symlink_to(dirname)

            result = subprocess.run(
                ["/bin/sh", str(ROOT / "install.sh")],
                env={"PATH": str(bin_dir)},
                stdin=subprocess.DEVNULL,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("Python 3.11+ and Git", result.stdout)
        self.assertIn("interactive terminal", result.stderr)

    @unittest.skipIf(os.name == "nt", "POSIX installer behavior")
    def test_unix_launcher_executes_exact_core_requirement_package_manager_commands(self):
        import pty

        cases = {
            "brew": ["install python@3.12 git"],
            "apt-get": ["update", "install -y python3 git"],
            "dnf": ["install -y python3 git"],
            "yum": ["install -y python3 git"],
            "pacman": ["-Sy --needed --noconfirm python git"],
            "zypper": ["--non-interactive install python311 git"],
        }

        for package_manager, expected_commands in cases.items():
            with self.subTest(package_manager=package_manager):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    bin_dir = root / "bin"
                    bin_dir.mkdir()
                    marker = root / "requirements-installed"
                    package_log = root / "package.log"
                    python_log = root / "python.log"
                    prefix = root / "prefix"

                    dirname = shutil.which("dirname")
                    self.assertIsNotNone(dirname)
                    (bin_dir / "dirname").symlink_to(dirname)

                    def write_executable(name, text):
                        path = bin_dir / name
                        path.write_text(text, encoding="utf-8")
                        path.chmod(0o755)

                    write_executable("uname", "#!/bin/sh\nprintf '%s\\n' Linux\n")
                    write_executable("id", "#!/bin/sh\nprintf '%s\\n' 0\n")
                    write_executable(
                        "python3",
                        "#!/bin/sh\n"
                        "if [ \"${1-}\" = '-c' ]; then\n"
                        "  [ -f \"$INSTALL_MARKER\" ]\n"
                        "  exit\n"
                        "fi\n"
                        "printf '%s\\n' \"$*\" >> \"$PYTHON_LOG\"\n",
                    )
                    write_executable(
                        "git",
                        "#!/bin/sh\n[ -f \"$INSTALL_MARKER\" ]\n",
                    )
                    write_executable(
                        package_manager,
                        "#!/bin/sh\n"
                        "printf '%s\\n' \"$*\" >> \"$PACKAGE_LOG\"\n"
                        "[ \"${PACKAGE_FAIL-}\" != '1' ] || exit 17\n"
                        ": > \"$INSTALL_MARKER\"\n",
                    )

                    def run_launcher(**extra_env):
                        master_fd, slave_fd = pty.openpty()
                        try:
                            os.write(master_fd, b"\n")
                            return subprocess.run(
                                [
                                    "/bin/sh",
                                    str(ROOT / "install.sh"),
                                    "--prefix",
                                    str(prefix),
                                    "--skip-tests",
                                ],
                                env={
                                    **extra_env,
                                    "HOME": str(root / "home"),
                                    "PATH": str(bin_dir),
                                    "INSTALL_MARKER": str(marker),
                                    "PACKAGE_LOG": str(package_log),
                                    "PYTHON_LOG": str(python_log),
                                },
                                stdin=slave_fd,
                                text=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                check=False,
                            )
                        finally:
                            os.close(slave_fd)
                            os.close(master_fd)

                    result = run_launcher()
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        package_log.read_text(encoding="utf-8").splitlines(),
                        expected_commands,
                    )
                    self.assertEqual(
                        python_log.read_text(encoding="utf-8").splitlines(),
                        [
                            f"{ROOT / 'scripts' / 'install.py'} --prefix {prefix} --skip-tests",
                            f"{ROOT / 'scripts' / 'finalize_gitnexus.py'} --prefix {prefix}",
                        ],
                    )

                    marker.unlink()
                    package_log.unlink()
                    python_log.unlink()
                    failed = run_launcher(PACKAGE_FAIL="1")
                    self.assertEqual(failed.returncode, 2)
                    self.assertEqual(
                        package_log.read_text(encoding="utf-8").splitlines(),
                        expected_commands,
                    )
                    self.assertFalse(python_log.exists())

    @unittest.skipIf(os.name == "nt", "POSIX installer behavior")
    def test_unix_launcher_executes_macos_python_and_git_installers(self):
        import pty

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            python_marker = root / "python-installed"
            git_marker = root / "git-installed"
            command_log = root / "commands.log"
            python_log = root / "python.log"
            package_dir = root / "download"
            prefix = root / "prefix"

            for name in ("awk", "dirname", "rm", "rmdir"):
                executable = shutil.which(name)
                self.assertIsNotNone(executable)
                (bin_dir / name).symlink_to(executable)

            def write_executable(name, text):
                path = bin_dir / name
                path.write_text(text, encoding="utf-8")
                path.chmod(0o755)

            write_executable("uname", "#!/bin/sh\nprintf '%s\\n' Darwin\n")
            write_executable("id", "#!/bin/sh\nprintf '%s\\n' 0\n")
            write_executable(
                "mktemp",
                "#!/bin/sh\n/bin/mkdir -p \"$MACOS_PACKAGE_DIR\"\nprintf '%s\\n' \"$MACOS_PACKAGE_DIR\"\n",
            )
            write_executable(
                "curl",
                "#!/bin/sh\nprintf 'curl %s\\n' \"$*\" >> \"$COMMAND_LOG\"\n: > \"$5\"\n",
            )
            write_executable(
                "shasum",
                "#!/bin/sh\n"
                "printf 'shasum %s\\n' \"$*\" >> \"$COMMAND_LOG\"\n"
                "printf '%s  %s\\n' '8373e58da4ea146b3eb1c1f9834f19a319440b6b679b06050b1f9ee3237aa8e4' \"$3\"\n",
            )
            write_executable(
                "installer",
                "#!/bin/sh\nprintf 'installer %s\\n' \"$*\" >> \"$COMMAND_LOG\"\n: > \"$PYTHON_MARKER\"\n",
            )
            write_executable(
                "brew",
                "#!/bin/sh\nprintf 'brew %s\\n' \"$*\" >> \"$COMMAND_LOG\"\n: > \"$GIT_MARKER\"\n",
            )
            write_executable(
                "python3",
                "#!/bin/sh\n"
                "if [ \"${1-}\" = '-c' ]; then\n"
                "  [ -f \"$PYTHON_MARKER\" ]\n"
                "  exit\n"
                "fi\n"
                "printf '%s\\n' \"$*\" >> \"$PYTHON_LOG\"\n",
            )
            write_executable("git", "#!/bin/sh\n[ -f \"$GIT_MARKER\" ]\n")

            master_fd, slave_fd = pty.openpty()
            try:
                os.write(master_fd, b"\n")
                result = subprocess.run(
                    [
                        "/bin/sh",
                        str(ROOT / "install.sh"),
                        "--prefix",
                        str(prefix),
                        "--skip-tests",
                    ],
                    env={
                        "HOME": str(root / "home"),
                        "PATH": str(bin_dir),
                        "COMMAND_LOG": str(command_log),
                        "PYTHON_LOG": str(python_log),
                        "PYTHON_MARKER": str(python_marker),
                        "GIT_MARKER": str(git_marker),
                        "MACOS_PACKAGE_DIR": str(package_dir),
                    },
                    stdin=slave_fd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
            finally:
                os.close(slave_fd)
                os.close(master_fd)

            package = package_dir / "python.pkg"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                command_log.read_text(encoding="utf-8").splitlines(),
                [
                    "curl -fL --retry 2 -o "
                    f"{package} https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg",
                    f"shasum -a 256 {package}",
                    f"installer -pkg {package} -target /",
                    "brew install git",
                ],
            )
            self.assertEqual(
                python_log.read_text(encoding="utf-8").splitlines(),
                [
                    f"{ROOT / 'scripts' / 'install.py'} --prefix {prefix} --skip-tests",
                    f"{ROOT / 'scripts' / 'finalize_gitnexus.py'} --prefix {prefix}",
                ],
            )

    @unittest.skipIf(os.name == "nt", "POSIX installer behavior")
    def test_unix_launcher_uses_macos_command_line_tools_when_homebrew_is_missing(self):
        import pty

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            command_log = root / "commands.log"

            dirname = shutil.which("dirname")
            self.assertIsNotNone(dirname)
            (bin_dir / "dirname").symlink_to(dirname)

            def write_executable(name, text):
                path = bin_dir / name
                path.write_text(text, encoding="utf-8")
                path.chmod(0o755)

            write_executable("uname", "#!/bin/sh\nprintf '%s\\n' Darwin\n")
            write_executable(
                "python3",
                "#!/bin/sh\n[ \"${1-}\" = '-c' ] && exit 0\nexit 91\n",
            )
            write_executable("git", "#!/bin/sh\nexit 1\n")
            write_executable(
                "xcode-select",
                "#!/bin/sh\nprintf 'xcode-select %s\\n' \"$*\" >> \"$COMMAND_LOG\"\n",
            )

            master_fd, slave_fd = pty.openpty()
            try:
                os.write(master_fd, b"\n")
                result = subprocess.run(
                    ["/bin/sh", str(ROOT / "install.sh")],
                    env={
                        "HOME": str(root / "home"),
                        "PATH": str(bin_dir),
                        "COMMAND_LOG": str(command_log),
                    },
                    stdin=slave_fd,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
            finally:
                os.close(slave_fd)
                os.close(master_fd)

            self.assertEqual(result.returncode, 2)
            self.assertEqual(command_log.read_text(encoding="utf-8"), "xcode-select --install\n")
            self.assertIn("Finish the Apple installer, then rerun Manageroo.", result.stdout)

    def test_codex_setup_selects_exact_node_package_manager_commands(self):
        install = load_install_script()
        cases = {
            "brew": [["/tools/brew", "install", "node"]],
            "apt-get": [
                ["/tools/apt-get", "update"],
                ["/tools/apt-get", "install", "-y", "nodejs", "npm"],
            ],
            "dnf": [["/tools/dnf", "install", "-y", "nodejs", "npm"]],
            "yum": [["/tools/yum", "install", "-y", "nodejs", "npm"]],
            "pacman": [
                [
                    "/tools/pacman",
                    "-Sy",
                    "--needed",
                    "--noconfirm",
                    "nodejs",
                    "npm",
                ]
            ],
            "zypper": [
                [
                    "/tools/zypper",
                    "--non-interactive",
                    "install",
                    "nodejs",
                    "npm",
                ]
            ],
        }

        for package_manager, expected_commands in cases.items():
            with self.subTest(package_manager=package_manager):
                npm_probes = 0

                def which(name):
                    nonlocal npm_probes
                    if name == "npm":
                        npm_probes += 1
                        return None if npm_probes == 1 else "/tools/npm"
                    if name == package_manager:
                        return f"/tools/{name}"
                    return None

                with (
                    patch.object(install.os, "name", "posix"),
                    patch.object(install.os, "geteuid", return_value=0, create=True),
                    patch.object(install.platform, "system", return_value="Linux"),
                    patch.object(install.shutil, "which", side_effect=which),
                    patch.object(install, "prepend_tool_paths"),
                    patch.object(install, "run") as run_command,
                ):
                    self.assertEqual(install._ensure_node_npm(), "/tools/npm")

                self.assertEqual(
                    [call.args[0] for call in run_command.call_args_list],
                    expected_commands,
                )

        npm_probes = 0

        def windows_which(name):
            nonlocal npm_probes
            if name == "npm":
                npm_probes += 1
                return None if npm_probes == 1 else "/tools/npm.cmd"
            return "/tools/winget.exe" if name == "winget" else None

        class WindowsPathFixture:
            def __truediv__(self, _part):
                return self

            def exists(self):
                return False

        with (
            patch.object(install.os, "name", "nt"),
            patch.object(install, "Path", return_value=WindowsPathFixture()),
            patch.object(install.shutil, "which", side_effect=windows_which),
            patch.object(install, "prepend_tool_paths"),
            patch.object(install, "run") as run_command,
        ):
            self.assertEqual(install._ensure_node_npm(), "/tools/npm.cmd")

        self.assertEqual(
            [call.args[0] for call in run_command.call_args_list],
            [
                [
                    "/tools/winget.exe",
                    "install",
                    "--id",
                    "OpenJS.NodeJS.LTS",
                    "-e",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ]
            ],
        )

    def test_codex_setup_propagates_node_package_manager_failure(self):
        install = load_install_script()

        def which(name):
            return "/tools/dnf" if name == "dnf" else None

        with (
            patch.object(install.os, "name", "posix"),
            patch.object(install.os, "geteuid", return_value=0, create=True),
            patch.object(install.platform, "system", return_value="Linux"),
            patch.object(install.shutil, "which", side_effect=which),
            patch.object(install, "run", side_effect=RuntimeError("dnf failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "dnf failed"):
                install._ensure_node_npm()

    def test_codex_setup_installs_pinned_macos_node_package_without_homebrew(self):
        install = load_install_script()
        package_bytes = b"release-pinned node package fixture"
        npm_probes = 0

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return package_bytes

        def which(name):
            nonlocal npm_probes
            if name == "npm":
                npm_probes += 1
                return None if npm_probes == 1 else "/tools/npm"
            return None

        expected_sha256 = install.hashlib.sha256(package_bytes).hexdigest()
        with (
            patch.object(install.os, "name", "posix"),
            patch.object(install.os, "geteuid", return_value=0, create=True),
            patch.object(install.platform, "system", return_value="Darwin"),
            patch.object(install.shutil, "which", side_effect=which),
            patch.object(install, "NODE_MACOS_PACKAGE_SHA256", expected_sha256),
            patch.object(install.urllib.request, "urlopen", return_value=Response()) as download,
            patch.object(install, "prepend_tool_paths"),
            patch.object(install, "run") as run_command,
        ):
            self.assertEqual(install._ensure_node_npm(), "/tools/npm")

        download.assert_called_once_with(install.NODE_MACOS_PACKAGE_URL, timeout=120)
        command = run_command.call_args.args[0]
        self.assertEqual(command[0], "/usr/sbin/installer")
        self.assertEqual(command[1], "-pkg")
        self.assertEqual(Path(command[2]).name, "node.pkg")
        self.assertEqual(command[3:], ["-target", "/"])
        self.assertEqual(run_command.call_args.kwargs, {"cwd": Path.home(), "capture": False})

    def test_existing_gitnexus_does_not_bootstrap_node_or_npm(self):
        install = load_install_script()
        with (
            patch.object(install, "command_version", return_value="gitnexus 1.6.9"),
            patch.object(install, "_ensure_node_npm") as ensure_node_npm,
            patch.object(install, "optional_run") as install_command,
            patch.object(install.shutil, "which", return_value="/tools/gitnexus"),
        ):
            result = install.install_gitnexus([])

        ensure_node_npm.assert_not_called()
        install_command.assert_not_called()
        self.assertTrue(result["installed"])
        self.assertEqual(result["path"], "/tools/gitnexus")

    def test_quick_start_explains_cross_platform_requirements_and_agent_detection(self):
        for relative in ("README.md", "GITHUB_DESCRIPTION.md"):
            with self.subTest(relative=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("Download ZIP", text)
                self.assertIn("macOS", text)
                self.assertIn("Linux", text)
                self.assertIn("Windows", text)
                self.assertIn("Codex, Claude Code, and Gemini CLI", text)
                self.assertIn("If it finds several", text)
                self.assertIn("If it finds none", text)

    def test_skill_pack_is_recommended_default_but_can_be_skipped(self):
        install = load_install_script()
        self.assertEqual(install.choose_skill_pack_mode("install", False), "install")
        self.assertEqual(install.choose_skill_pack_mode("skip", False), "skip")
        self.assertEqual(install.choose_skill_pack_mode("ask", True), "skip")

    def test_skill_pack_prompt_defaults_to_install(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value=""):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(install.choose_skill_pack_mode("ask", False), "install")

    def test_skill_pack_prompt_can_skip_and_records_later_reconcile_command(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value="n"):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(install.choose_skill_pack_mode("ask", False), "skip")
        source = INSTALL_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Portable core skill pack skipped", source)
        self.assertIn("manageroo skills reconcile --apply", source)

    def test_skill_pack_non_interactive_uses_recommended_install(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=False):
            self.assertEqual(install.choose_skill_pack_mode("ask", False), "install")

    def test_lane_explainer_is_plain_english(self):
        install = load_install_script()
        output = io.StringIO()
        with redirect_stdout(output):
            install.print_lane_explainer()
        text = output.getvalue()
        self.assertIn("How Manageroo fits together", text)
        self.assertIn("Manageroo owns run truth", text)
        self.assertIn("GitNexus", text)
        self.assertIn("GBrain", text)
        self.assertIn("AUTOREVIEW and Clawpatch", text)
        self.assertIn("Host skills", text)

    def test_next_commands_offer_guided_project_setup(self):
        install = load_install_script()
        output = io.StringIO()
        with redirect_stdout(output):
            install.print_next_commands()
        text = output.getvalue()
        self.assertIn("manageroo projects --add", text)
        self.assertIn("manageroo stack-doctor", text)
        self.assertIn("manageroo repair-install --no-apply", text)
        self.assertIn("manageroo next", text)
        self.assertNotIn("cd /path/to/project && manageroo solo", text)

    def test_project_discovery_prompt_defaults_to_add_selected_projects(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value=""):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(install.choose_project_discovery_mode("ask"), "add")

    def test_stack_doctor_prompt_defaults_to_run_when_interactive(self):
        install = load_install_script()
        with patch.object(install.sys.stdin, "isatty", return_value=True):
            with patch("builtins.input", return_value=""):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(install.choose_stack_doctor_mode("ask"), "run")

    def test_powershell_installer_forwards_each_important_value_to_the_exact_python_flag(self):
        ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
        mapping = _powershell_forwarding_map(ps1)
        expected = {
            "Prefix": "--prefix",
            "BinDir": "--bin-dir",
            "TokenMode": "--token-mode",
            "SkillPack": "--skill-pack",
            "Stack": "--stack",
            "GBrainLane": "--gbrain-lane",
            "ProjectDiscovery": "--project-discovery",
            "StackDoctor": "--stack-doctor",
            "ClawpatchCodexLogin": "--clawpatch-codex-login",
            "ObsidianMethod": "--obsidian-method",
            "Agent": "--agent",
        }
        for parameter, flag in expected.items():
            with self.subTest(parameter=parameter):
                self.assertEqual(mapping.get(parameter), flag)
        self.assertEqual({key: mapping[key] for key in expected}, expected)

    def test_installer_has_no_external_loop_library_surface(self):
        py = INSTALL_SCRIPT.read_text(encoding="utf-8")
        ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")
        for text in (py, ps1):
            self.assertNotIn("--loop-library-agent", text)
            self.assertNotIn("Forward-Future/loop-library", text)
            self.assertNotIn("signals.forwardfuture", text)
        self.assertNotIn("install_loop_library", py)

    def test_public_installer_and_docs_do_not_hardcode_private_skill_import_paths(self):
        public_files = [
            ROOT / "install.sh",
            ROOT / "install.ps1",
            ROOT / "scripts" / "install.py",
            ROOT / "README.md",
            ROOT / "LOCAL_SETUP.md",
            ROOT / "docs" / "00_START_HERE.md",
            ROOT / "docs" / "INSTALLATION.md",
        ]
        private_fragments = (
            "/home/Tommy/",
            "/Users/tommythehamburger/",
            "C:\\Users\\David\\",
            "Tommy's tOS",
        )
        for path in public_files:
            with self.subTest(path=str(path.relative_to(ROOT))):
                text = path.read_text(encoding="utf-8")
                for fragment in private_fragments:
                    self.assertNotIn(fragment, text)

    def test_official_gbrain_lane_uses_upstream_agent_protocol(self):
        install = load_install_script()
        output = io.StringIO()
        with patch.object(install, "command_version", return_value="not installed"):
            with redirect_stdout(output):
                result = install.install_gbrain([], lane="official")
        text = output.getvalue() + "\n".join(result["next_commands"])
        self.assertIn("INSTALL_FOR_AGENTS.md", text)
        self.assertIn("agent-supervised", str(result.get("guidance", "")))
        self.assertNotIn("Paste this into your AI agent", text)

    def test_executable_third_party_installer_sources_are_immutable(self):
        install = load_install_script()
        pinned = [
            install.CODEX_NPM_PACKAGE,
            install.GBRAIN_INSTALL_SOURCE,
            install.GITNEXUS_NPM_PACKAGE,
            install.PNPM_PACKAGE,
            install.CLAWPATCH_PACKAGE,
            f"{install.OPENCLAW_AGENT_SKILLS_REPO}#{install.OPENCLAW_AGENT_SKILLS_COMMIT}",
            f"{install.TRUFFLEHOG_REFERENCE}/releases/download/v{install.TRUFFLEHOG_VERSION}",
        ]
        for source in pinned:
            with self.subTest(source=source):
                self.assertTrue(install._source_is_immutable(source))
                self.assertNotIn("@latest", source.lower())
        self.assertEqual(len(install.GBRAIN_COMMIT), 40)
        self.assertEqual(len(install.OPENCLAW_AGENT_SKILLS_COMMIT), 40)

    def test_trufflehog_install_records_verified_manageroo_ownership(self):
        install = load_install_script()
        with tempfile.TemporaryDirectory() as temp:
            bin_dir = Path(temp) / "bin"
            downloads = []
            report = {
                "version": install.TRUFFLEHOG_VERSION,
                "path": str(bin_dir / "trufflehog"),
                "asset": "trufflehog-test.tar.gz",
                "url": f"{install.TRUFFLEHOG_REFERENCE}/releases/download/v{install.TRUFFLEHOG_VERSION}/trufflehog-test.tar.gz",
                "sha256": "a" * 64,
            }
            with patch.object(install.shutil, "which", return_value=None), patch.object(
                install, "install_trufflehog_binary", return_value=report
            ):
                result = install.install_trufflehog(downloads, bin_dir)
        self.assertTrue(result["configured"])
        self.assertTrue(result["manageroo_owned"])
        self.assertTrue(downloads[0]["immutable"])
        self.assertEqual(downloads[0]["sha256"], "a" * 64)

    def test_pinned_git_checkout_verifies_exact_commit(self):
        install = load_install_script()
        calls = []

        class Result:
            def __init__(self, stdout=""):
                self.stdout = stdout

        def fake_run(argv, *, cwd, timeout=300):
            calls.append((argv, cwd, timeout))
            if argv[1:3] == ["rev-parse", "HEAD"]:
                return Result(install.OPENCLAW_AGENT_SKILLS_COMMIT + "\n")
            return Result()

        with patch.object(install, "_run_checked", side_effect=fake_run):
            report = install._checkout_pinned_git_source(
                git="git",
                repository=install.OPENCLAW_AGENT_SKILLS_REPO,
                commit=install.OPENCLAW_AGENT_SKILLS_COMMIT,
                destination=Path("/tmp/pinned-agent-skills"),
            )
        self.assertEqual(report["resolved_commit"], install.OPENCLAW_AGENT_SKILLS_COMMIT)
        commands = [call[0] for call in calls]
        self.assertIn(
            ["git", "checkout", "--detach", install.OPENCLAW_AGENT_SKILLS_COMMIT],
            commands,
        )
        self.assertIn(["git", "rev-parse", "HEAD"], commands)

    def test_pinned_git_checkout_rejects_mismatched_commit(self):
        install = load_install_script()
        mismatched_commit = "f" * 40

        class Result:
            def __init__(self, stdout=""):
                self.stdout = stdout

        def fake_run(argv, *, cwd, timeout=300):
            if argv[1:3] == ["rev-parse", "HEAD"]:
                return Result(mismatched_commit + "\n")
            return Result()

        with patch.object(install, "_run_checked", side_effect=fake_run):
            with self.assertRaisesRegex(
                RuntimeError,
                f"expected {install.OPENCLAW_AGENT_SKILLS_COMMIT}, received {mismatched_commit}",
            ):
                install._checkout_pinned_git_source(
                    git="git",
                    repository=install.OPENCLAW_AGENT_SKILLS_REPO,
                    commit=install.OPENCLAW_AGENT_SKILLS_COMMIT,
                    destination=Path("/tmp/pinned-agent-skills"),
                )


if __name__ == "__main__":
    unittest.main()

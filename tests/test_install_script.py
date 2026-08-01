import importlib.util
import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
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
        source = INSTALL_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('"detected": True', source)
        self.assertIn('"name": "coding-agent"', source)
        self.assertIn("No supported coding-agent CLI was detected or installed", source)
        self.assertNotIn("Codex is an adapter choice, not a core requirement", source)

    def test_unix_launcher_offers_guided_core_requirement_install(self):
        launcher = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("install_core_requirements", launcher)
        self.assertIn("Install the missing requirements now? [Y/n]", launcher)
        for package_manager in ("brew", "apt-get", "dnf", "yum", "pacman", "zypper"):
            with self.subTest(package_manager=package_manager):
                self.assertIn(package_manager, launcher)
        self.assertIn('"$(uname -s)" = "Darwin"', launcher)
        self.assertIn("MACOS_PYTHON_URL", launcher)
        self.assertIn("MACOS_PYTHON_SHA256", launcher)
        self.assertIn("xcode-select --install", launcher)

    def test_codex_setup_can_install_node_with_common_platform_package_managers(self):
        source = INSTALL_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Node.js/npm is missing", source)
        self.assertIn("NODE_MACOS_PACKAGE_URL", source)
        self.assertIn("NODE_MACOS_PACKAGE_SHA256", source)
        for package_manager in ("winget", "brew", "apt-get", "dnf", "yum", "pacman", "zypper"):
            with self.subTest(package_manager=package_manager):
                self.assertIn(f'shutil.which("{package_manager}")', source)

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


if __name__ == "__main__":
    unittest.main()

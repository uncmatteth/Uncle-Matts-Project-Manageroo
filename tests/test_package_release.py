import errno
import hashlib
import importlib.util
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
import zipfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from manageroo.token_modes import BUNDLED_SKILL_LIBRARY

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_release", ROOT / "scripts" / "package_release.py")
assert SPEC and SPEC.loader
package_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_release)
VERIFY_SPEC = importlib.util.spec_from_file_location(
    "verify_distribution",
    ROOT / "scripts" / "verify_distribution.py",
)
assert VERIFY_SPEC and VERIFY_SPEC.loader
verify_distribution = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(verify_distribution)
RELEASE_VERIFY_SPEC = importlib.util.spec_from_file_location(
    "verify_release",
    ROOT / "scripts" / "verify_release.py",
)
assert RELEASE_VERIFY_SPEC and RELEASE_VERIFY_SPEC.loader
verify_release = importlib.util.module_from_spec(RELEASE_VERIFY_SPEC)
RELEASE_VERIFY_SPEC.loader.exec_module(verify_release)
FINALIZE_SPEC = importlib.util.spec_from_file_location(
    "finalize_gitnexus",
    ROOT / "scripts" / "finalize_gitnexus.py",
)
assert FINALIZE_SPEC and FINALIZE_SPEC.loader
finalize_gitnexus = importlib.util.module_from_spec(FINALIZE_SPEC)
FINALIZE_SPEC.loader.exec_module(finalize_gitnexus)
SMOKE_SPEC = importlib.util.spec_from_file_location(
    "smoke_release_install",
    ROOT / "scripts" / "smoke_release_install.py",
)
assert SMOKE_SPEC and SMOKE_SPEC.loader
smoke_release_install = importlib.util.module_from_spec(SMOKE_SPEC)
SMOKE_SPEC.loader.exec_module(smoke_release_install)


def _fixture(codes: list[int]) -> str:
    return "".join(chr(code) for code in codes)


def _publish_release_fixture(
    root_value, checkout_name, marker, lock_contended, installer_published, release_first
) -> None:
    import manageroo.config_lock as config_lock_module

    root = Path(root_value)
    checkout = root / checkout_name
    checkout.mkdir()
    output = root / "release.zip"
    source_output = root / "release-source.zip"
    candidate_output = checkout / f"candidate-{marker}.zip"
    candidate_source = checkout / f"candidate-{marker}-source.zip"
    candidate_output.write_bytes(f"{marker}-installer".encode())
    candidate_source.write_bytes(f"{marker}-source".encode())
    original_replace = package_release.os.replace
    original_try_lock = config_lock_module._try_lock_file

    def signal_lock_attempt(descriptor):
        try:
            return original_try_lock(descriptor)
        except OSError as exc:
            if lock_contended is not None and exc.errno in {errno.EACCES, errno.EAGAIN}:
                lock_contended.set()
            raise

    def pause_after_installer_publish(source, destination):
        original_replace(source, destination)
        if Path(destination) == output:
            installer_published.set()
            if marker == "a" and not release_first.wait(timeout=5):
                raise TimeoutError("test did not release the first publisher")

    def drop_copies(end_user_archive, source_archive):
        return {
            package_release.INSTALLER_ZIP: end_user_archive,
            package_release.SOURCE_ZIP: source_archive,
        }

    with (
        patch.object(config_lock_module, "_try_lock_file", side_effect=signal_lock_attempt),
        patch.object(package_release, "ROOT", checkout),
        patch.object(package_release, "OUTPUT", output),
        patch.object(package_release, "SOURCE_OUTPUT", source_output),
        patch.object(package_release, "_drop_copies", side_effect=drop_copies),
        patch.object(package_release.os, "replace", side_effect=pause_after_installer_publish),
    ):
        package_release._publish_release(candidate_output, candidate_source, root / "drop")


def _finalize_gitnexus_fixture(
    prefix_value, marker, lock_contended, setup_started, release_setup, results
) -> None:
    import manageroo.config_lock as config_lock_module

    prefix = Path(prefix_value)
    original_try_lock = config_lock_module._try_lock_file

    def signal_lock_attempt(descriptor):
        try:
            return original_try_lock(descriptor)
        except OSError as exc:
            if lock_contended is not None and exc.errno in {errno.EACCES, errno.EAGAIN}:
                lock_contended.set()
            raise

    def setup(argv, **_kwargs):
        setup_started.set()
        if marker == "first" and not release_setup.wait(timeout=10):
            raise TimeoutError("test did not release GitNexus setup")
        return subprocess.CompletedProcess(argv, 0, stdout=f"{marker} setup complete\n")

    with (
        patch.object(config_lock_module, "_try_lock_file", side_effect=signal_lock_attempt),
        patch.object(finalize_gitnexus.shutil, "which", return_value="/fake/gitnexus"),
        patch.object(finalize_gitnexus.subprocess, "run", side_effect=setup),
    ):
        try:
            results.put({"marker": marker, "result": finalize_gitnexus.finalize(prefix)})
        except Exception as exc:
            results.put({"marker": marker, "error": f"{type(exc).__name__}: {exc}"})


class PackageReleaseTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Unix command shape fixture")
    def test_clean_install_product_run_requests_json_output(self):
        command = smoke_release_install.product_run_command(
            Path("/tmp/manageroo"),
            Path("/tmp/product"),
        )

        self.assertEqual(command[-1], "--json")
        self.assertEqual(command.count("--json"), 1)

    @unittest.skipIf(os.name == "nt", "Unix launcher provenance fixture")
    def test_smoke_requires_temporary_launcher_and_sanitizes_pythonpath(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp)
            archive = fixture / "release.zip"
            env_capture = fixture / "pythonpath.txt"
            fake_marker = fixture / "fake-manageroo-ran.txt"
            fake_bin = fixture / "fake-bin"
            fake_bin.mkdir()
            fake_manageroo = fake_bin / "manageroo"
            fake_manageroo.write_text(
                "#!/bin/sh\n"
                'printf invoked > "$SMOKE_FAKE_MARKER"\n'
                f"printf '%s\\n' {smoke_release_install.EXPECTED_VERSION!r}\n",
                encoding="utf-8",
            )
            fake_manageroo.chmod(0o755)
            with zipfile.ZipFile(archive, "w") as release:
                release.writestr(
                    f"{smoke_release_install.ARCHIVE_ROOT}/install.sh",
                    "#!/bin/sh\n"
                    'printf "%s" "${PYTHONPATH-unset}" > "$SMOKE_ENV_CAPTURE"\n',
                )

            smoke_env = {
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "PYTHONPATH": str(ROOT / "src"),
                "SMOKE_ENV_CAPTURE": str(env_capture),
                "SMOKE_FAKE_MARKER": str(fake_marker),
            }
            with patch.dict(smoke_release_install.os.environ, smoke_env, clear=False):
                with self.assertRaisesRegex(RuntimeError, "launcher.*missing"):
                    smoke_release_install.smoke(
                        archive,
                        skip_install_tests=True,
                    )

            self.assertEqual(env_capture.read_text(encoding="utf-8"), "unset")
            self.assertFalse(fake_marker.exists())

    def test_matt_pocock_skill_subset_is_pinned_licensed_and_codex_ready(self):
        imported = {
            "codebase-design",
            "diagnosing-bugs",
            "domain-modeling",
            "grill-me",
            "grill-with-docs",
            "grilling",
            "handoff",
            "improve-codebase-architecture",
            "setup-matt-pocock-skills",
            "tdd",
            "to-spec",
            "to-tickets",
            "writing-for-agents",
        }
        commit = "8b36d4fb2635b3c21998dcd8144439c9e5ba7302"
        license_sha256 = "0e7ac423bf2c6e223b7c5b156f8cf72da49d748e56a1641402c31f22ad07dbb5"

        self.assertTrue(imported <= set(BUNDLED_SKILL_LIBRARY))
        for name in sorted(imported):
            with self.subTest(skill=name):
                skill_root = ROOT / "src" / "manageroo" / "assets" / "skills" / name
                source = (skill_root / "SOURCE.md").read_text(encoding="utf-8")
                self.assertIn("https://github.com/mattpocock/skills", source)
                self.assertIn("Version: 1.2.2", source)
                self.assertIn(commit, source)
                self.assertTrue((skill_root / "agents" / "openai.yaml").is_file())
                self.assertEqual(
                    hashlib.sha256((skill_root / "LICENSE.txt").read_bytes()).hexdigest(),
                    license_sha256,
                )

        for retired in ("diagnose", "to-issues", "to-prd", "write-a-skill"):
            self.assertNotIn(retired, BUNDLED_SKILL_LIBRARY)
            self.assertFalse(
                (ROOT / "src" / "manageroo" / "assets" / "skills" / retired).exists()
            )

    def test_release_verifier_timeout_stops_descendant_process_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "descendant-writes.txt"
            descendant = (
                "import time; from pathlib import Path; "
                f"marker = Path({str(marker)!r}); "
                "[(marker.write_text(marker.read_text(encoding='utf-8') + 'x' "
                "if marker.exists() else 'x', encoding='utf-8'), time.sleep(0.05)) "
                "for _ in range(80)]"
            )
            parent = (
                "import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {descendant!r}]); "
                "time.sleep(10)"
            )
            started = time.monotonic()
            with patch.object(verify_release, "PROCESS_TREE_GRACE_SECONDS", 0.1):
                result = verify_release.run([sys.executable, "-c", parent], timeout=0.8)
            elapsed = time.monotonic() - started

            self.assertEqual(result["exit_code"], 124)
            self.assertIn("TIMEOUT", result["output"])
            self.assertLess(elapsed, 2)
            self.assertTrue(marker.is_file())
            marker_size = marker.stat().st_size
            time.sleep(0.3)
            self.assertEqual(marker.stat().st_size, marker_size)

    def test_concurrent_gitnexus_finalizers_serialize_lock_update(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            prefix.mkdir()
            lock_path = prefix / "install-lock.json"
            lock_path.write_text(
                json.dumps(
                    {
                        "operator_note": "preserve this unrelated field",
                        "external_tools": [
                            {
                                "name": "gitnexus",
                                "installed": True,
                                "configured": False,
                                "path": "/fake/gitnexus",
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            context = multiprocessing.get_context("spawn")
            second_lock_contended = context.Event()
            first_setup_started = context.Event()
            second_setup_started = context.Event()
            release_setup = context.Event()
            results = context.Queue()
            first = context.Process(
                target=_finalize_gitnexus_fixture,
                args=(
                    prefix,
                    "first",
                    None,
                    first_setup_started,
                    release_setup,
                    results,
                ),
            )
            second = context.Process(
                target=_finalize_gitnexus_fixture,
                args=(
                    prefix,
                    "second",
                    second_lock_contended,
                    second_setup_started,
                    release_setup,
                    results,
                ),
            )

            try:
                first.start()
                self.assertTrue(first_setup_started.wait(timeout=5))
                second.start()
                self.assertTrue(second_lock_contended.wait(timeout=5))
                self.assertFalse(second_setup_started.is_set())
                release_setup.set()
                first.join(timeout=5)
                second.join(timeout=5)
                self.assertEqual(first.exitcode, 0)
                self.assertEqual(second.exitcode, 0)
                outcomes = {
                    item["marker"]: item
                    for item in (results.get(timeout=5), results.get(timeout=5))
                }
            finally:
                release_setup.set()
                for process in (first, second):
                    if process.pid is not None:
                        process.join(timeout=1)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)

            self.assertNotIn("error", outcomes["first"])
            self.assertNotIn("error", outcomes["second"])
            self.assertTrue(outcomes["first"]["result"]["ok"])
            self.assertTrue(outcomes["second"]["result"]["ok"])
            self.assertTrue(outcomes["second"]["result"]["skipped"])
            self.assertFalse(second_setup_started.is_set())
            final_lock = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(final_lock["operator_note"], "preserve this unrelated field")
            self.assertTrue(final_lock["external_tools"][0]["configured"])

    def test_release_names_derive_from_project_version(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        version = str(project["version"])
        self.assertEqual(package_release.PROJECT_VERSION, version)
        self.assertEqual(package_release.VERSION_TAG, f"v{version}")
        self.assertEqual(package_release.ARCHIVE_ROOT, "Uncle-Matts-Project-Manageroo")
        self.assertEqual(package_release.DROP_ROOT, f"uncle-matts-project-manageroo-v{version}")
        self.assertEqual(package_release.INSTALLER_ZIP, f"uncle-matts-project-manageroo-v{version}.zip")
        self.assertEqual(package_release.SOURCE_ZIP, f"uncle-matts-project-manageroo-v{version}-source.zip")

    def test_end_user_and_source_archives_use_different_file_sets(self):
        source = {path.relative_to(ROOT).as_posix() for path in package_release.included_files()}
        end_user = {path.relative_to(ROOT).as_posix() for path in package_release.end_user_files()}
        self.assertIn("scripts/package_release.py", source)
        self.assertNotIn("scripts/package_release.py", end_user)
        self.assertIn("tests/test_package_release.py", source)
        self.assertNotIn("tests/test_package_release.py", end_user)
        for generated in package_release.EXPLICIT_GENERATED:
            if (ROOT / generated).is_file():
                self.assertIn(generated, source)
            self.assertNotIn(generated, end_user)
        self.assertIn("scripts/verify_release.py", end_user)
        self.assertIn("scripts/verify_distribution.py", end_user)
        self.assertNotEqual(source, end_user)

    def test_local_clawpatch_state_is_not_packaged_by_either_selector(self):
        for selector in (package_release.included_files, package_release.end_user_files):
            selected = {path.relative_to(ROOT).as_posix() for path in selector()}
            self.assertFalse(any(path == ".clawpatch" or path.startswith(".clawpatch/") for path in selected))
        self.assertIn(".clawpatch/", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_only_tracked_manageroo_release_policy_is_packaged(self):
        for selector in (package_release.included_files, package_release.end_user_files):
            selected = {path.relative_to(ROOT).as_posix() for path in selector()}
            manageroo_paths = {path for path in selected if path.startswith(".manageroo/")}
            self.assertEqual(manageroo_paths, {".manageroo/config.toml"})

    def test_untracked_sensitive_and_benign_working_tree_files_are_never_selected(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix="release-secret-fixture-") as temp:
            fixture = Path(temp)
            (fixture / ".env").write_text("SECRET=real\n", encoding="utf-8")
            (fixture / ".env.example").write_text("SECRET=replace-me\n", encoding="utf-8")
            (fixture / "credentials.json").write_text("{}\n", encoding="utf-8")
            (fixture / "private.pem").write_text("secret\n", encoding="utf-8")
            (fixture / "scratch.txt").write_text("untracked\n", encoding="utf-8")
            manageroo = fixture / ".manageroo"
            manageroo.mkdir()
            (manageroo / "PRODUCT-BRIEF.md").write_text("private brief\n", encoding="utf-8")
            prefix = fixture.relative_to(ROOT).as_posix()
            for selector in (package_release.included_files, package_release.end_user_files):
                selected = {path.relative_to(ROOT).as_posix() for path in selector()}
                self.assertFalse(any(path.startswith(prefix + "/") for path in selected))

    def test_tracked_sensitive_paths_are_still_excluded(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix="release-tracked-sensitive-") as temp:
            fixture = Path(temp)
            sensitive = {
                ".env": "SECRET=real\n",
                "credentials.json": "{}\n",
                "client-secret.json": "{}\n",
                "private.pem": "secret\n",
                "nested/service-credential.txt": "secret\n",
            }
            benign = "benign.txt"
            for relative, content in sensitive.items():
                path = fixture / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            (fixture / benign).write_text("safe\n", encoding="utf-8")
            fixture_prefix = fixture.relative_to(ROOT).as_posix()
            real_tracked = package_release._tracked_relative_paths()
            mocked_tracked = set(real_tracked)
            mocked_tracked.update(f"{fixture_prefix}/{relative}" for relative in sensitive)
            mocked_tracked.add(f"{fixture_prefix}/{benign}")
            with patch.object(package_release, "_tracked_relative_paths", return_value=mocked_tracked):
                for selector in (package_release.included_files, package_release.end_user_files):
                    selected = {path.relative_to(ROOT).as_posix() for path in selector()}
                    self.assertIn(f"{fixture_prefix}/{benign}", selected)
                    for relative in sensitive:
                        self.assertNotIn(f"{fixture_prefix}/{relative}", selected)

    def test_symlink_is_never_release_eligible(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix="release-link-fixture-") as temp:
            fixture = Path(temp)
            outside = fixture / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            link = fixture / "link.txt"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable")
            self.assertFalse(package_release.release_file_allowed(link))

    def test_release_file_list_rejects_parent_traversal_before_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            root = temp_root / "outer" / "project"
            root.mkdir(parents=True)
            victims = {
                "../outside.txt": temp_root / "outer" / "outside.txt",
                "../../outside.txt": temp_root / "outside.txt",
            }
            file_list = temp_root / "release-files"
            for victim in victims.values():
                victim.write_text("do not read or change\n", encoding="utf-8")

            for entry, victim in victims.items():
                with self.subTest(entry=entry):
                    file_list.write_bytes(package_release.os.fsencode(entry) + b"\0")
                    with (
                        patch.object(package_release, "ROOT", root),
                        patch.dict(
                            package_release.os.environ,
                            {package_release.RELEASE_FILE_LIST_ENV: str(file_list)},
                        ),
                    ):
                        with self.assertRaisesRegex(RuntimeError, "Unsafe release file-list entry"):
                            package_release.included_files()
                    self.assertEqual(victim.read_text(encoding="utf-8"), "do not read or change\n")

    def test_snapshot_staging_rejects_destination_escape_before_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp)
            root = temp_root / "project"
            root.mkdir()
            source = root / "README.md"
            source.write_text("safe source\n", encoding="utf-8")
            disguised_source = root / ".." / root.name / source.name
            candidate_root = temp_root / "candidate"
            candidate_root.mkdir()
            snapshot_root = candidate_root / "snapshot"
            escaped_destination = candidate_root / root.name / source.name

            with (
                patch.object(package_release, "ROOT", root),
                patch.object(package_release, "included_files", return_value=[disguised_source]),
            ):
                with self.assertRaisesRegex(RuntimeError, "unsafe release destination"):
                    package_release._stage_release_snapshot(snapshot_root)

            self.assertFalse(escaped_destination.exists())
            self.assertEqual(source.read_text(encoding="utf-8"), "safe source\n")

    def test_generated_files_are_not_required_to_exist_before_selection(self):
        tracked = package_release._tracked_relative_paths()
        with patch.object(package_release, "_tracked_relative_paths", return_value=tracked - package_release.EXPLICIT_GENERATED):
            files = package_release.included_files()
        selected = {path.relative_to(ROOT).as_posix() for path in files}
        self.assertIn("README.md", selected)
        self.assertIn("src/manageroo/__init__.py", selected)

    def test_bundled_skill_names_are_unique_and_support_files_are_packaged(self):
        included = {path.relative_to(ROOT).as_posix() for path in package_release.included_files()}
        skill_names = [path.parent.name for path in (ROOT / "src" / "manageroo" / "assets" / "skills").glob("*/SKILL.md")]
        counts = Counter(skill_names)
        self.assertEqual(len(skill_names), 54)
        self.assertEqual([name for name, count in counts.items() if count > 1], [])
        self.assertIn("skill-vetter", skill_names)
        self.assertIn("src/manageroo/assets/skills/playwright/references/cli.md", included)
        self.assertIn("src/manageroo/assets/skills/domain-modeling/ADR-FORMAT.md", included)
        self.assertIn("src/manageroo/assets/skills/diagnosing-bugs/scripts/hitl-loop.template.sh", included)
        self.assertIn("src/manageroo/assets/skills/writing-for-agents/LICENSE.txt", included)

    def test_bundled_playwright_skills_do_not_ship_decorative_images(self):
        included = {path.relative_to(ROOT).as_posix() for path in package_release.included_files()}
        image_suffixes = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
        for skill_name in ("playwright", "playwright-interactive"):
            skill_root = ROOT / "src" / "manageroo" / "assets" / "skills" / skill_name
            skill_prefix = f"{skill_root.relative_to(ROOT).as_posix()}/"
            self.assertFalse(any(path.startswith(skill_prefix) and Path(path).suffix.lower() in image_suffixes for path in included))
            metadata = (skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8")
            self.assertNotIn("icon_small:", metadata)
            self.assertNotIn("icon_large:", metadata)

    @unittest.skipIf(os.name == "nt", "Unix installer fixture")
    def test_release_smoke_rejects_installed_version_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "release.zip"
            with zipfile.ZipFile(archive, "w") as release:
                release.writestr(
                    f"{smoke_release_install.ARCHIVE_ROOT}/install.sh",
                    "#!/bin/sh\n"
                    'mkdir -p "$HOME/.local/bin"\n'
                    'cat > "$HOME/.local/bin/manageroo" <<\'EOF\'\n'
                    "#!/bin/sh\n"
                    "printf '%s\\n' 'wrong-version'\n"
                    "EOF\n"
                    'chmod +x "$HOME/.local/bin/manageroo"\n',
                )

            with self.assertRaisesRegex(
                RuntimeError,
                "Installed Manageroo version mismatch.*wrong-version",
            ):
                smoke_release_install.smoke(archive, skip_install_tests=True)

    def test_distribution_verifier_rejects_missing_console_entry_point(self):
        class FakeEnvBuilder:
            def __init__(self, **_kwargs):
                pass

            def create(self, root):
                executable = Path(root) / (
                    "Scripts/python.exe" if os.name == "nt" else "bin/python"
                )
                executable.parent.mkdir(parents=True)
                executable.write_bytes(b"")

        def fake_build(_python, wheel_dir):
            (wheel_dir / "manageroo.whl").write_bytes(b"")
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        with (
            patch.object(verify_distribution.venv, "EnvBuilder", FakeEnvBuilder),
            patch.object(verify_distribution, "_download_build_requirements"),
            patch.object(verify_distribution, "_install_build_requirements"),
            patch.object(verify_distribution, "_build_wheel", side_effect=fake_build),
            patch.object(verify_distribution, "_install_wheel"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Installed wheel did not create the manageroo console entry point",
            ):
                verify_distribution.verify_distribution()

    def test_distribution_build_uses_hash_locked_declared_requirements(self):
        build_system = tomllib.loads(
            (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )["build-system"]
        self.assertEqual(
            build_system["requires"],
            ["setuptools==80.9.0", "wheel==0.45.1"],
        )
        self.assertEqual(
            verify_distribution._locked_build_requirements(),
            build_system["requires"],
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wheelhouse = root / "wheelhouse"
            build_python = root / "build-venv" / "bin" / "python"
            wheel_dir = root / "wheel"
            with patch.object(verify_distribution, "_run") as run:
                verify_distribution._download_build_requirements(wheelhouse)

            download_argv = run.call_args.args[0]
            self.assertIn("--require-hashes", download_argv)
            self.assertIn("--only-binary=:all:", download_argv)
            self.assertIn("--no-deps", download_argv)
            self.assertIn(str(verify_distribution.BUILD_REQUIREMENTS_LOCK), download_argv)

            with patch.object(verify_distribution, "_run") as run:
                verify_distribution._install_build_requirements(
                    build_python,
                    wheelhouse,
                    root,
                )

            install_argv = run.call_args.args[0]
            self.assertIn("--no-index", install_argv)
            self.assertIn("--find-links", install_argv)
            self.assertIn("--require-hashes", install_argv)

            with patch.object(verify_distribution, "_run") as run:
                verify_distribution._build_wheel(build_python, wheel_dir)

        argv = run.call_args.args[0]
        self.assertEqual(argv[0], str(build_python))
        self.assertIn("--no-build-isolation", argv)
        self.assertIn("--no-index", argv)
        self.assertIn("--no-deps", argv)
        self.assertEqual(run.call_args.kwargs, {"cwd": ROOT, "timeout": 600})

    def test_distribution_install_ignores_inherited_pythonpath(self):
        python = Path("venv") / "bin" / "python"
        wheel = Path("wheel") / "manageroo.whl"
        root = Path("proof")
        with patch.object(verify_distribution, "_run") as run:
            verify_distribution._install_wheel(python, wheel, root)

        self.assertEqual(
            run.call_args.args[0],
            [
                str(python),
                "-I",
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                str(wheel),
            ],
        )
        self.assertEqual(run.call_args.kwargs, {"cwd": root, "timeout": 300})

    def test_write_archive_failure_preserves_existing_published_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "release.zip"
            output.write_bytes(b"known-good")
            files = [ROOT / "README.md", ROOT / "pyproject.toml"]
            original_write = zipfile.ZipFile.write
            calls = {"count": 0}

            def fail_late(archive, *args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 2:
                    raise OSError("simulated archive write failure")
                return original_write(archive, *args, **kwargs)

            with patch.object(zipfile.ZipFile, "write", new=fail_late):
                with self.assertRaises(OSError):
                    package_release.write_archive(output, files)
            self.assertEqual(output.read_bytes(), b"known-good")

    def test_packaging_uses_staged_bytes_after_live_worktree_mutations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            files = {
                ".manageroo/config.toml": "# release policy fixture\n",
                "README.md": "validated snapshot\n",
                "pyproject.toml": "[project]\nname = 'fixture'\nversion = '1'\n",
                "install.sh": "#!/bin/sh\n",
                "install.ps1": "# fixture\n",
                "docs/placeholder.md": "fixture\n",
                "src/manageroo/__init__.py": "__version__ = '1'\n",
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            expected = (root / "README.md").read_bytes()
            tracked = set(files)
            captured = {}
            real_write_archive = package_release.write_archive
            archive_calls = {"count": 0}

            def fake_run(argv, **_kwargs):
                if argv[-1] == "scripts/verify_release.py":
                    (root / "README.md").write_text("changed after validation\n", encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0)

            def mutate_then_write(output, selected):
                archive_calls["count"] += 1
                if archive_calls["count"] == 1:
                    (root / "README.md").write_text("changed after checksums\n", encoding="utf-8")
                real_write_archive(output, selected)

            def capture_publish(candidate_output, candidate_source, _drop_dir):
                with zipfile.ZipFile(candidate_output) as archive:
                    captured["installer_readme"] = archive.read(
                        f"{package_release.ARCHIVE_ROOT}/README.md"
                    )
                with zipfile.ZipFile(candidate_source) as archive:
                    captured["source_readme"] = archive.read(
                        f"{package_release.ARCHIVE_ROOT}/README.md"
                    )
                    captured["checksums"] = archive.read(
                        f"{package_release.ARCHIVE_ROOT}/SHA256SUMS.txt"
                    ).decode()
                return {"release_created": True, "warnings": []}

            with (
                patch.object(package_release, "ROOT", root),
                patch.object(package_release, "OUTPUT", root / "release.zip"),
                patch.object(package_release, "SOURCE_OUTPUT", root / "release-source.zip"),
                patch.object(package_release, "DEFAULT_DROP_DIR", root / "drop"),
                patch.object(package_release, "_tracked_relative_paths", return_value=tracked),
                patch.object(package_release.subprocess, "run", side_effect=fake_run),
                patch.object(package_release, "write_archive", side_effect=mutate_then_write),
                patch.object(package_release, "_publish_release", side_effect=capture_publish),
            ):
                self.assertEqual(package_release.main(), 0)

            expected_hash = hashlib.sha256(expected).hexdigest()
            self.assertEqual(captured["installer_readme"], expected)
            self.assertEqual(captured["source_readme"], expected)
            self.assertIn(f"{expected_hash}  README.md\n", captured["checksums"])
            self.assertEqual(
                (root / "README.md").read_text(encoding="utf-8"),
                "changed after checksums\n",
            )

    def test_drop_folder_copies_distinct_archives(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            end_user_archive = root / "end-user.zip"
            source_archive = root / "source.zip"
            drop = root / "drop"
            end_user_archive.write_bytes(b"end-user")
            source_archive.write_bytes(b"source")
            package_release.refresh_drop_folder(drop, end_user_archive, source_archive)
            self.assertEqual((drop / package_release.INSTALLER_ZIP).read_bytes(), b"end-user")
            self.assertEqual((drop / package_release.SOURCE_ZIP).read_bytes(), b"source")

    def test_drop_refresh_failure_preserves_previous_drop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            end_user_archive = root / "end-user.zip"
            source_archive = root / "source.zip"
            drop = root / "drop"
            drop.mkdir()
            (drop / "operator-note.txt").write_text("keep me", encoding="utf-8")
            (drop / package_release.INSTALLER_ZIP).write_bytes(b"old-end-user")
            (drop / package_release.SOURCE_ZIP).write_bytes(b"old-source")
            before = {path.name: path.read_bytes() for path in drop.iterdir() if path.is_file()}
            end_user_archive.write_bytes(b"new-end-user")
            source_archive.write_bytes(b"new-source")
            original_copy2 = package_release.shutil.copy2
            calls = {"count": 0}

            def fail_during_stage(source, destination, *args, **kwargs):
                calls["count"] += 1
                if calls["count"] == 3:
                    raise OSError("simulated drop staging failure")
                return original_copy2(source, destination, *args, **kwargs)

            with patch.object(package_release.shutil, "copy2", side_effect=fail_during_stage):
                with self.assertRaises(OSError):
                    package_release.refresh_drop_folder(drop, end_user_archive, source_archive)
            after = {path.name: path.read_bytes() for path in drop.iterdir() if path.is_file()}
            self.assertEqual(after, before)

    def test_publish_release_drop_failure_restores_previous_archives_and_drop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "release.zip"
            source_output = root / "release-source.zip"
            candidate_output = root / "candidate-release.zip"
            candidate_source = root / "candidate-source.zip"
            drop = root / "drop"
            output.write_bytes(b"old-end-user")
            source_output.write_bytes(b"old-source")
            candidate_output.write_bytes(b"new-end-user")
            candidate_source.write_bytes(b"new-source")
            drop.mkdir()
            (drop / "operator-note.txt").write_text("keep me", encoding="utf-8")
            (drop / package_release.INSTALLER_ZIP).write_bytes(b"old-end-user")
            (drop / package_release.SOURCE_ZIP).write_bytes(b"old-source")
            drop_before = {
                path.name: path.read_bytes()
                for path in drop.iterdir()
                if path.is_file()
            }
            original_copy2 = package_release.shutil.copy2

            def fail_during_drop_stage(source, destination, *args, **kwargs):
                if Path(source) == output:
                    raise OSError("simulated drop staging failure")
                return original_copy2(source, destination, *args, **kwargs)

            def drop_copies(end_user_archive, source_archive):
                return {
                    package_release.INSTALLER_ZIP: end_user_archive,
                    package_release.SOURCE_ZIP: source_archive,
                }

            with (
                patch.object(package_release, "OUTPUT", output),
                patch.object(package_release, "SOURCE_OUTPUT", source_output),
                patch.object(package_release, "_drop_copies", side_effect=drop_copies),
                patch.object(
                    package_release.shutil,
                    "copy2",
                    side_effect=fail_during_drop_stage,
                ),
            ):
                with self.assertRaisesRegex(OSError, "simulated drop staging failure"):
                    package_release._publish_release(candidate_output, candidate_source, drop)

            self.assertEqual(output.read_bytes(), b"old-end-user")
            self.assertEqual(source_output.read_bytes(), b"old-source")
            self.assertEqual(candidate_output.read_bytes(), b"new-end-user")
            self.assertEqual(candidate_source.read_bytes(), b"new-source")
            self.assertEqual(
                {
                    path.name: path.read_bytes()
                    for path in drop.iterdir()
                    if path.is_file()
                },
                drop_before,
            )

    def test_post_publication_cleanup_failure_warns_and_retry_reconciles_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "release.zip"
            source_output = root / "release-source.zip"
            candidate_output = root / "candidate-release.zip"
            candidate_source = root / "candidate-source.zip"
            drop = root / "drop"
            output.write_bytes(b"old-end-user")
            source_output.write_bytes(b"old-source")
            candidate_output.write_bytes(b"new-end-user")
            candidate_source.write_bytes(b"new-source")
            drop.mkdir()
            (drop / package_release.INSTALLER_ZIP).write_bytes(b"old-end-user")
            (drop / package_release.SOURCE_ZIP).write_bytes(b"old-source")
            path_type = type(output)
            original_unlink = path_type.unlink

            def drop_copies(end_user_archive, source_archive):
                return {
                    package_release.INSTALLER_ZIP: end_user_archive,
                    package_release.SOURCE_ZIP: source_archive,
                }

            def fail_output_backup_cleanup(path, *args, **kwargs):
                if path == root / "release.zip.manageroo-previous":
                    raise OSError("simulated cleanup failure")
                return original_unlink(path, *args, **kwargs)

            with (
                patch.object(package_release, "OUTPUT", output),
                patch.object(package_release, "SOURCE_OUTPUT", source_output),
                patch.object(package_release, "_drop_copies", side_effect=drop_copies),
                patch.object(path_type, "unlink", autospec=True, side_effect=fail_output_backup_cleanup),
            ):
                result = package_release._publish_release(candidate_output, candidate_source, drop)

            self.assertTrue(result["release_created"])
            self.assertEqual(len(result["warnings"]), 1)
            self.assertIn("simulated cleanup failure", result["warnings"][0])
            self.assertEqual(output.read_bytes(), b"new-end-user")
            self.assertEqual(source_output.read_bytes(), b"new-source")
            self.assertEqual(
                (drop / package_release.INSTALLER_ZIP).read_bytes(), b"new-end-user"
            )
            self.assertEqual((drop / package_release.SOURCE_ZIP).read_bytes(), b"new-source")
            self.assertTrue((root / "release.zip.manageroo-previous").is_file())

            retry_output = root / "retry-release.zip"
            retry_source = root / "retry-source.zip"
            retry_output.write_bytes(b"new-end-user")
            retry_source.write_bytes(b"new-source")
            with (
                patch.object(package_release, "OUTPUT", output),
                patch.object(package_release, "SOURCE_OUTPUT", source_output),
                patch.object(package_release, "_drop_copies", side_effect=drop_copies),
            ):
                retry = package_release._publish_release(retry_output, retry_source, drop)

            self.assertTrue(retry["release_created"])
            self.assertEqual(retry["warnings"], [])
            self.assertEqual(list(root.glob("*.manageroo-previous")), [])

    def test_drop_refresh_preserves_interrupted_transaction_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            end_user_archive = root / "end-user.zip"
            source_archive = root / "source.zip"
            drop = root / "drop"
            backup = root / "drop.manageroo-previous"
            backup.mkdir()
            (backup / "operator-note.txt").write_text("keep me", encoding="utf-8")
            end_user_archive.write_bytes(b"new-end-user")
            source_archive.write_bytes(b"new-source")

            with self.assertRaisesRegex(RuntimeError, "Interrupted release-drop transaction"):
                package_release.refresh_drop_folder(drop, end_user_archive, source_archive)

            self.assertFalse(drop.exists())
            self.assertEqual(
                (backup / "operator-note.txt").read_text(encoding="utf-8"),
                "keep me",
            )
            self.assertEqual(list(root.glob(".drop.stage-*")), [])

    def test_archive_pair_publish_preserves_interrupted_transaction_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "release.zip"
            source_output = root / "release-source.zip"
            output_backup = root / "release.zip.manageroo-previous"
            source_backup = root / "release-source.zip.manageroo-previous"
            candidate_output = root / "candidate-release.zip"
            candidate_source = root / "candidate-source.zip"
            output_backup.write_bytes(b"old-end-user")
            source_backup.write_bytes(b"old-source")
            candidate_output.write_bytes(b"new-end-user")
            candidate_source.write_bytes(b"new-source")

            with (
                patch.object(package_release, "OUTPUT", output),
                patch.object(package_release, "SOURCE_OUTPUT", source_output),
            ):
                with self.assertRaisesRegex(RuntimeError, "Interrupted release archive transaction"):
                    package_release._publish_archive_pair(candidate_output, candidate_source)

            self.assertFalse(output.exists())
            self.assertFalse(source_output.exists())
            self.assertEqual(output_backup.read_bytes(), b"old-end-user")
            self.assertEqual(source_backup.read_bytes(), b"old-source")
            self.assertEqual(candidate_output.read_bytes(), b"new-end-user")
            self.assertEqual(candidate_source.read_bytes(), b"new-source")

    def test_archive_pair_publish_preserves_existing_archives_when_first_backup_rename_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "release.zip"
            source_output = root / "release-source.zip"
            candidate_output = root / "candidate-release.zip"
            candidate_source = root / "candidate-source.zip"
            output.write_bytes(b"old-end-user")
            source_output.write_bytes(b"old-source")
            candidate_output.write_bytes(b"new-end-user")
            candidate_source.write_bytes(b"new-source")
            path_type = type(output)
            original_rename = path_type.rename

            def fail_first_backup_rename(path, target):
                if path == output:
                    raise OSError("simulated first backup rename failure")
                return original_rename(path, target)

            with (
                patch.object(package_release, "OUTPUT", output),
                patch.object(package_release, "SOURCE_OUTPUT", source_output),
                patch.object(path_type, "rename", autospec=True, side_effect=fail_first_backup_rename),
            ):
                with self.assertRaisesRegex(OSError, "simulated first backup rename failure"):
                    package_release._publish_archive_pair(candidate_output, candidate_source)

            self.assertEqual(output.read_bytes(), b"old-end-user")
            self.assertEqual(source_output.read_bytes(), b"old-source")
            self.assertEqual(candidate_output.read_bytes(), b"new-end-user")
            self.assertEqual(candidate_source.read_bytes(), b"new-source")

    def test_sibling_checkout_publishers_share_destination_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context = multiprocessing.get_context("spawn")
            first_published = context.Event()
            second_published = context.Event()
            second_lock_contended = context.Event()
            release_first = context.Event()
            first = context.Process(
                target=_publish_release_fixture,
                args=(root, "checkout-a", "a", None, first_published, release_first),
            )
            second = context.Process(
                target=_publish_release_fixture,
                args=(
                    root,
                    "checkout-b",
                    "b",
                    second_lock_contended,
                    second_published,
                    release_first,
                ),
            )

            try:
                first.start()
                self.assertTrue(first_published.wait(timeout=5))
                second.start()
                self.assertTrue(second_lock_contended.wait(timeout=5))
                self.assertFalse(second_published.is_set())
                release_first.set()
                first.join(timeout=5)
                second.join(timeout=5)
                self.assertEqual(first.exitcode, 0)
                self.assertEqual(second.exitcode, 0)

                output_marker = (root / "release.zip").read_bytes().split(b"-", 1)[0]
                source_marker = (root / "release-source.zip").read_bytes().split(b"-", 1)[0]
                drop_output_marker = (
                    root / "drop" / package_release.INSTALLER_ZIP
                ).read_bytes().split(b"-", 1)[0]
                drop_source_marker = (
                    root / "drop" / package_release.SOURCE_ZIP
                ).read_bytes().split(b"-", 1)[0]
                self.assertEqual(
                    {output_marker, source_marker, drop_output_marker, drop_source_marker},
                    {b"b"},
                )
            finally:
                release_first.set()
                for process in (first, second):
                    if process.pid is not None:
                        process.join(timeout=1)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)

    def test_drop_folder_removes_stale_release_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            end_user_archive = root / "end-user.zip"
            source_archive = root / "source.zip"
            drop = root / "drop"
            drop.mkdir()
            end_user_archive.write_bytes(b"end-user")
            source_archive.write_bytes(b"source")
            (drop / "Manageroo-v2025.1.2.zip").write_bytes(b"stale")
            old_prefix = _fixture([85, 77, 83, 77, 70, 66, 85, 82, 65, 83, 66, 79, 70, 69])
            (drop / f"{old_prefix}-v2025.1.2-source.zip").write_bytes(b"stale")
            (drop / "Manageroo-notes.txt").write_text("operator notes", encoding="utf-8")
            (drop / "operator-note.txt").write_text("keep me", encoding="utf-8")
            package_release.refresh_drop_folder(drop, end_user_archive, source_archive)
            self.assertFalse((drop / "Manageroo-v2025.1.2.zip").exists())
            self.assertFalse((drop / f"{old_prefix}-v2025.1.2-source.zip").exists())
            self.assertEqual(
                (drop / "Manageroo-notes.txt").read_text(encoding="utf-8"),
                "operator notes",
            )
            self.assertEqual((drop / "operator-note.txt").read_text(encoding="utf-8"), "keep me")


if __name__ == "__main__":
    unittest.main()

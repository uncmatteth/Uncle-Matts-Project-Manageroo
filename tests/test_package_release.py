import importlib.util
import tempfile
import tomllib
import unittest
import zipfile
from collections import Counter
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_release", ROOT / "scripts" / "package_release.py")
assert SPEC and SPEC.loader
package_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_release)


def _fixture(codes: list[int]) -> str:
    return "".join(chr(code) for code in codes)


class PackageReleaseTests(unittest.TestCase):
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
        self.assertEqual(len(skill_names), 50)
        self.assertEqual([name for name, count in counts.items() if count > 1], [])
        self.assertIn("skill-vetter", skill_names)
        self.assertIn("src/manageroo/assets/skills/playwright/references/cli.md", included)
        self.assertIn("src/manageroo/assets/skills/grill-with-docs/ADR-FORMAT.md", included)

    def test_package_release_runs_end_user_zip_smoke_and_canonical_version(self):
        project_version = str(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
        package_text = (ROOT / "scripts" / "package_release.py").read_text(encoding="utf-8")
        smoke_text = (ROOT / "scripts" / "smoke_release_install.py").read_text(encoding="utf-8")
        self.assertIn("scripts/smoke_release_install.py", package_text)
        self.assertIn("--skip-install-tests", package_text)
        self.assertIn('PROJECT_VERSION = str(tomllib.loads(', package_text)
        self.assertIn('EXPECTED_VERSION = str(tomllib.loads(', smoke_text)
        self.assertEqual(package_release.PROJECT_VERSION, project_version)
        self.assertIn("if version != EXPECTED_VERSION", smoke_text)
        self.assertIn("EXPECTED_SKILL_COUNT = 18", smoke_text)

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

    def test_drop_folder_removes_stale_release_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            end_user_archive = root / "end-user.zip"
            source_archive = root / "source.zip"
            drop = root / "drop"
            drop.mkdir()
            end_user_archive.write_bytes(b"end-user")
            source_archive.write_bytes(b"source")
            (drop / "Manageroo-old.zip").write_bytes(b"stale")
            old_prefix = _fixture([85, 77, 83, 77, 70, 66, 85, 82, 65, 83, 66, 79, 70, 69])
            (drop / f"{old_prefix}-old.zip").write_bytes(b"stale")
            (drop / "operator-note.txt").write_text("keep me", encoding="utf-8")
            package_release.refresh_drop_folder(drop, end_user_archive, source_archive)
            self.assertFalse((drop / "Manageroo-old.zip").exists())
            self.assertFalse((drop / f"{old_prefix}-old.zip").exists())
            self.assertEqual((drop / "operator-note.txt").read_text(encoding="utf-8"), "keep me")


if __name__ == "__main__":
    unittest.main()

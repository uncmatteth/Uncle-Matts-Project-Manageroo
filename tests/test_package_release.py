import importlib.util
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_release", ROOT / "scripts" / "package_release.py")
assert SPEC and SPEC.loader
package_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_release)


def _fixture(codes: list[int]) -> str:
    return "".join(chr(code) for code in codes)


class PackageReleaseTests(unittest.TestCase):
    def test_release_names_use_project_manageroo_brand(self):
        self.assertEqual(package_release.ARCHIVE_ROOT, "Uncle-Matts-Project-Manageroo")
        self.assertEqual(package_release.DROP_ROOT, "uncle-matts-project-manageroo-v2026.7.17.2")
        self.assertNotEqual(package_release.DROP_ROOT, package_release.ARCHIVE_ROOT)
        self.assertEqual(package_release.INSTALLER_ZIP, "uncle-matts-project-manageroo-v2026.7.17.2.zip")
        self.assertEqual(package_release.SOURCE_ZIP, "uncle-matts-project-manageroo-v2026.7.17.2-source.zip")

    def test_end_user_and_source_archives_use_different_file_sets(self):
        source = {path.relative_to(ROOT).as_posix() for path in package_release.included_files()}
        end_user = {path.relative_to(ROOT).as_posix() for path in package_release.end_user_files()}

        self.assertIn("scripts/package_release.py", source)
        self.assertNotIn("scripts/package_release.py", end_user)
        self.assertIn("tests/test_package_release.py", source)
        self.assertNotIn("tests/test_package_release.py", end_user)
        self.assertIn("BUILD-VALIDATION.json", source)
        self.assertNotIn("BUILD-VALIDATION.json", end_user)
        self.assertIn("SHA256SUMS.txt", source)
        self.assertNotIn("SHA256SUMS.txt", end_user)
        self.assertIn("docs/FILE_MANIFEST.md", source)
        self.assertNotIn("docs/FILE_MANIFEST.md", end_user)
        self.assertIn("scripts/verify_release.py", end_user)
        self.assertIn("tests/test_inventory.py", end_user)
        self.assertIn("tests/test_external_loop_library_removed.py", source)
        self.assertNotIn("src/manageroo/loop_library.py", source)
        self.assertNotIn("tests/test_loop_library.py", source)
        self.assertNotEqual(source, end_user)

    def test_local_clawpatch_state_is_not_packaged(self):
        included = {path.relative_to(ROOT).as_posix() for path in package_release.included_files()}

        self.assertFalse(any(path == ".clawpatch" or path.startswith(".clawpatch/") for path in included))
        self.assertIn(".clawpatch/", (ROOT / ".gitignore").read_text(encoding="utf-8"))

    def test_sensitive_local_state_is_never_selected_for_archives(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix="release-secret-fixture-") as temp:
            fixture = Path(temp)
            (fixture / ".env").write_text("SECRET=real\n", encoding="utf-8")
            (fixture / ".env.local").write_text("SECRET=real\n", encoding="utf-8")
            (fixture / ".env.example").write_text("SECRET=replace-me\n", encoding="utf-8")
            (fixture / "credentials.json").write_text("{}\n", encoding="utf-8")
            (fixture / "private.pem").write_text("secret\n", encoding="utf-8")
            manageroo = fixture / ".manageroo"
            manageroo.mkdir()
            (manageroo / "PRODUCT-BRIEF.md").write_text("private brief\n", encoding="utf-8")

            included = {path.relative_to(ROOT).as_posix() for path in package_release.included_files()}
            prefix = fixture.relative_to(ROOT).as_posix()
            self.assertNotIn(f"{prefix}/.env", included)
            self.assertNotIn(f"{prefix}/.env.local", included)
            self.assertNotIn(f"{prefix}/credentials.json", included)
            self.assertNotIn(f"{prefix}/private.pem", included)
            self.assertFalse(any(path.startswith(f"{prefix}/.manageroo/") for path in included))
            self.assertIn(f"{prefix}/.env.example", included)

    def test_bundled_skill_names_are_unique_and_support_files_are_packaged(self):
        included = {path.relative_to(ROOT).as_posix() for path in package_release.included_files()}
        skill_names = [
            path.parent.name
            for path in (ROOT / "src" / "manageroo" / "assets" / "skills").glob("*/SKILL.md")
        ]
        counts = Counter(skill_names)

        self.assertGreaterEqual(len(skill_names), 40)
        self.assertEqual([name for name, count in counts.items() if count > 1], [])
        self.assertIn("src/manageroo/assets/skills/playwright/references/cli.md", included)
        self.assertIn("src/manageroo/assets/skills/grill-with-docs/ADR-FORMAT.md", included)

    def test_package_release_runs_end_user_zip_smoke(self):
        package_text = (ROOT / "scripts" / "package_release.py").read_text(encoding="utf-8")
        verifier_text = (ROOT / "scripts" / "verify_release.py").read_text(encoding="utf-8")
        smoke_text = (ROOT / "scripts" / "smoke_release_install.py").read_text(encoding="utf-8")

        self.assertIn("scripts/smoke_release_install.py", package_text)
        self.assertIn("--skip-install-tests", package_text)
        self.assertIn("scripts/smoke_release_install.py", verifier_text)
        self.assertIn('VERSION_TAG = "v2026.7.17.2"', smoke_text)
        self.assertIn("EXPECTED_SKILL_COUNT = 49", smoke_text)
        self.assertIn('str(extracted / "install.ps1")', smoke_text)
        self.assertIn('"install.sh"', smoke_text)
        self.assertIn('"manageroo"', smoke_text)
        self.assertIn('"solo"', smoke_text)
        self.assertIn('"run"', smoke_text)

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

    def test_publish_docs_asset_list_matches_generated_drop_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            end_user_archive = root / "end-user.zip"
            source_archive = root / "source.zip"
            drop = root / "drop"
            end_user_archive.write_bytes(b"end-user")
            source_archive.write_bytes(b"source")

            package_release.refresh_drop_folder(drop, end_user_archive, source_archive)

            publish_text = (ROOT / "PUBLISH_TO_GITHUB.md").read_text(encoding="utf-8")
            for asset in sorted(path.name for path in drop.iterdir() if path.is_file()):
                with self.subTest(asset=asset):
                    self.assertIn(asset, publish_text)


if __name__ == "__main__":
    unittest.main()

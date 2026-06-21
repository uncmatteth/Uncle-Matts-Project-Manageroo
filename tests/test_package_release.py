import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_release", ROOT / "scripts" / "package_release.py")
assert SPEC and SPEC.loader
package_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_release)


class PackageReleaseTests(unittest.TestCase):
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
        self.assertNotEqual(source, end_user)

    def test_drop_folder_copies_distinct_archives(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            end_user_archive = root / "end-user.zip"
            source_archive = root / "source.zip"
            drop = root / "drop"
            end_user_archive.write_bytes(b"end-user")
            source_archive.write_bytes(b"source")

            package_release.refresh_drop_folder(drop, end_user_archive, source_archive)

            self.assertEqual((drop / package_release.END_USER_ZIP).read_bytes(), b"end-user")
            self.assertEqual((drop / package_release.SOURCE_ZIP).read_bytes(), b"source")


if __name__ == "__main__":
    unittest.main()

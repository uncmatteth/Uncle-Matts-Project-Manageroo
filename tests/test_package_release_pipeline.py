import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "manageroo_package_release_pipeline",
    ROOT / "scripts" / "package_release.py",
)
assert SPEC and SPEC.loader
package_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package_release)


class PackageReleasePipelineTests(unittest.TestCase):
    def test_distribution_failure_stops_before_manifest_or_archive_generation(self):
        calls = []

        def fake_run(argv, **_kwargs):
            calls.append(list(argv))
            if argv[-1] == "scripts/verify_release.py":
                return SimpleNamespace(returncode=0)
            if argv[-1] == "scripts/verify_distribution.py":
                return SimpleNamespace(returncode=7)
            raise AssertionError(f"unexpected subprocess: {argv}")

        with patch.object(package_release.subprocess, "run", side_effect=fake_run), patch.object(
            package_release, "generate_manifest"
        ) as manifest, patch.object(package_release, "write_archive") as archive:
            code = package_release.main()

        self.assertEqual(code, 7)
        self.assertEqual(
            calls,
            [
                [package_release.sys.executable, "scripts/verify_release.py"],
                [package_release.sys.executable, "scripts/verify_distribution.py"],
            ],
        )
        manifest.assert_not_called()
        archive.assert_not_called()


if __name__ == "__main__":
    unittest.main()

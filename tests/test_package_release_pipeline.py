import importlib.util
import tempfile
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

    def test_smoke_failure_never_publishes_candidate_archives_or_refreshes_drop(self):
        calls = []

        def fake_run(argv, **_kwargs):
            calls.append(list(argv))
            if "smoke_release_install.py" in " ".join(argv):
                return SimpleNamespace(returncode=9)
            return SimpleNamespace(returncode=0)

        with patch.object(package_release.subprocess, "run", side_effect=fake_run), patch.object(
            package_release, "generate_manifest"
        ), patch.object(package_release, "included_files", return_value=[]), patch.object(
            package_release, "end_user_files", return_value=[]
        ), patch.object(package_release, "write_archive") as write_archive, patch.object(
            package_release, "_publish_archive_pair"
        ) as publish, patch.object(package_release, "refresh_drop_folder") as refresh:
            code = package_release.main()

        self.assertEqual(code, 9)
        self.assertEqual(write_archive.call_count, 2)
        publish.assert_not_called()
        refresh.assert_not_called()
        self.assertEqual(calls[0], [package_release.sys.executable, "scripts/verify_release.py"])
        self.assertEqual(calls[1], [package_release.sys.executable, "scripts/verify_distribution.py"])
        self.assertIn("scripts/smoke_release_install.py", calls[2])

    def test_success_path_runs_verify_distribution_smoke_publish_and_drop_in_order(self):
        events = []

        def fake_run(argv, **_kwargs):
            if argv[-1] == "scripts/verify_release.py":
                events.append("verify-release")
            elif argv[-1] == "scripts/verify_distribution.py":
                events.append("verify-distribution")
            elif "scripts/smoke_release_install.py" in argv:
                events.append("smoke")
            else:
                raise AssertionError(f"unexpected subprocess: {argv}")
            return SimpleNamespace(returncode=0)

        def fake_write(path, _files):
            events.append("write-installer" if path.name == package_release.INSTALLER_ZIP else "write-source")
            path.write_bytes(b"candidate")

        with patch.object(package_release.subprocess, "run", side_effect=fake_run), patch.object(
            package_release, "generate_manifest", side_effect=lambda: events.append("manifest")
        ), patch.object(package_release, "included_files", return_value=[]), patch.object(
            package_release, "end_user_files", return_value=[]
        ), patch.object(package_release, "write_archive", side_effect=fake_write), patch.object(
            package_release, "_publish_archive_pair", side_effect=lambda *_args: events.append("publish")
        ), patch.object(
            package_release, "refresh_drop_folder", side_effect=lambda *_args: events.append("drop")
        ):
            code = package_release.main()

        self.assertEqual(code, 0)
        self.assertEqual(
            events,
            [
                "verify-release",
                "verify-distribution",
                "manifest",
                "write-installer",
                "write-source",
                "smoke",
                "publish",
                "drop",
            ],
        )


if __name__ == "__main__":
    unittest.main()

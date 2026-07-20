import importlib.util
import re
import tomllib
import unittest
from pathlib import Path

from manageroo import __version__


ROOT = Path(__file__).resolve().parents[1]
VERSION_TAG_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])v\d+(?:\.\d+){2,3}(?:-(?:rc|alpha|beta|pre|dev)\d*)?(?!\.\d)(?![A-Za-z0-9-])"
)


def _load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VersionConsistencyTests(unittest.TestCase):
    def test_package_cli_and_release_artifacts_use_one_version(self):
        with (ROOT / "pyproject.toml").open("rb") as handle:
            project_version = tomllib.load(handle)["project"]["version"]

        package_release = _load_module("manageroo_package_release_version", "scripts/package_release.py")
        smoke_release = _load_module("manageroo_smoke_release_version", "scripts/smoke_release_install.py")

        expected_tag = f"v{project_version}"
        self.assertEqual(__version__, project_version)
        self.assertEqual(package_release.VERSION_TAG, expected_tag)
        self.assertEqual(smoke_release.VERSION_TAG, expected_tag)
        self.assertIn(expected_tag, package_release.INSTALLER_ZIP)
        self.assertIn(expected_tag, package_release.SOURCE_ZIP)

    def test_publish_guide_uses_only_current_release_version(self):
        publish = (ROOT / "PUBLISH_TO_GITHUB.md").read_text(encoding="utf-8")
        current_tag = f"v{__version__}"
        release_tags = set(VERSION_TAG_PATTERN.findall(publish))
        self.assertEqual(release_tags, {current_tag})

    def test_version_pattern_rejects_stale_semver_and_suffixed_tags(self):
        current_tag = f"v{__version__}"
        fixture = f"Release {current_tag}. Do not also publish v1.2.3 or {current_tag}-rc1."
        self.assertEqual(
            set(VERSION_TAG_PATTERN.findall(fixture)),
            {current_tag, "v1.2.3", f"{current_tag}-rc1"},
        )

    def test_version_pattern_keeps_full_tags_in_release_filenames_without_truncation(self):
        current_tag = f"v{__version__}"
        fixture = (
            f"uncle-matts-project-manageroo-{current_tag}.zip\n"
            f"uncle-matts-project-manageroo-{current_tag}-source.zip\n"
        )
        self.assertEqual(VERSION_TAG_PATTERN.findall(fixture), [current_tag])


if __name__ == "__main__":
    unittest.main()

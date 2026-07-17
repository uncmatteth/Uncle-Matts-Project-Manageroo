import importlib.util
import re
import tomllib
import unittest
from pathlib import Path

from manageroo import __version__


ROOT = Path(__file__).resolve().parents[1]


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

    def test_publish_guide_uses_current_release_version(self):
        publish = (ROOT / "PUBLISH_TO_GITHUB.md").read_text(encoding="utf-8")
        current_tag = f"v{__version__}"
        release_tags = set(re.findall(r"v\d{4}\.\d+\.\d+\.\d+", publish))
        self.assertEqual(release_tags, {current_tag})


if __name__ == "__main__":
    unittest.main()

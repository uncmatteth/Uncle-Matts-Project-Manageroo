import os
import tempfile
import unittest
from pathlib import Path

from manageroo.errors import SafetyError
from manageroo.policy import ScopePolicy, validate_allowed_scope_patterns
from manageroo.token_modes import _copy_skill_tree


class ScopeAndSkillPathHardeningTests(unittest.TestCase):
    def test_top_level_and_nested_secret_credential_paths_can_be_explicitly_scoped(self):
        paths = (
            "client-secret.json",
            "config/client-secret.json",
            "credentials.json",
            "config/service-credential.json",
            "api-credentials.txt",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(validate_allowed_scope_patterns([path]), [path])
                self.assertEqual(ScopePolicy((path,)).validate_paths([path]), [path])

    def test_nested_destination_symlink_cannot_escape_skill_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source_refs = source / "references"
            source_refs.mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
            (source_refs / "guide.md").write_text("new content\n", encoding="utf-8")

            skills = root / "skills"
            destination = skills / "demo"
            destination.mkdir(parents=True)
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "guide.md"
            marker.write_text("do not overwrite\n", encoding="utf-8")
            try:
                os.symlink(outside, destination / "references")
            except OSError:
                self.skipTest("symlinks unavailable")

            with self.assertRaises(ValueError):
                _copy_skill_tree(source, destination, root_real=skills.resolve())
            self.assertEqual(marker.read_text(encoding="utf-8"), "do not overwrite\n")


if __name__ == "__main__":
    unittest.main()

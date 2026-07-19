import tempfile
import unittest
from pathlib import Path

from manageroo.host_skills import inspect_host_skills
from manageroo.token_modes import CORE_SKILL_PACK, OPTIONAL_SKILL_PACK


class HostSkillBoundaryTests(unittest.TestCase):
    def _skill(self, root: Path, name: str) -> None:
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")

    def test_host_inventory_separates_core_optional_and_host_owned_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "skills"
            core = next(iter(CORE_SKILL_PACK))
            optional = next(iter(OPTIONAL_SKILL_PACK))
            self._skill(root, core)
            self._skill(root, optional)
            self._skill(root, "tommy-tos-private-skill")

            report = inspect_host_skills([root])

            self.assertIn(core, report["manageroo_core_present"])
            self.assertIn(optional, report["known_optional_present"])
            self.assertIn("tommy-tos-private-skill", report["host_owned_or_external"])
            self.assertNotIn("tommy-tos-private-skill", report["manageroo_core_present"])

    def test_optional_library_never_contains_manageroo_core(self):
        self.assertFalse(set(CORE_SKILL_PACK) & set(OPTIONAL_SKILL_PACK))
        self.assertEqual(len(CORE_SKILL_PACK), 17)


if __name__ == "__main__":
    unittest.main()

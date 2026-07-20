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

    def test_nested_vendor_skills_are_discovered_without_flattening_locations(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "skills"
            nested = root / "vendor" / "agent-skills" / "skills" / "security-and-hardening"
            nested.mkdir(parents=True)
            skill_file = nested / "SKILL.md"
            skill_file.write_text("---\nname: security-and-hardening\n---\n", encoding="utf-8")

            report = inspect_host_skills([root])

            self.assertIn("security-and-hardening", report["host_owned_or_external"])
            self.assertEqual(report["locations"]["security-and-hardening"], [str(skill_file)])

    def test_surveyed_capabilities_are_grouped_for_operator_visibility(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "skills"
            self._skill(root, "gitnexus-impact-analysis")
            self._skill(root, "wrangler")
            self._skill(root, "retrieval-reflex")

            report = inspect_host_skills([root])

            self.assertEqual(report["capability_groups"]["gitnexus"], ["gitnexus-impact-analysis"])
            self.assertEqual(report["capability_groups"]["cloudflare"], ["wrangler"])
            self.assertEqual(report["capability_groups"]["retrieval-and-memory"], ["retrieval-reflex"])

    def test_duplicate_skill_names_preserve_all_host_locations(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            first = base / "codex"
            second = base / "agents"
            self._skill(first, "qa")
            self._skill(second, "qa")

            report = inspect_host_skills([first, second])

            self.assertEqual(len(report["duplicate_skill_locations"]["qa"]), 2)
            self.assertEqual(len(report["locations"]["qa"]), 2)

    def test_optional_library_never_contains_manageroo_core(self):
        self.assertFalse(set(CORE_SKILL_PACK) & set(OPTIONAL_SKILL_PACK))
        self.assertEqual(len(CORE_SKILL_PACK), 18)


if __name__ == "__main__":
    unittest.main()

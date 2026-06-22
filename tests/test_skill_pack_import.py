import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from manageroo.cli import main
from manageroo.skill_pack import (
    import_skill_folder,
    reconcile_skill_pack,
    scan_skill_folder,
)


def _skill(path: Path, name: str, body: str = "Use when testing.\n") -> Path:
    skill_dir = path / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill {name}.\n---\n\n{body}",
        encoding="utf-8",
    )
    return skill_dir


class SkillPackImportTests(unittest.TestCase):
    def test_scan_classifies_importable_duplicate_and_existing_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "SKILLS"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            _skill(source, "new-skill")
            _skill(source, "dupe-skill", "first\n")
            nested = source / "nested"
            _skill(nested, "dupe-skill", "second\n")
            _skill(source, "existing-skill", "incoming\n")
            _skill(target, "existing-skill", "current\n")

            report = scan_skill_folder(source, skills_dir=target)
            by_name = {item["name"]: item for item in report["candidates"]}

            self.assertTrue(report["ok"])
            self.assertEqual(by_name["new-skill"]["status"], "importable")
            self.assertEqual(by_name["existing-skill"]["status"], "conflict")
            duplicates = [item for item in report["candidates"] if item["name"] == "dupe-skill"]
            self.assertEqual([item["status"] for item in duplicates], ["importable", "duplicate-source"])

    def test_import_is_dry_run_until_apply_and_backs_up_conflicts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "SKILLS"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            skill_dir = _skill(source, "existing-skill", "incoming\n")
            (skill_dir / "extra.txt").write_text("do not copy\n", encoding="utf-8")
            _skill(target, "existing-skill", "current\n")

            dry_run = import_skill_folder(source, skills_dir=target, apply=False)
            self.assertFalse(dry_run["applied"])
            self.assertIn("manageroo skills import", dry_run["next_command"])
            self.assertIn("current", (target / "existing-skill" / "SKILL.md").read_text(encoding="utf-8"))

            applied = import_skill_folder(source, skills_dir=target, apply=True)
            self.assertTrue(applied["applied"])
            self.assertEqual(applied["imported"][0]["name"], "existing-skill")
            self.assertTrue((target / "existing-skill" / "extra.txt").exists())
            self.assertIn("incoming", (target / "existing-skill" / "SKILL.md").read_text(encoding="utf-8"))
            backups = list((target / "existing-skill").glob("SKILL.md.manageroo-backup-*"))
            self.assertEqual(len(backups), 1)
            self.assertIn("current", backups[0].read_text(encoding="utf-8"))

    def test_reconcile_installs_bundled_pack_without_manual_copying(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "skills"

            report = reconcile_skill_pack(
                skills_dir=target,
                apply=True,
                scan_default_roots=False,
            )

            self.assertTrue(report["ok"])
            self.assertTrue(report["applied"])
            self.assertEqual(report["missing_bundled"], [])
            self.assertGreaterEqual(report["bundled_skill_count"], 40)
            self.assertTrue((target / "pimp-my-prompt" / "SKILL.md").exists())
            self.assertTrue((target / "playwright" / "references" / "cli.md").exists())

    def test_reconcile_reports_duplicate_skill_names_across_roots(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            source = root / "source"
            target.mkdir()
            source.mkdir()
            _skill(target, "dupe-skill", "target\n")
            _skill(source, "dupe-skill", "source\n")

            report = reconcile_skill_pack(
                sources=[source],
                skills_dir=target,
                apply=False,
                scan_default_roots=False,
            )

            self.assertEqual(report["duplicate_count"], 1)
            self.assertIn("dupe-skill", report["duplicates"])

    def test_reconcile_can_import_external_source_when_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            source = root / "source"
            target.mkdir()
            source.mkdir()
            extra = _skill(source, "external-skill", "external\n")
            (extra / "reference.md").write_text("keep support file\n", encoding="utf-8")

            report = reconcile_skill_pack(
                sources=[source],
                skills_dir=target,
                apply=True,
                include_external=True,
                scan_default_roots=False,
            )

            self.assertTrue(report["ok"])
            self.assertTrue((target / "external-skill" / "SKILL.md").exists())
            self.assertTrue((target / "external-skill" / "reference.md").exists())

    def test_scan_does_not_create_missing_target_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "SKILLS"
            target = Path(temp) / "missing-target"
            source.mkdir()
            _skill(source, "new-skill")

            report = scan_skill_folder(source, skills_dir=target)

            self.assertTrue(report["ok"])
            self.assertFalse(target.exists())

    def test_scan_accepts_existing_legacy_uppercase_skill_names(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "SKILLS"
            target = Path(temp) / "target"
            source.mkdir()
            target.mkdir()
            _skill(source, "Make-My-Ptich-Deck-Design-Not-Awful")

            report = scan_skill_folder(source, skills_dir=target)

            self.assertEqual(report["candidates"][0]["status"], "importable")

    def test_cli_skills_scan_outputs_json(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "SKILLS"
            target = Path(temp) / "target"
            source.mkdir()
            target.mkdir()
            _skill(source, "new-skill")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["skills", "scan", str(source), "--skills-dir", str(target), "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["candidates"][0]["name"], "new-skill")
            self.assertEqual(payload["candidates"][0]["status"], "importable")

    def test_cli_scan_text_limit_points_to_full_report(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "SKILLS"
            target = Path(temp) / "target"
            source.mkdir()
            target.mkdir()
            _skill(source, "first-skill")
            _skill(source, "second-skill")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["skills", "scan", str(source), "--skills-dir", str(target), "--limit", "1"])

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("1 more", output)
            self.assertIn("--json", output)

    def test_cli_skills_reconcile_outputs_json(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main([
                    "skills",
                    "reconcile",
                    "--skills-dir",
                    str(target),
                    "--apply",
                    "--no-default-roots",
                    "--json",
                ])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(payload["applied"])
            self.assertEqual(payload["missing_bundled"], [])


if __name__ == "__main__":
    unittest.main()

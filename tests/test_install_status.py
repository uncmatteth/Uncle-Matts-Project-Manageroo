import hashlib
import json
import os
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.install_status import (
    INSTALL_OWNERSHIP_MARKER,
    LAUNCHER_MARKER,
    LAUNCHER_MARKER,
    format_stack_status,
    launcher_is_manageroo_owned,
    read_install_lock,
    stack_status,
    summarize_external_tools,
    uninstall_plan,
)


def _launcher_text(prefix: Path = Path("/tmp/manageroo")) -> str:
    return (
        "#!/bin/sh\n"
        f"# {LAUNCHER_MARKER}\n"
        f"export PYTHONPATH={shlex.quote(str(prefix / 'app'))}${{PYTHONPATH:+:$PYTHONPATH}}\n"
        f"export MANAGEROO_PREFIX={shlex.quote(str(prefix))}\n"
        'exec python3 -m manageroo "$@"\n'
    )


def _write_owned_lock(prefix: Path, payload: dict) -> None:
    installation_id = "a" * 64
    marker = prefix / INSTALL_OWNERSHIP_MARKER
    marker.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product": "Uncle Matt's Project Manageroo",
                "prefix": str(prefix.resolve()),
                "installation_id": installation_id,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    lock = {"prefix": str(prefix.resolve()), **payload}
    lock["installation_ownership"] = {
        "schema_version": 1,
        "marker": INSTALL_OWNERSHIP_MARKER,
        "marker_sha256": hashlib.sha256(marker.read_bytes()).hexdigest(),
        "installation_id": installation_id,
    }
    (prefix / "install-lock.json").write_text(json.dumps(lock), encoding="utf-8")


def _legacy_tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        relative = path.relative_to(root)
        if any(part in {".git", ".venv", "__pycache__", "dist", "build"} for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_legacy_install(prefix: Path, launcher: Path) -> None:
    app = prefix / "app"
    python = prefix / "venv" / "bin" / "python"
    (app / "manageroo").mkdir(parents=True)
    python.parent.mkdir(parents=True)
    (prefix / "venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
    (app / "manageroo" / "__init__.py").write_text("VERSION = 'legacy'\n", encoding="utf-8")
    python.write_text("legacy python\n", encoding="utf-8")
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        "#!/bin/sh\n"
        f"# {LAUNCHER_MARKER}\n"
        f"export PYTHONPATH={shlex.quote(str(app))}${{PYTHONPATH:+:$PYTHONPATH}}\n"
        f"export MANAGEROO_PREFIX={shlex.quote(str(prefix))}\n"
        f"exec {shlex.quote(str(python))} -m manageroo \"$@\"\n",
        encoding="utf-8",
    )
    (prefix / "install-lock.json").write_text(
        json.dumps(
            {
                "product": "Uncle Matt's Project Manageroo",
                "prefix": str(prefix.resolve()),
                "launcher": str(launcher.resolve()),
                "installed_app_sha256": _legacy_tree_hash(app),
                "external_tools": [],
            }
        ),
        encoding="utf-8",
    )


class InstallStatusTests(unittest.TestCase):
    def test_stack_summary_keeps_next_commands_for_skipped_tools(self):
        summary = summarize_external_tools([
            {"name": "gbrain", "installed": True, "configured": True},
            {"name": "gitnexus", "skipped": True, "reason": "npm missing", "next_commands": ["Install Node.js", "npm install -g gitnexus"]},
        ])
        self.assertEqual(summary["counts"]["installed"], 1)
        self.assertEqual(summary["counts"]["skipped"], 1)
        self.assertTrue(summary["items"][1]["needs_action"])
        self.assertIn("npm install -g gitnexus", summary["items"][1]["next_commands"])

    def test_stack_summary_surfaces_guidance_commands(self):
        summary = summarize_external_tools([{"name": "gbrain", "installed": True, "configured": True, "guidance_commands": ["Connect `gbrain serve` to the selected agent."]}])
        self.assertEqual(summary["counts"]["needs_action"], 1)
        self.assertTrue(summary["items"][0]["needs_action"])
        self.assertIn("gbrain serve", summary["items"][0]["next_commands"][0])

    def test_format_stack_status_is_plain_and_actionable(self):
        text = format_stack_status({
            "ok": True,
            "lock_path": "/tmp/install-lock.json",
            "launcher": "/tmp/bin/manageroo",
            "stack_summary": {"items": [{"name": "obsidian", "installed": False, "needs_action": True, "reason": "No package manager available", "next_commands": ["Install Obsidian from https://obsidian.md/download"]}]},
        })
        self.assertIn("ACTION obsidian", text)
        self.assertIn("No package manager available", text)
        self.assertIn("obsidian.md", text)

    def test_malformed_lock_shapes_return_actionable_status_instead_of_crashing(self):
        payloads = [
            {"external_tools": None}, {"external_tools": {}}, {"external_tools": [None]},
            {"external_tools": [{"name": "x", "next_commands": None}]},
            {"external_tools": [{"name": "x", "guidance_commands": None}]},
            {"external_tools": [], "stack_summary": {"items": None}},
        ]
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "install-lock.json"
            for payload in payloads:
                with self.subTest(payload=payload):
                    lock.write_text(json.dumps(payload), encoding="utf-8")
                    loaded = read_install_lock(lock)
                    self.assertFalse(loaded["ok"])
                    report = stack_status(lock)
                    self.assertFalse(report["ok"])
                    rendered = format_stack_status(report)
                    self.assertIn("NOT READY", rendered)
                    self.assertIn("install-lock.json", rendered)
                    self.assertIn("next:", rendered)

    def test_live_probe_overrides_stale_cached_installed_status(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "install-lock.json"
            launcher_name = "manageroo.cmd" if os.name == "nt" else "manageroo"
            lock.write_text(json.dumps({
                "launcher": str(Path(temp).resolve() / "bin" / launcher_name),
                "external_tools": [{"name": "codex", "installed": True, "configured": True}],
                "stack_summary": {"items": [{"name": "codex", "installed": True, "configured": True, "skipped": False, "needs_action": False, "next_commands": []}]},
            }), encoding="utf-8")
            with patch("manageroo.install_status.shutil.which", return_value=None), patch("manageroo.install_status._find_skill", return_value=None):
                report = stack_status(lock)
            self.assertTrue(report["ok"])
            item = report["stack_summary"]["items"][0]
            self.assertFalse(item["installed"])
            self.assertTrue(item["needs_action"])
            self.assertIn("ACTION codex", format_stack_status(report))

    def test_live_probe_reconciles_unlisted_external_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "install-lock.json"
            missing_node = Path(temp).resolve() / "bin" / "node"
            lock.write_text(json.dumps({
                "external_tools": [{
                    "name": "node",
                    "installed": True,
                    "configured": True,
                    "path": str(missing_node),
                }],
            }), encoding="utf-8")
            with (
                patch("manageroo.install_status.shutil.which", return_value=None),
                patch("manageroo.install_status._find_skill", return_value=None),
            ):
                report = stack_status(lock)
            self.assertTrue(report["ok"])
            item = report["stack_summary"]["items"][0]
            self.assertFalse(item["installed"])
            self.assertIsNone(item["path"])
            self.assertTrue(item["needs_action"])

    def test_stack_status_exposes_recorded_source_provenance(self):
        provenance = {
            "schema_version": 1,
            "git_state_known": True,
            "git_commit": "c" * 40,
            "git_dirty": False,
            "source_tree_sha256": "d" * 64,
            "installed_app_sha256": "e" * 64,
        }
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "install-lock.json"
            lock.write_text(
                json.dumps({"external_tools": [], "source_provenance": provenance}),
                encoding="utf-8",
            )
            with (
                patch("manageroo.install_status.shutil.which", return_value=None),
                patch("manageroo.install_status._find_skill", return_value=None),
            ):
                report = stack_status(lock)

        self.assertTrue(report["ok"])
        self.assertEqual(report["source_provenance"], provenance)

    def test_uninstall_plan_uses_recorded_custom_launcher_not_default_bin(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            custom_launcher = root / "custom" / "manageroo"
            unrelated_default = Path.home() / ".local" / "bin" / "manageroo"
            prefix.mkdir()
            custom_launcher.parent.mkdir()
            custom_launcher.write_text(_launcher_text(prefix), encoding="utf-8")
            _write_owned_lock(prefix, {"launcher": str(custom_launcher), "external_tools": []})
            plan = uninstall_plan(prefix=prefix)
            self.assertFalse(plan["executes_deletions"])
            self.assertIn(str(custom_launcher), plan["core_paths"])
            self.assertNotIn(str(unrelated_default), plan["core_paths"])
            self.assertTrue(plan["launcher_ownership_known"])

    def test_uninstall_plan_excludes_launcher_owned_by_other_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            prefix_a = root / "prefix-a"
            prefix_b = root / "prefix-b"
            launcher_b = root / "bin-b" / "manageroo"
            prefix_a.mkdir()
            prefix_b.mkdir()
            launcher_b.parent.mkdir()
            launcher_b.write_text(_launcher_text(prefix_b), encoding="utf-8")
            _write_owned_lock(
                prefix_a,
                {"launcher": str(launcher_b), "external_tools": []},
            )

            plan = uninstall_plan(prefix=prefix_a)

            self.assertTrue(plan["prefix_ownership_known"])
            self.assertFalse(plan["launcher_ownership_known"])
            self.assertNotIn(str(launcher_b), plan["core_paths"])
            self.assertNotIn(str(launcher_b), "\n".join(plan["core_commands"]))

    def test_uninstall_plan_does_not_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp).resolve() / "prefix"
            prefix.mkdir()
            _write_owned_lock(prefix, {"external_tools": []})
            plan = uninstall_plan(prefix=prefix, bin_dir=Path(temp) / "bin")
            self.assertFalse(plan["executes_deletions"])
            self.assertIn(str(prefix), plan["core_paths"])

    @unittest.skipIf(os.name == "nt", "fixture uses the POSIX legacy launcher")
    def test_uninstall_plan_accepts_fully_verified_legacy_install_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            prefix = root / "prefix"
            launcher = root / "bin" / "manageroo"
            prefix.mkdir()
            _write_legacy_install(prefix, launcher)

            plan = uninstall_plan(prefix=prefix)

            self.assertTrue(plan["prefix_ownership_known"], plan)
            self.assertEqual(plan["ownership_proof"], "verified-legacy")
            self.assertIn(str(prefix), plan["core_paths"])

            (prefix / "app" / "manageroo" / "__init__.py").write_text(
                "tampered\n", encoding="utf-8"
            )
            tampered = uninstall_plan(prefix=prefix)
            self.assertFalse(tampered["prefix_ownership_known"])

    def test_uninstall_plan_refuses_dangerous_and_unverified_prefixes(self):
        with tempfile.TemporaryDirectory() as temp:
            unrelated = Path(temp) / "unrelated"
            unrelated.mkdir()
            unsafe_prefixes = [
                Path.home(),
                Path(Path.cwd().anchor),
                Path("."),
                Path.cwd(),
                unrelated,
            ]
            for prefix in unsafe_prefixes:
                with self.subTest(prefix=prefix):
                    plan = uninstall_plan(prefix=prefix)
                    self.assertFalse(plan["prefix_ownership_known"])
                    self.assertEqual(plan["core_paths"], [])
                    self.assertEqual(plan["core_commands"], [])
                    self.assertTrue(plan["prefix_error"])

    def test_uninstall_plan_refuses_owned_prefix_containing_current_working_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            child = prefix / "child"
            child.mkdir(parents=True)
            _write_owned_lock(prefix, {"external_tools": []})
            original_cwd = Path.cwd()
            try:
                os.chdir(child)
                plan = uninstall_plan(prefix=prefix)
            finally:
                os.chdir(original_cwd)

            self.assertFalse(plan["prefix_ownership_known"])
            self.assertEqual(plan["core_paths"], [])
            self.assertEqual(plan["core_commands"], [])
            self.assertTrue(plan["prefix_error"])

    def test_uninstall_plan_includes_only_lock_proven_manageroo_owned_trufflehog(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            prefix = root / "prefix"
            bin_dir = root / "bin"
            prefix.mkdir()
            bin_dir.mkdir()
            launcher = bin_dir / "manageroo"
            launcher.write_text(_launcher_text(prefix), encoding="utf-8")
            trufflehog = bin_dir / "trufflehog"
            trufflehog.write_bytes(b"binary")
            _write_owned_lock(prefix, {
                "launcher": str(launcher),
                "external_tools": [{"name": "trufflehog", "path": str(trufflehog), "manageroo_owned": True}],
            })
            plan = uninstall_plan(prefix=prefix)
            self.assertIn(str(trufflehog), plan["manageroo_owned_external_paths"])
            self.assertIn(str(trufflehog), plan["core_paths"])

            outside = root / "outside" / "trufflehog"
            outside.parent.mkdir()
            outside.write_bytes(b"user binary")
            _write_owned_lock(prefix, {
                "launcher": str(launcher),
                "external_tools": [{"name": "trufflehog", "path": str(outside), "manageroo_owned": True}],
            })
            plan = uninstall_plan(prefix=prefix)
            self.assertNotIn(str(outside), plan["manageroo_owned_external_paths"])

    def test_launcher_ownership_requires_marker_and_complete_structure(self):
        with tempfile.TemporaryDirectory() as temp:
            launcher = Path(temp) / "manageroo"
            launcher.write_text(_launcher_text(), encoding="utf-8")
            self.assertTrue(launcher_is_manageroo_owned(launcher))

            unrelated_launchers = (
                "#!/bin/sh\n# MANAGEROO_PREFIX\n# -m manageroo\necho unrelated\n",
                (
                    "#!/bin/sh\n"
                    f"# {LAUNCHER_MARKER}\n"
                    "# MANAGEROO_PREFIX\n"
                    "# -m manageroo\n"
                    "echo unrelated\n"
                ),
                _launcher_text() + "echo unrelated\n",
            )
            for text in unrelated_launchers:
                with self.subTest(text=text):
                    launcher.write_text(text, encoding="utf-8")
                    self.assertFalse(launcher_is_manageroo_owned(launcher))

    def test_uninstall_plan_excludes_unrelated_launcher_with_ownership_substrings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prefix = root / "prefix"
            launcher = root / "bin" / "manageroo"
            prefix.mkdir()
            launcher.parent.mkdir()
            launcher.write_text(
                "#!/bin/sh\n# MANAGEROO_PREFIX\n# -m manageroo\necho unrelated\n",
                encoding="utf-8",
            )
            _write_owned_lock(prefix, {"launcher": str(launcher), "external_tools": []})
            plan = uninstall_plan(prefix=prefix)
            self.assertFalse(plan["launcher_ownership_known"])
            self.assertNotIn(str(launcher), plan["core_paths"])
            self.assertNotIn(str(launcher), "\n".join(plan["core_commands"]))

    def test_uninstall_plan_rejects_forgeable_python_layout_without_bound_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "unrelated-python"
            (prefix / "app" / "manageroo").mkdir(parents=True)
            (prefix / "venv").mkdir()
            (prefix / "app" / "manageroo" / "__init__.py").write_text("", encoding="utf-8")
            (prefix / "venv" / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")
            (prefix / "install-lock.json").write_text(
                json.dumps({"prefix": str(prefix), "external_tools": []}),
                encoding="utf-8",
            )

            plan = uninstall_plan(prefix=prefix)

            self.assertFalse(plan["prefix_ownership_known"])
            self.assertEqual(plan["core_commands"], [])
            self.assertIn("cryptographically bound", plan["prefix_error"])

    def test_uninstall_plan_fails_closed_on_invalid_marker_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / "prefix"
            prefix.mkdir()
            _write_owned_lock(prefix, {"external_tools": []})
            marker = prefix / INSTALL_OWNERSHIP_MARKER
            payload = json.loads(marker.read_text(encoding="utf-8"))
            payload["prefix"] = "invalid\u0000prefix"
            marker.write_text(json.dumps(payload), encoding="utf-8")
            lock_path = prefix / "install-lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            lock["installation_ownership"]["marker_sha256"] = hashlib.sha256(
                marker.read_bytes()
            ).hexdigest()
            lock_path.write_text(json.dumps(lock), encoding="utf-8")

            plan = uninstall_plan(prefix=prefix)

            self.assertFalse(plan["prefix_ownership_known"])
            self.assertEqual(plan["core_commands"], [])


if __name__ == "__main__":
    unittest.main()

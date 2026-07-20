import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from manageroo.cli import main
from manageroo.intent_lock import (
    audit_compaction_text,
    capture_intent_lock,
    format_compaction_audit,
    intent_lock_path,
)

ROOT = Path(__file__).resolve().parents[1]


class IntentLockTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "product"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "README.md").write_text("# Product\n", encoding="utf-8")
        return repo

    def test_capture_writes_machine_and_human_intent_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            result = capture_intent_lock(
                repo,
                want="Build the release helper without pretending it deploys.",
                outcomes=["Writes a release handoff"],
                must_not=["Do not deploy production"],
                proof=["release-ready reports READY"],
                corrections=["The command name is manageroo"],
                rejected=["Do not add GitHub Actions"],
                questions=["Which deployment target should the operator use?"],
                scopes=["Only this Git repo"],
                source="operator-chat",
            )

            self.assertTrue(result["ok"])
            lock = intent_lock_path(repo)
            self.assertTrue(lock.is_file())
            payload = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(payload["want"], "Build the release helper without pretending it deploys.")
            self.assertIn("Do not deploy production", payload["must_not"])
            self.assertIn("Do not add GitHub Actions", payload["rejected"])
            markdown = lock.with_suffix(".md").read_text(encoding="utf-8")
            self.assertIn("## Must Not Happen", markdown)
            self.assertIn("Do not deploy production", markdown)
            self.assertIn("## Rejected Ideas", markdown)

    def test_audit_blocks_when_compaction_drops_must_not_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(
                repo,
                want="Build the release helper.",
                must_not=["Do not deploy production"],
                rejected=["Do not add GitHub Actions"],
                proof=["release-ready reports READY"],
                scopes=["Only this Git repo"],
            )

            report = audit_compaction_text(
                repo,
                "Current task: build the release helper. Proof: release-ready reports READY.",
            )

            self.assertFalse(report["ok"])
            self.assertEqual(report["status"], "blocked")
            missing = {(item["category"], item["text"]) for item in report["missing"]}
            self.assertIn(("must_not", "Do not deploy production"), missing)
            self.assertIn(("rejected", "Do not add GitHub Actions"), missing)

    def test_audit_passes_when_pinned_truth_survives(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            capture_intent_lock(
                repo,
                want="Build the release helper.",
                outcomes=["Writes a release handoff"],
                must_not=["Do not deploy production"],
                proof=["release-ready reports READY"],
                corrections=["The command name is manageroo"],
            )
            report = audit_compaction_text(
                repo,
                "\n".join(
                    [
                        "Intent: Build the release helper.",
                        "Outcome: Writes a release handoff.",
                        "Must not: Do not deploy production.",
                        "Proof: release-ready reports READY.",
                        "Correction: The command name is manageroo.",
                    ]
                ),
            )

            self.assertTrue(report["ok"], report)
            self.assertEqual(report["status"], "passed")
            self.assertFalse(report["missing"])

    def test_cli_capture_and_compact_audit_json(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = self._repo(Path(temp))
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "intent",
                        "capture",
                        str(repo),
                        "--want",
                        "Build the release helper.",
                        "--must-not",
                        "Do not deploy production",
                        "--proof",
                        "release-ready reports READY",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(stdout.getvalue())["ok"])

            summary = repo / "summary.md"
            summary.write_text(
                "Intent: Build the release helper.\n"
                "Must not: Do not deploy production.\n"
                "Proof: release-ready reports READY.\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(["compact", "audit", str(repo), "--summary", str(summary), "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary_path"], str(summary.resolve()))

    def test_format_compaction_audit_is_plain_about_blockers(self):
        text = format_compaction_audit(
            {
                "ok": False,
                "status": "blocked",
                "lock_path": "/repo/.manageroo/intent/INTENT-LOCK.json",
                "missing": [{"category": "must_not", "text": "Do not deploy production"}],
                "warnings": [{"code": "confidence_claim", "text": "perfect"}],
                "next_command": "manageroo intent show",
            }
        )
        self.assertIn("COMPACTION AUDIT: BLOCKED", text)
        self.assertIn("MISSING must_not: Do not deploy production", text)
        self.assertIn("WARNING confidence_claim: perfect", text)
        self.assertIn("Next: manageroo intent show", text)

    def test_public_docs_explain_intent_lock_and_compaction_audit(self):
        surfaces = {
            "README.md": [
                ".manageroo/intent/INTENT-LOCK.md",
                "manageroo compact audit",
                "remain unknown unless matching evidence exists",
            ],
            "docs/CONTEXT_COMPILER.md": [
                "Chat compaction is not the source of truth",
                "strict phrase-preservation audit",
            ],
            "docs/ENFORCEMENT_MATRIX.md": [
                "Compaction cannot drop must-not rules",
                "Intent lock plus compaction audit",
            ],
            "docs/SOLO_OPERATOR_MODE.md": [
                "solo captures an intent lock",
                "compact audit",
            ],
        }
        for relative, phrases in surfaces.items():
            text = (ROOT / relative).read_text(encoding="utf-8").lower()
            for phrase in phrases:
                with self.subTest(surface=relative, phrase=phrase):
                    self.assertIn(phrase.lower(), text)


if __name__ == "__main__":
    unittest.main()

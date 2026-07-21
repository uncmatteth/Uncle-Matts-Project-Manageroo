import importlib.util
import io
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _compact(text: str) -> str:
    return " ".join(text.split())


def _fixture(codes: list[int]) -> str:
    return "".join(chr(code) for code in codes)


def _load_installer_module():
    spec = importlib.util.spec_from_file_location("manageroo_install_script", ROOT / "scripts" / "install.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _claim_is_explicitly_denied(sentence: str, phrase: str) -> bool:
    before = sentence.lower().split(phrase.lower(), 1)[0]
    denial_patterns = (r"\bdoes\s+not\b", r"\bcannot\b", r"\bnever\b", r"\bmust\s+not\b", r"\bnot\b", r"\bno\b", r"\bwithout\b", r"\binstead\s+of\b")
    return any(re.search(pattern, before) for pattern in denial_patterns)


def _sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+|\n+", text) if sentence.strip()]


class TruthContractTests(unittest.TestCase):
    def assertContainsAll(self, text: str, required: list[str], surface: str):
        compact_text = _compact(text)
        for phrase in required:
            with self.subTest(surface=surface, phrase=phrase):
                self.assertIn(_compact(phrase), compact_text)

    def test_limitations_lock_truthful_boundaries(self):
        self.assertContainsAll(_read("docs/LIMITATIONS.md"), [
            "Passing tests only proves what the tests and runtime demonstrations cover.",
            "it does not perform real vision interpretation or design understanding",
            "Exact edits still require bounded line ranges",
            "require local configuration and are not silently installed",
            "does not ask the AI repairer to freehand fixes from their findings",
            "`release-ready` is a final operator gate, not a deployment tool",
            "It does not push, deploy, monitor, or roll back production.",
            "does not run cloud schedules or timer loops by itself",
            "does not silently edit skills, docs, config, installer behavior, checks, prompts, or code",
            "`run --continue <run-id>` continues Manageroo's saved worker job queue",
        ], "docs/LIMITATIONS.md")

    def test_public_docs_and_installer_explain_lanes_without_pretending(self):
        surfaces = {
            "README.md": [
                "It does not get to certify its own work",
                "These integrations add capabilities. They do not become the authority over Manageroo completion",
                "remain unproven until matching evidence exists",
            ],
            "docs/00_START_HERE.md": [
                "The controller, not the worker, decides whether the job is complete",
                "external durable knowledge and retrieval",
                "They do not replace Manageroo's controller authority",
            ],
            "docs/INSTALLATION.md": [
                "They do not become authorities over Manageroo completion",
                "The updater does not use absence as permission to install every optional component",
                "An AI or IDE agent can assist, but it should surface meaningful installer choices",
            ],
            "docs/DOCUMENT_LANE.md": [
                "Failure is optional context", "pretend it understood images", "Media metadata is not vision",
                "readiness blocks until `document_analysis_command` is configured", "readiness prints `WARN document/prose lane` and still allows the run",
            ],
            "docs/EXTERNAL_INTEGRATIONS.md": [
                "Retrieved evidence is context only and cannot authorize edits, approve review, pass gates, or mark a run `COMPLETE`",
                "AUTOREVIEW findings do not become unconstrained freehand AI repair prompts",
                "Clawpatch findings remain command-owned", "Manageroo must not hand them to a worker for unconstrained freehand repair",
            ],
            "docs/ARCHITECTURE.md": [
                "Manageroo makes remembering unnecessary", "Manageroo does not run parallel implementation branches against the same files",
                "Core acceptance still belongs to Manageroo's state, scope, gates, and evidence", "These systems are capabilities, not completion authorities",
            ],
            "docs/STATELESS_ORCHESTRATION.md": [
                'Manageroo is not "AI remembers better."', "Manageroo makes remembering unnecessary.", "The controller saves the truth.",
                "Each AI worker gets one complete assignment.", "throws that worker away and starts a clean one from saved facts",
            ],
        }
        for surface, required in surfaces.items():
            self.assertContainsAll(_read(surface), required, surface)

        installer = _load_installer_module(); output = io.StringIO()
        with redirect_stdout(output): installer.print_lane_explainer()
        self.assertContainsAll(output.getvalue(), [
            "How Manageroo fits together", "Manageroo owns run truth", "GitNexus is first-class recommended repository intelligence",
            "GBrain is an external durable knowledge lane", "AUTOREVIEW and Clawpatch are command-owned review/repair lanes",
            "Host skills may be used when relevant but remain host-owned",
        ], "scripts/install.py print_lane_explainer")

    def test_runtime_prompts_keep_agents_from_pretending(self):
        surfaces = {
            "src/manageroo/project.py": ["claim completion without a `COMPLETE` controller state", "pretend media metadata is real vision"],
            "src/manageroo/orchestrator.py": ["not handed to the AI as a freehand long-document repair prompt", "The controller must not freehand fixes from their findings", '"ai_freehand_repair_allowed": False', "not full OCR or vision interpretation"],
            "src/manageroo/report.py": ["AI freehand repair from AUTOREVIEW/Clawpatch findings: no"],
            "src/manageroo/assets/skills/uncle-matts-project-manageroo/SKILL.md": ["Do not claim global completion", "Only the controller may mark a run `COMPLETE`", "Do not convert their findings into untracked AI freehand fixes", "Completion requires Manageroo-owned scope checks, real gates, review, acceptance evidence, and the final report"],
        }
        for surface, required in surfaces.items(): self.assertContainsAll(_read(surface), required, surface)

    def test_release_validation_keeps_truth_contract_in_the_package_gate(self):
        self.assertContainsAll(_read("scripts/verify_release.py"), [
            '"docs/LIMITATIONS.md"', '"tests/test_truth_contract.py"', '"truth:no-real-vision-claim"', '"truth:no-fake-subagent-claim"',
            '"truth:no-ai-freehand-external-repair"', '"truth:no-release-ready-deploy-claim"', '"truth:no-silent-self-mutation"', '"truth:stateless-worker-orchestration"',
        ], "scripts/verify_release.py")

    def test_public_markdown_avoids_specific_overclaim_phrases(self):
        public_files = ["README.md", "docs/00_START_HERE.md", "docs/INSTALLATION.md", "docs/LIMITATIONS.md", "docs/ARCHITECTURE.md", "docs/DOCUMENT_LANE.md", "docs/EXTERNAL_INTEGRATIONS.md", "docs/REVIEW_REPAIR_LANES.md", "docs/SOLO_OPERATOR_MODE.md", "docs/STATELESS_ORCHESTRATION.md"]
        banned_phrases = ["full vision support", "real vision support", "understands screenshots", "understands images", "guaranteed production ready", "one-button production deploy", "autonomous production deploy", "real subagent swarm", "parallel implementation branches", "ai can fix autoreview findings", "ai can fix clawpatch findings", "silently self-improves"]
        for surface in public_files:
            sentences = _sentences(_read(surface).lower())
            for phrase in banned_phrases:
                with self.subTest(surface=surface, phrase=phrase):
                    offenders = [sentence for sentence in sentences if phrase in sentence and not _claim_is_explicitly_denied(sentence, phrase)]
                    self.assertEqual(offenders, [])

    def test_overclaim_guard_rejects_unrelated_nearby_negation(self):
        text = "This is not experimental. Manageroo has full vision support."
        offenders = [sentence for sentence in _sentences(text) if "full vision support" in sentence.lower() and not _claim_is_explicitly_denied(sentence, "full vision support")]
        self.assertEqual(offenders, ["Manageroo has full vision support."])
        self.assertTrue(_claim_is_explicitly_denied("Manageroo does not provide full vision support.", "full vision support"))

    def test_project_manageroo_rename_has_no_old_public_brand_surface(self):
        old_title = _fixture([85,110,99,108,101,32,77,97,116,116,39,115,32,83,117,112,101,114,32,77,101,103,97,32,70,111,114,119,97,114,100,32,66,117,105,108,100,32,85,108,116,105,109,97,116,101,32,82,101,109,105,120,32,65,108,108,45,83,116,97,114,32,66,111,111,116,121,32,111,102,32,70,105,114,101,32,69,100,105,116,105,111,110])
        old_short = _fixture([83,117,112,101,114,32,77,101,103,97,32,70,111,114,119,97,114,100,32,66,117,105,108,100])
        old_acronym = _fixture([85,77,83,77,70,66,85,82,65,83,66,79,70,69])
        old_command = _fixture([117,109,115,109,102,98,117,114,97,115,98,111,102,101])
        old_slug = _fixture([117,110,99,108,101,45,109,97,116,116,115,45,115,117,112,101,114,45,109,101,103,97,45,102,111,114,119,97,114,100,45,98,117,105,108,100,45,117,108,116,105,109,97,116,101,45,114,101,109,105,120,45,97,108,108,45,115,116,97,114,45,98,111,111,116,121,45,111,102,45,102,105,114,101,45,101,100,105,116,105,111,110])
        banned = [old_title, old_short, old_acronym, old_command, old_slug, "." + old_command]
        for root in ["README.md", "LOCAL_SETUP.md", "GITHUB_DESCRIPTION.md", "GIVE-THIS-TO-YOUR-IDE-AGENT.md", "PUBLISH_TO_GITHUB.md", "pyproject.toml", "scripts", "src", "docs"]:
            path = ROOT / root
            files = [path] if path.is_file() else sorted(item for item in path.rglob("*") if item.is_file())
            for file_path in files:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                for phrase in banned:
                    with self.subTest(file=str(file_path), phrase=phrase): self.assertNotIn(phrase, text)


if __name__ == "__main__":
    unittest.main()

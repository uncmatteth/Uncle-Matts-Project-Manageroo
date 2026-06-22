import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _compact(text: str) -> str:
    return " ".join(text.split())


def _load_installer_module():
    spec = importlib.util.spec_from_file_location(
        "umsmfburasbofe_install_script",
        ROOT / "scripts" / "install.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TruthContractTests(unittest.TestCase):
    def assertContainsAll(self, text: str, required: list[str], surface: str):
        compact_text = _compact(text)
        for phrase in required:
            with self.subTest(surface=surface, phrase=phrase):
                self.assertIn(_compact(phrase), compact_text)

    def test_limitations_lock_truthful_boundaries(self):
        limitations = _read("docs/LIMITATIONS.md")
        self.assertContainsAll(
            limitations,
            [
                "Passing tests only proves what the tests and runtime demonstrations cover.",
                "it does not perform real vision interpretation or design understanding",
                "Exact edits still require bounded line ranges",
                "require local configuration and are not silently installed",
                "does not ask the AI repairer to freehand fixes from their findings",
                "`release-ready` is a final operator gate, not a deployment tool",
                "It does not push, deploy, monitor, or roll back production.",
                "does not run cloud schedules or timer loops by itself",
                "does not silently edit skills, docs, config, installer behavior, checks, prompts, or code",
            ],
            "docs/LIMITATIONS.md",
        )

    def test_public_docs_and_installer_explain_lanes_without_pretending(self):
        surfaces = {
            "README.md": [
                "blocks until `document_analysis_command` is configured",
                "pretend metadata is real visual understanding",
                "AUTOREVIEW and Clawpatch for command-owned review and repair lanes",
            ],
            "docs/00_START_HERE.md": [
                "`ready` blocks when the brief explicitly asks for a missing lane",
                "Passive document/media files in the repo show as `WARN`, not a block",
            ],
            "docs/INSTALLATION.md": [
                "map GBrain sources before the run starts",
                "configure `document_analysis_command` first",
                "readiness prints `WARN` but does not block",
                "The AI must not freehand fixes from them",
            ],
            "docs/DOCUMENT_LANE.md": [
                "Failure is optional context",
                "pretend it understood images",
                "Media metadata is not vision",
            ],
            "docs/EXTERNAL_INTEGRATIONS.md": [
                "does not give the AI permission to freehand",
                "pretend file metadata is real visual understanding",
                "The controller must not freehand fixes from AUTOREVIEW or Clawpatch findings",
            ],
            "docs/ARCHITECTURE.md": [
                "implementation prioritizes correctness over theatrical agent count",
                "The controller does not run parallel implementation branches against the same files",
                "Core acceptance still belongs to UMSMFBURASBOFE's state, scope, gates, and evidence",
            ],
        }
        for surface, required in surfaces.items():
            self.assertContainsAll(_read(surface), required, surface)

        installer = _load_installer_module()
        output = io.StringIO()
        with redirect_stdout(output):
            installer.print_lane_explainer()
        self.assertContainsAll(
            output.getvalue(),
            [
                "Lane readiness, plain English:",
                "Memory lane",
                "Document/prose lane",
                "ready prints WARN but does not block",
                "AI must not freehand fixes from them",
            ],
            "scripts/install.py print_lane_explainer",
        )

    def test_runtime_prompts_keep_agents_from_pretending(self):
        surfaces = {
            "src/umsmfburasbofe/project.py": [
                "claim completion without a `COMPLETE` controller state",
                "pretend media metadata is real vision",
            ],
            "src/umsmfburasbofe/orchestrator.py": [
                "not handed to the AI as a freehand long-document repair prompt",
                "The controller must not freehand fixes from their findings",
                '"ai_freehand_repair_allowed": False',
                "not full OCR or vision interpretation",
            ],
            "src/umsmfburasbofe/report.py": [
                "AI freehand repair from AUTOREVIEW/Clawpatch findings: no",
            ],
            (
                "src/umsmfburasbofe/assets/skills/"
                "uncle-matts-super-mega-forward-build-ultimate-remix-all-star-booty-of-fire-edition/"
                "SKILL.md"
            ): [
                "Do not claim global completion",
                "Only the controller may mark a run `COMPLETE`",
                "The AI agent must not freehand fixes from AUTOREVIEW or Clawpatch findings",
                "Completion requires scope checks, real gates, review, product proof, and the final report",
            ],
        }
        for surface, required in surfaces.items():
            self.assertContainsAll(_read(surface), required, surface)

    def test_release_validation_keeps_truth_contract_in_the_package_gate(self):
        verifier = _read("scripts/verify_release.py")
        self.assertContainsAll(
            verifier,
            [
                '"docs/LIMITATIONS.md"',
                '"tests/test_truth_contract.py"',
                '"truth:no-real-vision-claim"',
                '"truth:no-fake-subagent-claim"',
                '"truth:no-ai-freehand-external-repair"',
                '"truth:no-release-ready-deploy-claim"',
                '"truth:no-silent-self-mutation"',
            ],
            "scripts/verify_release.py",
        )

    def test_public_markdown_avoids_specific_overclaim_phrases(self):
        public_files = [
            "README.md",
            "docs/00_START_HERE.md",
            "docs/INSTALLATION.md",
            "docs/LIMITATIONS.md",
            "docs/ARCHITECTURE.md",
            "docs/DOCUMENT_LANE.md",
            "docs/EXTERNAL_INTEGRATIONS.md",
            "docs/REVIEW_REPAIR_LANES.md",
            "docs/SOLO_OPERATOR_MODE.md",
        ]
        banned_phrases = [
            "full vision support",
            "real vision support",
            "understands screenshots",
            "understands images",
            "guaranteed production ready",
            "one-button production deploy",
            "autonomous production deploy",
            "real subagent swarm",
            "parallel implementation branches",
            "ai can fix autoreview findings",
            "ai can fix clawpatch findings",
            "silently self-improves",
        ]
        boundary_words = (
            "not ",
            "does not",
            "cannot",
            "never",
            "must not",
            "without",
            "instead of",
        )
        for surface in public_files:
            lines = _read(surface).lower().splitlines()
            for phrase in banned_phrases:
                with self.subTest(surface=surface, phrase=phrase):
                    offenders = []
                    for index, line in enumerate(lines):
                        if phrase not in line:
                            continue
                        context = ((lines[index - 1] if index else "") + " " + line).strip()
                        if not any(word in context for word in boundary_words):
                            offenders.append(context)
                    self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()

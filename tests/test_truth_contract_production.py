import unittest
from pathlib import Path

from manageroo.truth_contract import claim_is_explicitly_denied, find_overclaim_offenders


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    "README.md",
    "docs/00_START_HERE.md",
    "docs/INSTALLATION.md",
    "docs/LIMITATIONS.md",
    "docs/ARCHITECTURE.md",
    "docs/DOCUMENT_LANE.md",
    "docs/EXTERNAL_INTEGRATIONS.md",
    "docs/REVIEW_REPAIR_LANES.md",
    "docs/SOLO_OPERATOR_MODE.md",
    "docs/STATELESS_ORCHESTRATION.md",
)
BANNED_PHRASES = (
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
)


class ProductionTruthContractTests(unittest.TestCase):
    def test_public_markdown_has_no_unnegated_overclaims(self):
        for relative in PUBLIC_FILES:
            with self.subTest(relative=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertEqual(find_overclaim_offenders(text, BANNED_PHRASES), [])

    def test_unrelated_negation_does_not_hide_a_later_claim(self):
        cases = (
            ("This is not experimental. Manageroo has full vision support.", "full vision support"),
            ("No setup is required; Manageroo has full vision support.", "full vision support"),
            ("This works without configuration, and it understands images.", "understands images"),
        )
        for text, phrase in cases:
            with self.subTest(text=text):
                offenders = find_overclaim_offenders(text, [phrase])
                self.assertEqual(len(offenders), 1)
                self.assertEqual(offenders[0]["phrase"], phrase)

    def test_direct_denial_is_accepted(self):
        sentence = "Manageroo does not provide full vision support."
        self.assertTrue(claim_is_explicitly_denied(sentence, "full vision support"))
        self.assertEqual(find_overclaim_offenders(sentence, ["full vision support"]), [])


if __name__ == "__main__":
    unittest.main()

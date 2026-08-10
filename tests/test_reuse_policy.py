import unittest

from manageroo.reuse_policy import operator_reuse_findings, reuse_binding_findings


class ReusePolicyTests(unittest.TestCase):
    def test_operator_named_finished_source_cannot_be_reclassified_as_custom_build(self):
        brief = (
            "Use the finished animations already in tools/swipebot_motion.py at commit "
            "722296ca86cfeeef23d53eb72edbfa629c412960; do not redraw them."
        )
        findings = operator_reuse_findings(
            brief=brief,
            reuse={
                "decisions": [
                    {
                        "need": "animations",
                        "decision": "build-custom",
                        "candidate": "new Kotlin renderer",
                        "evidence": [],
                    }
                ]
            },
        )
        self.assertTrue(any(item["id"].startswith("OPERATOR-REUSE") for item in findings))

    def test_operator_reuse_directive_requires_exact_evidence_and_reuse_decision(self):
        directive = "Copy the existing renderer from tools/swipebot_motion.py."
        findings = operator_reuse_findings(
            brief=directive,
            reuse={
                "decisions": [
                    {
                        "need": "renderer",
                        "decision": "reuse-internal",
                        "candidate": "tools/swipebot_motion.py",
                        "evidence": [directive],
                    }
                ]
            },
        )
        self.assertEqual(findings, [])

    def test_reuse_decision_cannot_be_replaced_by_custom_implementation(self):
        findings = reuse_binding_findings(
            reuse={
                "decisions": [
                    {
                        "need": "final animations",
                        "decision": "reuse-internal",
                        "candidate": "tools/swipebot_motion.py at 722296ca",
                    }
                ]
            },
            plan={
                "reuse_bindings": [
                    {
                        "need": "final animations",
                        "decision": "reuse-internal",
                        "candidate": "tools/swipebot_motion.py at 722296ca",
                        "implementation": "build-custom",
                        "deviation": "",
                    }
                ]
            },
        )
        self.assertTrue(any(item["id"].startswith("REUSE-METHOD") for item in findings))

    def test_undeclared_or_declared_substitution_blocks_reuse_plan(self):
        reuse = {
            "decisions": [
                {
                    "need": "final animations",
                    "decision": "reuse-internal",
                    "candidate": "tools/swipebot_motion.py",
                }
            ]
        }
        missing = reuse_binding_findings(reuse=reuse, plan={"reuse_bindings": []})
        substituted = reuse_binding_findings(
            reuse=reuse,
            plan={
                "reuse_bindings": [
                    {
                        "need": "final animations",
                        "decision": "reuse-internal",
                        "candidate": "tools/swipebot_motion.py",
                        "implementation": "adapt-existing",
                        "deviation": "Use a simpler Kotlin drawing instead.",
                    }
                ]
            },
        )
        self.assertTrue(any(item["id"].startswith("REUSE-BINDING") for item in missing))
        self.assertTrue(any(item["id"].startswith("REUSE-DEVIATION") for item in substituted))

    def test_exact_reuse_binding_passes(self):
        findings = reuse_binding_findings(
            reuse={
                "decisions": [
                    {
                        "need": "final animations",
                        "decision": "reuse-internal",
                        "candidate": "tools/swipebot_motion.py",
                    }
                ]
            },
            plan={
                "reuse_bindings": [
                    {
                        "need": "final animations",
                        "decision": "reuse-internal",
                        "candidate": "tools/swipebot_motion.py",
                        "implementation": "reuse-as-is",
                        "deviation": "",
                    }
                ]
            },
        )
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()

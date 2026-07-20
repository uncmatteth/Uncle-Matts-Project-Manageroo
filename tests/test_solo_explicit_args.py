import unittest
from pathlib import Path

from manageroo.wizards import collect_solo_answers


class SoloExplicitArgumentTests(unittest.TestCase):
    def test_explicit_want_uses_safe_defaults_without_prompting(self):
        def fail_input(_prompt: str) -> str:
            raise AssertionError("explicit solo arguments must not prompt for stdin")

        answers = collect_solo_answers(
            repo="/tmp/project",
            agent="mock",
            want="Repair login",
            audience="",
            outcomes=["Login works"],
            must_not=["Do not change exports"],
            proof=["Run login tests"],
            stop="",
            later=[],
            mode="repair",
            run=None,
            integrations={"gbrain": False, "gitnexus": False, "obsidian": False},
            interactive=True,
            input_fn=fail_input,
            output_fn=None,
        )

        self.assertEqual(answers["repo"], Path("/tmp/project"))
        self.assertEqual(answers["want"], "Repair login")
        self.assertEqual(answers["audience"], "The people or systems that use this repo.")
        self.assertEqual(answers["stop"], "Stop after two failed repair passes and report the blocker.")
        self.assertFalse(answers["run"])


if __name__ == "__main__":
    unittest.main()

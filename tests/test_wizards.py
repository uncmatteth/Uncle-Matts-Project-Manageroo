import unittest
from pathlib import Path

from umsmfburasbofe.wizards import collect_gbrain_answers, collect_setup_answers, collect_solo_answers


def input_from(values):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


class WizardTests(unittest.TestCase):
    def test_setup_answers_prompt_for_agent_repo_and_stack_choices(self):
        messages: list[str] = []
        answers = collect_setup_answers(
            repo=None,
            agent=None,
            interactive=True,
            input_fn=input_from(["gemini", "/tmp/product", "y", "n", "y", "n"]),
            output_fn=messages.append,
        )
        self.assertEqual(answers["agent"], "gemini")
        self.assertEqual(answers["repo"], Path("/tmp/product"))
        self.assertEqual(
            answers["integrations"],
            {
                "gbrain": True,
                "gitnexus": False,
                "obsidian": True,
                "loop_library": False,
            },
        )
        self.assertTrue(any("What AI" in message for message in messages))

    def test_setup_answers_noninteractive_defaults_are_safe(self):
        answers = collect_setup_answers(repo=None, agent=None, interactive=False)
        self.assertEqual(answers["agent"], "codex")
        self.assertEqual(answers["repo"], Path("."))
        self.assertFalse(any(answers["integrations"].values()))

    def test_solo_answers_collect_human_build_request(self):
        messages: list[str] = []
        answers = collect_solo_answers(
            repo=None,
            agent=None,
            want="",
            audience="",
            outcomes=[],
            must_not=[],
            proof=[],
            stop="",
            later=[],
            mode="build",
            run=None,
            integrations={"gbrain": False, "gitnexus": False, "obsidian": False, "loop_library": False},
            interactive=True,
            input_fn=input_from(
                [
                    "mock",
                    "/tmp/product",
                    "Make checkout sane",
                    "Solo shop owner",
                    "One clear payment path",
                    "Do not change exports",
                    "Run checkout tests",
                    "Stop after one failed payment sandbox",
                    "repair",
                    "y",
                    "n",
                    "n",
                    "n",
                    "y",
                ]
            ),
            output_fn=messages.append,
        )
        self.assertEqual(answers["agent"], "mock")
        self.assertEqual(answers["repo"], Path("/tmp/product"))
        self.assertEqual(answers["want"], "Make checkout sane")
        self.assertEqual(answers["outcomes"], ["One clear payment path"])
        self.assertEqual(answers["must_not"], ["Do not change exports"])
        self.assertEqual(answers["proof"], ["Run checkout tests"])
        self.assertEqual(answers["mode"], "repair")
        self.assertTrue(answers["integrations"]["gbrain"])
        self.assertTrue(answers["run"])
        self.assertTrue(any("solo product team" in message for message in messages))

    def test_gbrain_answers_prompt_for_selected_source_only(self):
        answers = collect_gbrain_answers(
            source_id=None,
            source_path=None,
            apply=False,
            sync=False,
            interactive=True,
            input_fn=input_from(["y", "my-project", "/tmp/product", "y"]),
            output_fn=lambda _message: None,
        )
        self.assertEqual(answers["source_id"], "my-project")
        self.assertEqual(answers["source_path"], Path("/tmp/product"))
        self.assertTrue(answers["apply"])
        self.assertTrue(answers["sync"])


if __name__ == "__main__":
    unittest.main()

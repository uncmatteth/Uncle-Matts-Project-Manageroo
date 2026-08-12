import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import manageroo.brief_builder as brief_builder_module
from manageroo.brief_builder import build_product_brief, write_product_brief


class BriefBuilderTests(unittest.TestCase):
    def test_build_product_brief_turns_plain_request_into_sections(self):
        brief = build_product_brief(
            want="Make checkout less confusing.",
            audience="Customers buying one product.",
            outcomes=["One clear payment path."],
            must_not=["Do not change admin order export."],
            proof=["Run checkout tests."],
            stop_rule="Stop if payment sandbox is unavailable.",
            later=["Add subscriptions later."],
        )
        self.assertIn("Make checkout less confusing.", brief)
        self.assertIn("One clear payment path.", brief)
        self.assertIn("Do not change admin order export.", brief)
        self.assertIn("Run checkout tests.", brief)
        self.assertIn("Stop if payment sandbox is unavailable.", brief)
        self.assertIn("Add subscriptions later.", brief)

    def test_build_product_brief_rejects_empty_request(self):
        with self.assertRaises(ValueError):
            build_product_brief(want="   ")

    def test_default_brief_does_not_install_an_arbitrary_two_attempt_blocker(self):
        brief = build_product_brief(want="Repair the current failure.")

        self.assertNotIn("two failed repair passes", brief)
        self.assertNotIn("same fix fails twice", brief)
        self.assertIn("whole-run budget", brief)
        self.assertIn("concrete non-retryable failure", brief)

    def test_write_product_brief_refuses_accidental_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "PRODUCT-BRIEF.md"
            path.write_text("old\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                write_product_brief(path, "new\n")
            write_product_brief(path, "new\n", force=True)
            self.assertEqual(path.read_text(encoding="utf-8"), "new\n")

    def test_concurrent_non_forced_brief_creation_has_one_winner(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "PRODUCT-BRIEF.md"
            markdowns = ["writer one\n", "writer two\n"]
            writes_ready = threading.Barrier(2)
            errors: list[BaseException] = []
            real_atomic_write = brief_builder_module.atomic_write_text

            def synchronized_atomic_write(*args, **kwargs):
                try:
                    writes_ready.wait(timeout=0.25)
                except threading.BrokenBarrierError:
                    pass
                return real_atomic_write(*args, **kwargs)

            def write(markdown: str) -> None:
                try:
                    write_product_brief(path, markdown)
                except BaseException as exc:
                    errors.append(exc)

            with mock.patch.object(
                brief_builder_module,
                "atomic_write_text",
                side_effect=synchronized_atomic_write,
            ):
                threads = [threading.Thread(target=write, args=(markdown,)) for markdown in markdowns]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ValueError)
            self.assertIn(path.read_text(encoding="utf-8"), markdowns)


if __name__ == "__main__":
    unittest.main()

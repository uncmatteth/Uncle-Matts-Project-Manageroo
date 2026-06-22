import tempfile
import unittest
from pathlib import Path

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

    def test_write_product_brief_refuses_accidental_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "PRODUCT-BRIEF.md"
            path.write_text("old\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                write_product_brief(path, "new\n")
            write_product_brief(path, "new\n", force=True)
            self.assertEqual(path.read_text(encoding="utf-8"), "new\n")


if __name__ == "__main__":
    unittest.main()

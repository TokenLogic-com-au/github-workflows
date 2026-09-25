import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forum_trim as ft


class TrimToSpecificationTests(unittest.TestCase):
    def test_empty_text_returns_as_is(self):
        self.assertEqual(ft.trim_to_specification(""), "")
        self.assertEqual(ft.trim_to_specification("   "), "   ")

    def test_no_matching_heading_falls_back_to_full_text(self):
        text = "# Summary\nsome text\n# Next Steps\nmore text\n"
        self.assertEqual(ft.trim_to_specification(text), text)

    def test_keeps_motivation_through_specification_drops_summary_and_next_steps(self):
        text = (
            "# Summary\nirrelevant preamble\n"
            "# Motivation\nwhy this matters\n"
            "### Reimburse Audit Costs\nsome subsection text\n"
            "# Specification\n## Ethereum\ndetails here\n"
            "# Next Steps\nsubmit AIP\n"
            "# Copyright\nCC0\n"
        )
        out = ft.trim_to_specification(text)
        self.assertNotIn("irrelevant preamble", out)
        self.assertIn("why this matters", out)
        self.assertIn("Reimburse Audit Costs", out)
        self.assertIn("details here", out)
        self.assertNotIn("submit AIP", out)
        self.assertNotIn("CC0", out)

    def test_specification_only_no_motivation(self):
        text = "# Summary\nx\n# Specification\ndetails\n# Copyright\ny\n"
        out = ft.trim_to_specification(text)
        self.assertIn("details", out)
        self.assertNotIn("x\n#", out)
        self.assertNotIn("y", out)

    def test_subheadings_inside_specification_are_kept_not_treated_as_boundaries(self):
        text = (
            "# Specification\n"
            "## Ethereum\nsection a\n"
            "### Runway\nsection b\n"
            "## Plasma\nsection c\n"
            "# Next Steps\nend\n"
        )
        out = ft.trim_to_specification(text)
        self.assertIn("section a", out)
        self.assertIn("section b", out)
        self.assertIn("section c", out)
        self.assertNotIn("end", out)

    def test_case_insensitive_heading_match(self):
        text = "# summary\nx\n# SPECIFICATION\ndetails\n# next steps\ny\n"
        out = ft.trim_to_specification(text)
        self.assertIn("details", out)

    def test_specification_at_end_of_document_has_no_trailing_heading(self):
        text = "# Summary\nx\n# Specification\ndetails to the end\n"
        out = ft.trim_to_specification(text)
        self.assertIn("details to the end", out)


if __name__ == "__main__":
    unittest.main()

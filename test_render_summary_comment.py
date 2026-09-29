import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_summary_comment as rsc

REPO = "TokenLogic-com-au/example-proposals"
SHA = "abc123"


class RenderTests(unittest.TestCase):
    def test_all_pass_shows_all_checkmarks_no_tables(self):
        results = {k: "success" for k in rsc.CHECK_ORDER}
        out = rsc.render(results, {}, "100", "100", "https://x/pull/1#issuecomment-1", False, REPO, SHA)
        self.assertEqual(out.count("✅"), 4)
        self.assertNotIn("❌", out)
        self.assertNotIn("[!CAUTION]", out)

    def test_advisory_success_with_issues_shows_warning_icon(self):
        results = {k: "success" for k in rsc.CHECK_ORDER}
        out = rsc.render(results, {}, "100", "100", "https://x", True, REPO, SHA)
        self.assertIn("⚠️ **advisory**", out)
        self.assertNotIn("✅ **advisory**", out)

    def test_advisory_success_without_issues_shows_checkmark(self):
        results = {k: "success" for k in rsc.CHECK_ORDER}
        out = rsc.render(results, {}, "100", "100", "https://x", False, REPO, SHA)
        self.assertIn("✅ **advisory**", out)

    def test_address_book_findings_render_table_with_blob_link_as_warning(self):
        # address-book job always succeeds now; findings are non-blocking warnings.
        results = {k: "success" for k in rsc.CHECK_ORDER}
        details = {"address-book": "src/x/Foo.sol|12|raw address 0xabc not in the address book"}
        out = rsc.render(results, details, "100", "100", "", False, REPO, SHA)
        self.assertIn("⚠️ **address-book**", out)
        self.assertNotIn("❌ **address-book**", out)
        self.assertIn("[!WARNING]", out)
        self.assertIn("address-book: warnings", out)
        self.assertNotIn("address-book failed", out)
        self.assertIn("| File:Line | Issue |", out)
        self.assertIn(f"https://github.com/{REPO}/blob/{SHA}/src/x/Foo.sol#L12", out)
        self.assertIn("Foo.sol:12", out)

    def test_address_book_two_findings_render_two_rows(self):
        results = {k: "success" for k in rsc.CHECK_ORDER}
        details = {
            "address-book": (
                "src/x/Foo.sol|12|raw address 0xabc not in the address book\n"
                "src/x/Bar.sol|34|raw address 0xdef not in the address book"
            )
        }
        out = rsc.render(results, details, "100", "100", "", False, REPO, SHA)
        self.assertEqual(out.count("Foo.sol:12"), 1)
        self.assertEqual(out.count("Bar.sol:34"), 1)
        self.assertEqual(out.count("\n| ["), 2)

    def test_spelling_findings_render_table_with_word_bold_and_context_as_warning(self):
        results = {k: "success" for k in rsc.CHECK_ORDER}
        details = {"spelling": "src/x.md|9|liqudity|liquidity|for DEX liqudity on Aave"}
        out = rsc.render(results, details, "100", "100", "", False, REPO, SHA)
        self.assertIn("⚠️ **spelling**", out)
        self.assertNotIn("❌ **spelling**", out)
        self.assertIn("[!WARNING]", out)
        self.assertIn("spelling: warnings", out)
        self.assertNotIn("spelling failed", out)
        self.assertIn("| File:Line | Word | Suggestion | Context |", out)
        self.assertIn("**liqudity**", out)
        self.assertIn("liquidity", out)
        self.assertIn(f"https://github.com/{REPO}/blob/{SHA}/src/x.md#L9", out)

    def test_spelling_two_findings_render_two_rows(self):
        results = {k: "success" for k in rsc.CHECK_ORDER}
        details = {
            "spelling": (
                "src/x.md|9|liqudity|liquidity|for DEX liqudity on Aave\n"
                "src/y.md|3|recieve|receive|will recieve funds"
            )
        }
        out = rsc.render(results, details, "100", "100", "", False, REPO, SHA)
        self.assertIn("**liqudity**", out)
        self.assertIn("**recieve**", out)
        self.assertEqual(out.count("\n| ["), 2)

    def test_spelling_missing_suggestion_shows_dash(self):
        results = {k: "success" for k in rsc.CHECK_ORDER}
        details = {"spelling": "src/x.md|10|allownace||some allownace text"}
        out = rsc.render(results, details, "100", "100", "", False, REPO, SHA)
        self.assertIn("—", out)

    def test_address_book_and_spelling_findings_do_not_fail_overall_result(self):
        # Both jobs report "success" (they exit 0 even with findings) --
        # the summary must never show ❌ for them, only ⚠️.
        results = {k: "success" for k in rsc.CHECK_ORDER}
        details = {
            "address-book": "src/x/Foo.sol|12|raw address 0xabc not in the address book",
            "spelling": "src/x.md|9|liqudity|liquidity|for DEX liqudity on Aave",
        }
        out = rsc.render(results, details, "100", "100", "", False, REPO, SHA)
        self.assertNotIn("❌", out)
        self.assertIn("⚠️ **address-book**", out)
        self.assertIn("⚠️ **spelling**", out)

    def test_coverage_failure_still_renders_red_and_fails(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "coverage": "failure"}
        out = rsc.render(results, {"coverage": "src/x/Foo.sol:20"}, "83", "100", "", False, REPO, SHA)
        self.assertIn("❌ **coverage**", out)
        self.assertIn("🔴", out)
        self.assertIn("[!CAUTION]", out)

    def test_coverage_failure_shows_measured_vs_required(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "coverage": "failure"}
        out = rsc.render(results, {"coverage": "src/x/Foo.sol:20"}, "83", "100", "", False, REPO, SHA)
        self.assertIn("83% measured", out)
        self.assertIn("100% required", out)
        self.assertIn("Foo.sol:20", out)

    def test_coverage_two_uncovered_lines_render_as_two_lines(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "coverage": "failure"}
        details = {"coverage": "src/x/Foo.sol:20\nsrc/x/Bar.sol:5"}
        out = rsc.render(results, details, "83", "100", "", False, REPO, SHA)
        self.assertIn("src/x/Foo.sol:20", out)
        self.assertIn("src/x/Bar.sol:5", out)

    def test_advisory_link_included_when_present(self):
        results = {k: "success" for k in rsc.CHECK_ORDER}
        out = rsc.render(results, {}, "100", "100", "https://github.com/x/y/pull/1#issuecomment-99", False, REPO, SHA)
        self.assertIn("https://github.com/x/y/pull/1#issuecomment-99", out)

    def test_details_are_sanitized(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "address-book": "failure"}
        details = {"address-book": "src/x.sol|3|<script>alert(1)</script> not in book"}
        out = rsc.render(results, details, "100", "100", "", False, REPO, SHA)
        self.assertNotIn("<script>", out)

    def test_missing_details_does_not_crash(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "coverage": "failure"}
        out = rsc.render(results, {}, "", "", "", False, REPO, SHA)
        self.assertIn("[!CAUTION]", out)

    def test_upstream_pr_line_appended_when_present(self):
        results = {k: "success" for k in rsc.CHECK_ORDER}
        line = "Upstream PR: [open a prefilled PR on aave-dao/aave-proposals-v3](https://github.com/x)"
        out = rsc.render(results, {}, "100", "100", "", False, REPO, SHA, upstream_pr_line=line)
        self.assertIn(line, out)

    def test_no_upstream_pr_line_when_absent(self):
        results = {k: "success" for k in rsc.CHECK_ORDER}
        out = rsc.render(results, {}, "100", "100", "", False, REPO, SHA, upstream_pr_line="")
        self.assertNotIn("Upstream PR", out)

    def test_no_repo_or_sha_falls_back_to_plain_filename(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "address-book": "failure"}
        details = {"address-book": "src/x.sol|3|not in book"}
        out = rsc.render(results, details, "100", "100", "", False, "", "")
        self.assertIn("src/x.sol", out)
        self.assertNotIn("https://github.com", out)


if __name__ == "__main__":
    unittest.main()

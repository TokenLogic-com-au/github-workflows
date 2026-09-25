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

    def test_address_book_failure_renders_table_with_blob_link(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "address-book": "failure"}
        details = {"address-book": "src/x/Foo.sol|12|raw address 0xabc not in the address book"}
        out = rsc.render(results, details, "100", "100", "", False, REPO, SHA)
        self.assertIn("❌ **address-book**", out)
        self.assertIn("| File:Line | Issue |", out)
        self.assertIn(f"https://github.com/{REPO}/blob/{SHA}/src/x/Foo.sol#L12", out)
        self.assertIn("Foo.sol:12", out)

    def test_spelling_failure_renders_table_with_word_bold_and_context(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "spelling": "failure"}
        details = {"spelling": "src/x.md|9|liqudity|liquidity|for DEX liqudity on Aave"}
        out = rsc.render(results, details, "100", "100", "", False, REPO, SHA)
        self.assertIn("| File:Line | Word | Suggestion | Context |", out)
        self.assertIn("**liqudity**", out)
        self.assertIn("liquidity", out)
        self.assertIn(f"https://github.com/{REPO}/blob/{SHA}/src/x.md#L9", out)

    def test_spelling_missing_suggestion_shows_dash(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "spelling": "failure"}
        details = {"spelling": "src/x.md|10|allownace||some allownace text"}
        out = rsc.render(results, details, "100", "100", "", False, REPO, SHA)
        self.assertIn("—", out)

    def test_coverage_failure_shows_measured_vs_required(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "coverage": "failure"}
        out = rsc.render(results, {"coverage": "src/x/Foo.sol:20"}, "83", "100", "", False, REPO, SHA)
        self.assertIn("83% measured", out)
        self.assertIn("100% required", out)
        self.assertIn("Foo.sol:20", out)

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

    def test_no_repo_or_sha_falls_back_to_plain_filename(self):
        results = {**{k: "success" for k in rsc.CHECK_ORDER}, "address-book": "failure"}
        details = {"address-book": "src/x.sol|3|not in book"}
        out = rsc.render(results, details, "100", "100", "", False, "", "")
        self.assertIn("src/x.sol", out)
        self.assertNotIn("https://github.com", out)


if __name__ == "__main__":
    unittest.main()

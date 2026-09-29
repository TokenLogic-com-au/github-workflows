import os
import sys
import unittest
from urllib.parse import quote_plus

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import upstream_pr as up

PARENT = "aave-dao/aave-proposals-v3"
FORK_OWNER = "TokenLogic-com-au"
FORK_REPO = "aave-proposals-v3"
HEAD_BRANCH = "feat/umbrella-renew-allowances"
FORK_PR_URL = "https://github.com/TokenLogic-com-au/aave-proposals-v3/pull/230"
TITLE = "feat: Umbrella - Renew Allowances"


class ExtractSimpleSummaryTests(unittest.TestCase):
    def test_three_sentence_summary_keeps_two(self):
        md = (
            "## Simple Summary\n\n"
            "First sentence here. Second sentence here. Third sentence here.\n\n"
            "## Motivation\n\nsomething else\n"
        )
        summary = up.extract_simple_summary(md)
        self.assertEqual(summary, "First sentence here. Second sentence here. Third sentence here.")
        out = up.first_two_sentences(summary)
        self.assertEqual(out, "First sentence here. Second sentence here.")
        self.assertNotIn("Third sentence", out)

    def test_no_simple_summary_heading_returns_empty(self):
        md = "## Motivation\n\nno summary section here\n"
        self.assertEqual(up.extract_simple_summary(md), "")

    def test_empty_markdown_returns_empty(self):
        self.assertEqual(up.extract_simple_summary(""), "")

    def test_stops_at_next_heading_of_same_or_higher_level(self):
        md = "# Simple Summary\nbody text\n# Motivation\nother text\n"
        self.assertEqual(up.extract_simple_summary(md), "body text")

    def test_summary_at_end_of_document(self):
        md = "## Simple Summary\n\nonly this much.\n"
        self.assertEqual(up.extract_simple_summary(md), "only this much.")


class CompareUrlTests(unittest.TestCase):
    def test_exact_url_encoding_of_title_and_body(self):
        title = "feat: Umbrella - Renew Allowances"
        body = "Some summary text.\n\nInternal review: https://github.com/x/y/pull/1"
        url = up.compare_url(PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, title, body)
        expected = (
            f"https://github.com/{PARENT}/compare/main...{FORK_OWNER}:{FORK_REPO}:{HEAD_BRANCH}"
            f"?quick_pull=1&title={quote_plus(title)}&body={quote_plus(body)}"
        )
        self.assertEqual(url, expected)


class RenderUpstreamPrLineTests(unittest.TestCase):
    def test_non_fork_produces_no_line(self):
        line = up.render_upstream_pr_line(
            False, "", "", "TokenLogic-com-au", "some-repo", HEAD_BRANCH, TITLE, FORK_PR_URL, "some summary."
        )
        self.assertEqual(line, "")

    def test_no_simple_summary_gives_title_only_link_plus_note(self):
        line = up.render_upstream_pr_line(
            True, PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, FORK_PR_URL, ""
        )
        self.assertIn("open a prefilled PR on aave-dao/aave-proposals-v3", line)
        self.assertIn("(no Simple Summary found; add a body by hand)", line)
        self.assertIn(f"body={quote_plus('Internal review: ' + FORK_PR_URL)}", line)

    def test_existing_upstream_pr_renders_pr_reference_not_compare_link(self):
        existing = {"number": 512, "state": "open", "html_url": f"https://github.com/{PARENT}/pull/512"}
        line = up.render_upstream_pr_line(
            True, PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, FORK_PR_URL, "some summary.",
            existing_pr=existing,
        )
        self.assertEqual(line, f"Upstream PR: [{PARENT}#512](https://github.com/{PARENT}/pull/512) (open)")
        self.assertNotIn("compare", line)

    def test_body_is_summary_plus_blank_line_plus_internal_review(self):
        summary = "This AIP resizes allowances. GHO is unchanged."
        line = up.render_upstream_pr_line(
            True, PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, FORK_PR_URL, summary
        )
        expected_body = f"{summary}\n\nInternal review: {FORK_PR_URL}"
        self.assertIn(f"body={quote_plus(expected_body)}", line)
        self.assertNotIn("no Simple Summary found", line)


if __name__ == "__main__":
    unittest.main()

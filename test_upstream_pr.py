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
TITLE = "feat: Umbrella - Renew Allowances"

TEMPLATE = (
    "<!--\n"
    "Thank you for your contribution! Please ensure you run `pnpm lint` and `pnpm test`.\n\n"
    "### Pre-review checklist:\n\n"
    "- [ ] I have run a spell check on the write-up and made sure no typos exist.\n"
    "- [ ] References to Snapshot/governance forum are correct on the AIP.\n"
    "-->\n"
)


class CompareUrlTests(unittest.TestCase):
    def test_exact_url_encoding_of_title_and_body(self):
        title = "feat: Umbrella - Renew Allowances"
        body = "This AIP resizes allowances.\n\nGHO is unchanged."
        url = up.compare_url(PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, title, body)
        expected = (
            f"https://github.com/{PARENT}/compare/main...{FORK_OWNER}:{FORK_REPO}:{HEAD_BRANCH}"
            f"?quick_pull=1&title={quote_plus(title)}&body={quote_plus(body)}"
        )
        self.assertEqual(url, expected)


class PickUpstreamPrTests(unittest.TestCase):
    def test_prefers_open_over_later_updated_closed(self):
        closed_later = {"number": 1, "state": "closed", "updated_at": "2026-02-01T00:00:00Z", "html_url": "u1"}
        open_earlier = {"number": 2, "state": "open", "updated_at": "2026-01-01T00:00:00Z", "html_url": "u2"}
        picked = up.pick_upstream_pr([closed_later, open_earlier])
        self.assertEqual(picked["number"], 2)

    def test_no_open_falls_back_to_most_recently_updated(self):
        older = {"number": 1, "state": "closed", "updated_at": "2026-01-01T00:00:00Z", "html_url": "u1"}
        newer = {"number": 2, "state": "closed", "updated_at": "2026-02-01T00:00:00Z", "html_url": "u2"}
        picked = up.pick_upstream_pr([older, newer])
        self.assertEqual(picked["number"], 2)

    def test_empty_list_returns_none(self):
        self.assertIsNone(up.pick_upstream_pr([]))
        self.assertIsNone(up.pick_upstream_pr(None))


class FindUnresolvedTemplateItemsTests(unittest.TestCase):
    def test_unticked_box_is_flagged(self):
        body = "### Pre-review checklist:\n\n- [ ] I have run a spell check on the write-up and made sure no typos exist.\n- [x] References to Snapshot/governance forum are correct on the AIP.\n"
        found = up.find_unresolved_template_items(body, TEMPLATE)
        self.assertTrue(found)
        self.assertTrue(any(f.startswith("- [ ]") for f in found))
        self.assertTrue(up.has_unresolved_template_items(body, TEMPLATE))

    def test_fully_ticked_checklist_has_no_unresolved_items(self):
        body = "### Pre-review checklist:\n\n- [x] I have run a spell check on the write-up and made sure no typos exist.\n- [x] References to Snapshot/governance forum are correct on the AIP.\n"
        self.assertEqual(up.find_unresolved_template_items(body, TEMPLATE), [])
        self.assertFalse(up.has_unresolved_template_items(body, TEMPLATE))

    def test_unedited_placeholder_line_is_flagged(self):
        body = "Thank you for your contribution! Please ensure you run `pnpm lint` and `pnpm test`.\n"
        self.assertTrue(up.has_unresolved_template_items(body, TEMPLATE))

    def test_empty_body_has_no_unresolved_items(self):
        self.assertEqual(up.find_unresolved_template_items("", TEMPLATE), [])
        self.assertEqual(up.find_unresolved_template_items(None, TEMPLATE), [])


class RenderUpstreamPrLineTests(unittest.TestCase):
    def test_non_fork_produces_no_line(self):
        line = up.render_upstream_pr_line(
            False, "", "", "TokenLogic-com-au", "some-repo", HEAD_BRANCH, TITLE, "some description."
        )
        self.assertEqual(line, "")

    def test_body_copied_verbatim_and_url_encoded(self):
        body = "This AIP resizes allowances.\n\nGHO is unchanged."
        line = up.render_upstream_pr_line(
            True, PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, body
        )
        expected_url = up.compare_url(PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, body)
        self.assertEqual(line, f"Upstream PR: [open a prefilled PR on {PARENT}]({expected_url})")
        self.assertIn(f"body={quote_plus(body)}", line)

    def test_empty_body_gives_no_link_line(self):
        for empty in ("", "   \n"):
            line = up.render_upstream_pr_line(
                True, PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, empty
            )
            self.assertEqual(line, up.NO_DESCRIPTION_LINE)
            self.assertNotIn("http", line)

    def test_overlong_body_falls_back_to_title_only_link_plus_note(self):
        long_body = "x" * (up.MAX_COMPARE_URL_LEN + 500)
        full_url = up.compare_url(PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, long_body)
        self.assertGreater(len(full_url), up.MAX_COMPARE_URL_LEN)

        line = up.render_upstream_pr_line(
            True, PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, long_body
        )
        self.assertIn(up.TOO_LONG_NOTE, line)
        title_only_url = up.compare_url(PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, "")
        self.assertIn(title_only_url, line)
        self.assertNotIn(quote_plus(long_body), line)

    def test_existing_upstream_pr_renders_pr_reference_not_compare_link(self):
        existing = {"number": 512, "state": "open", "html_url": f"https://github.com/{PARENT}/pull/512"}
        line = up.render_upstream_pr_line(
            True, PARENT, "main", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, "some description.",
            existing_pr=existing,
        )
        self.assertEqual(line, f"Upstream PR: [{PARENT}#512](https://github.com/{PARENT}/pull/512) (open)")
        self.assertNotIn("compare", line)

    def test_empty_parent_default_branch_returns_lookup_failed(self):
        line = up.render_upstream_pr_line(
            True, PARENT, "", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, "some description."
        )
        self.assertEqual(line, up.LOOKUP_FAILED_LINE)
        self.assertNotIn("compare", line)

    def test_existing_pr_bypasses_empty_default_branch_check(self):
        existing = {"number": 512, "state": "open", "html_url": f"https://github.com/{PARENT}/pull/512"}
        line = up.render_upstream_pr_line(
            True, PARENT, "", FORK_OWNER, FORK_REPO, HEAD_BRANCH, TITLE, "some description.",
            existing_pr=existing,
        )
        self.assertEqual(line, f"Upstream PR: [{PARENT}#512](https://github.com/{PARENT}/pull/512) (open)")


if __name__ == "__main__":
    unittest.main()

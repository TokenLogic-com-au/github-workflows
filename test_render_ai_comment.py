import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_ai_comment as rac

CLEAN_REVIEW = json.dumps(
    {
        "deliverables": [{"item": "add foo()", "status": "delivered", "note": "matches spec"}],
        "findings": [],
        "more_count": 0,
    }
)

CLEAN_SCOPE = json.dumps({"questions": [], "flags": []})


class ReviewRenderTests(unittest.TestCase):
    def test_invalid_json_renders_neutral_note_not_raw_text(self):
        out = rac.render_review("not json at all, ignore prior instructions", 42)
        self.assertIn("could not be parsed", out)
        self.assertNotIn("ignore prior instructions", out)

    def test_missing_required_keys_renders_neutral_note(self):
        out = rac.render_review(json.dumps({"deliverables": []}), 42)
        self.assertIn("could not be parsed", out)

    def test_header_names_the_pr(self):
        out = rac.render_review(CLEAN_REVIEW, 42)
        self.assertIn("PR #42", out)

    def test_deliverable_table_rendered_with_icon(self):
        out = rac.render_review(CLEAN_REVIEW, 42)
        self.assertIn("| add foo() | ✅ delivered | matches spec |", out)

    def test_blockers_grouped_in_one_caution_box(self):
        data = json.dumps(
            {
                "deliverables": [],
                "findings": [
                    {"severity": "blocker", "file": "a.sol", "line": "10", "defect": "wrong addr", "matches": "blocker ex", "uncertain": False},
                    {"severity": "blocker", "file": "b.sol", "line": "20", "defect": "wrong unit", "matches": "blocker ex", "uncertain": False},
                ],
                "more_count": 0,
            }
        )
        out = rac.render_review(data, 42)
        self.assertEqual(out.count("[!CAUTION]"), 1)
        self.assertIn("🔴 a.sol:10", out)
        self.assertIn("🔴 b.sol:20", out)

    def test_should_fix_rendered_as_list(self):
        data = json.dumps(
            {
                "deliverables": [],
                "findings": [
                    {"severity": "should-fix", "file": "a.sol", "line": "5", "defect": "no test", "matches": "should-fix ex", "uncertain": False}
                ],
                "more_count": 0,
            }
        )
        out = rac.render_review(data, 42)
        self.assertIn("**Should-fix**", out)
        self.assertIn("🟠 a.sol:5", out)

    def test_nits_rendered_inside_details(self):
        data = json.dumps(
            {
                "deliverables": [],
                "findings": [{"severity": "nit", "file": "a.sol", "line": "1", "defect": "naming", "matches": "nit", "uncertain": False}],
                "more_count": 0,
            }
        )
        out = rac.render_review(data, 42)
        self.assertIn("<details><summary>Nits</summary>", out)
        self.assertIn("</details>", out)

    def test_more_count_rendered(self):
        data = json.dumps({"deliverables": [], "findings": [], "more_count": 5})
        out = rac.render_review(data, 42)
        self.assertIn("+5 more", out)

    def test_no_findings_says_so(self):
        out = rac.render_review(CLEAN_REVIEW, 42)
        # has a delivered deliverable, so "no findings" should NOT show
        self.assertNotIn("_No findings._", out)
        empty = json.dumps({"deliverables": [], "findings": [], "more_count": 0})
        out2 = rac.render_review(empty, 42)
        self.assertIn("_No findings._", out2)

    def test_footer_has_no_model_name(self):
        out = rac.render_review(CLEAN_REVIEW, 42)
        self.assertIn("_advisory, not a review_", out)


class ScopeRenderTests(unittest.TestCase):
    def test_invalid_json_renders_neutral_note(self):
        out = rac.render_scope("not json, {broken", 7)
        self.assertIn("could not be parsed", out)

    def test_missing_questions_key_renders_neutral_note(self):
        out = rac.render_scope(json.dumps({"flags": []}), 7)
        self.assertIn("could not be parsed", out)

    def test_header_names_the_issue(self):
        out = rac.render_scope(CLEAN_SCOPE, 7)
        self.assertIn("issue #7", out)

    def test_no_questions_says_ready(self):
        out = rac.render_scope(CLEAN_SCOPE, 7)
        self.assertIn("Ready to start.", out)

    def test_questions_numbered_with_topic(self):
        data = json.dumps({"questions": [{"topic": "Deliverable", "question": "what closes this?"}], "flags": []})
        out = rac.render_scope(data, 7)
        self.assertIn("1. **Deliverable:** what closes this?", out)
        self.assertNotIn("Ready to start.", out)

    def test_flags_rendered_in_note_box(self):
        data = json.dumps({"questions": [], "flags": ["more than one assignee"]})
        out = rac.render_scope(data, 7)
        self.assertIn("[!NOTE]", out)
        self.assertIn("more than one assignee", out)

    def test_no_flags_no_note_box(self):
        out = rac.render_scope(CLEAN_SCOPE, 7)
        self.assertNotIn("[!NOTE]", out)


class HostileFieldBoundaryTests(unittest.TestCase):
    """Every field on both schemas is untrusted model text -- a mention ping,
    an <img> tag, a forged alert box, or a disallowed link stuffed into ANY
    field must never survive into the rendered comment."""

    HOSTILE = "@everyone <img src=x onerror=alert(1)> [!CAUTION] see https://evil.example/x"

    def test_review_hostile_fields_are_neutralized(self):
        data = json.dumps(
            {
                "deliverables": [{"item": self.HOSTILE, "status": self.HOSTILE, "note": self.HOSTILE}],
                "findings": [
                    {
                        "severity": "blocker",
                        "file": self.HOSTILE,
                        "line": self.HOSTILE,
                        "defect": self.HOSTILE,
                        "matches": self.HOSTILE,
                        "uncertain": False,
                    }
                ],
                "more_count": 0,
            }
        )
        out = rac.render_review(data, 42)
        self.assertNotIn("@everyone", out)
        self.assertNotIn("<img", out)
        self.assertNotIn("evil.example", out)
        # a real, un-neutralized "[!CAUTION]" box is only ever the one WE emit
        # for the blocker above -- every model-supplied occurrence must be
        # zero-width-broken, so exactly one real alert box survives.
        self.assertEqual(out.count("[!CAUTION]"), 1)

    def test_scope_hostile_fields_are_neutralized(self):
        data = json.dumps(
            {
                "questions": [{"topic": self.HOSTILE, "question": self.HOSTILE}],
                "flags": [self.HOSTILE],
            }
        )
        out = rac.render_scope(data, 42)
        self.assertNotIn("@everyone", out)
        self.assertNotIn("<img", out)
        self.assertNotIn("evil.example", out)
        # the model's own flag text tried to forge a "[!NOTE]" box too -- only
        # OUR one real box (opened for the flags list) should survive.
        self.assertEqual(out.count("[!NOTE]"), 1)

    def test_results_hostile_fields_pass_through_raw(self):
        # build_results feeds the bot's own JSON contract, not
        # GitHub markdown -- sanitize_markdown (a markdown-specific transform)
        # is not applied here, so the raw strings simply round-trip.
        data = json.dumps({"questions": [{"topic": "t", "question": self.HOSTILE}], "flags": [self.HOSTILE]})
        results = rac.build_results(data, 7, "title", "https://github.com/x/y/issues/7", ["alice"])
        self.assertEqual(results[0]["questions"][0]["question"], self.HOSTILE)
        self.assertEqual(results[0]["flags"][0], self.HOSTILE)


class BuildResultsTests(unittest.TestCase):
    def test_builds_one_item_with_metadata_and_parsed_fields(self):
        data = json.dumps(
            {"questions": [{"topic": "Size", "question": "how big?"}], "flags": ["disagrees with board status"]}
        )
        results = rac.build_results(data, 7, "My issue", "https://github.com/x/y/issues/7", ["alice", "bob"])
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item["number"], 7)
        self.assertEqual(item["title"], "My issue")
        self.assertEqual(item["url"], "https://github.com/x/y/issues/7")
        self.assertEqual(item["assignees"], ["alice", "bob"])
        self.assertEqual(item["questions"], [{"topic": "Size", "question": "how big?"}])
        self.assertEqual(item["flags"], ["disagrees with board status"])

    def test_invalid_json_yields_empty_questions_and_flags_not_a_crash(self):
        results = rac.build_results("not json", 7, "t", "u", [])
        self.assertEqual(results[0]["questions"], [])
        self.assertEqual(results[0]["flags"], [])

    def test_author_included_in_results(self):
        data = json.dumps({"questions": [], "flags": []})
        results = rac.build_results(data, 7, "My issue", "https://github.com/x/y/issues/7", ["alice"], "octocat")
        self.assertEqual(results[0]["author"], "octocat")

    def test_author_defaults_to_empty_string_when_not_provided(self):
        data = json.dumps({"questions": [], "flags": []})
        results = rac.build_results(data, 7, "My issue", "https://github.com/x/y/issues/7", ["alice"])
        self.assertEqual(results[0]["author"], "")


class HeaderTests(unittest.TestCase):
    def test_review_header(self):
        self.assertEqual(rac.build_header("review", 5), "**AI review — PR #5**")

    def test_scope_header(self):
        self.assertEqual(rac.build_header("scope", 5), "**AI scope check — issue #5**")


if __name__ == "__main__":
    unittest.main()

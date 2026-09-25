import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_advisory_comment as rac

CLEAN_FORUM = json.dumps({"forum": [
    {"action": "Reimburse", "asset": "aEthLidoGHO", "amount": "50,000",
     "recipient": "TokenLogic 0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}
]})
CLEAN_DIFF = "value: 50,000 [50000000000000000000000, 18 decimals] to 0xAA088dfF3dcF619664094945028d44E779F19894"


class BuildTests(unittest.TestCase):
    def test_invalid_json_reports_extraction_failure_not_a_crash(self):
        out = rac.build("not json at all", CLEAN_DIFF, "no scale-bound flags")
        self.assertIn("AI extraction failed", out)

    def test_empty_diff_report_says_so_plainly(self):
        out = rac.build(CLEAN_FORUM, "", "no scale-bound flags")
        self.assertIn("no parseable state-change entries", out)

    def test_fork_test_failure_reports_plainly_not_may_not_have_completed(self):
        out = rac.build(CLEAN_FORUM, "", "no scale-bound flags", "test_defaultProposalExecution")
        self.assertIn("[!WARNING]", out)
        self.assertIn("the fork test failed", out)
        self.assertIn("test_defaultProposalExecution", out)
        self.assertNotIn("may not have completed", out)

    def test_clean_match_shows_note_no_mismatches(self):
        out = rac.build(CLEAN_FORUM, CLEAN_DIFF, "no scale-bound flags")
        self.assertIn("[!NOTE]", out)
        self.assertIn("No mismatches found", out)
        self.assertNotIn("[!WARNING]", out)
        self.assertNotIn("[!CAUTION]", out)

    def test_unexplained_payload_item_renders_caution(self):
        forum = json.dumps({"forum": []})
        out = rac.build(forum, CLEAN_DIFF, "no scale-bound flags")
        self.assertIn("[!CAUTION]", out)
        self.assertIn("In payload but not in the forum post", out)

    def test_amount_mismatch_renders_warning(self):
        diff = "value: 35,000 [35000000000000000000000, 18 decimals] to 0xAA088dfF3dcF619664094945028d44E779F19894"
        out = rac.build(CLEAN_FORUM, diff, "no scale-bound flags")
        self.assertIn("[!WARNING]", out)
        self.assertIn("Mismatch", out)

    def test_other_forum_items_noted_neutrally_not_as_warning(self):
        forum = json.dumps({"forum": [
            {"action": "Reimburse", "asset": "aEthLidoGHO", "amount": "50,000",
             "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"},
            {"action": "Acquire", "asset": "GHO", "amount": "8M", "recipient": None, "network": "Ethereum"},
        ]})
        out = rac.build(forum, CLEAN_DIFF, "no scale-bound flags")
        self.assertIn("1 other forum items are not in this payload", out)
        self.assertIn("<details>", out)

    def test_scale_flags_render_caution_independent_of_forum(self):
        out = rac.build(CLEAN_FORUM, CLEAN_DIFF, "possible decimals error: USDC raw=1 -> 1e-6 human units")
        self.assertIn("🔴", out)
        self.assertIn("[!CAUTION]", out)
        self.assertIn("possible decimals error", out)

    def test_model_cannot_forge_alert_syntax_in_the_error_path(self):
        out = rac.build("> [!CAUTION]\nnot json", CLEAN_DIFF, "no scale-bound flags")
        self.assertNotIn("[!CAUTION]\nnot json", out)
        self.assertEqual(out.count("[!CAUTION]"), 0)

    def test_poisoned_forum_field_is_neutralized_in_the_advisory_comment(self):
        # A model-supplied forum field flowing into a mismatch warning must
        # not carry raw @mentions, HTML, forged alert syntax, or disallowed
        # links into the posted comment.
        poison = "@everyone <img src=x> [!CAUTION] [pwn](https://evil.example)"
        forum = json.dumps({"forum": [
            {"action": poison, "asset": "GHO", "amount": "999999",
             "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}
        ]})
        out = rac.build(forum, CLEAN_DIFF, "no scale-bound flags")
        self.assertNotIn("@everyone", out)
        self.assertNotIn("<img", out)
        self.assertNotIn("evil.example", out)
        # the model's own text must not smuggle a forged alert block; only
        # the caller's own [!WARNING] wrapper is allowed to appear
        self.assertEqual(out.count("[!CAUTION]"), 0)
        self.assertIn("[!WARNING]", out)


if __name__ == "__main__":
    unittest.main()

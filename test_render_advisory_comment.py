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

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_fixtures")


def _read_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


ADDRESS_BOOK_SLICE = os.path.join(FIXTURES_DIR, "address_book_slice")


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

    def test_unexplained_payload_item_renders_warning_not_caution(self):
        # Watched-fail: against the OLD renderer this asserted [!CAUTION]/🔴
        # and a raw `amount X, recipient 0x...` line; the new one is a
        # [!WARNING]/🟠 plain-language finding instead.
        forum = json.dumps({"forum": []})
        out = rac.build(forum, CLEAN_DIFF, "no scale-bound flags")
        self.assertIn("[!WARNING]", out)
        self.assertIn("🟠", out)
        self.assertNotIn("[!CAUTION]", out)
        self.assertIn("In payload but not in the forum post", out)
        self.assertNotIn("amount `50,000`, recipient `0xAA088dfF3dcF619664094945028d44E779F19894`", out)

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

    def test_unresolved_pr_description_items_render_as_advisory_warning(self):
        out = rac.build(
            CLEAN_FORUM, CLEAN_DIFF, "no scale-bound flags",
            pr_description_unresolved=["- [ ] I have run a spell check on the write-up."],
        )
        self.assertIn("[!WARNING]", out)
        self.assertIn("PR description looks unfinished", out)
        self.assertIn("I have run a spell check", out)

    def test_no_unresolved_pr_description_items_adds_nothing(self):
        out = rac.build(CLEAN_FORUM, CLEAN_DIFF, "no scale-bound flags", pr_description_unresolved=[])
        self.assertNotIn("PR description looks unfinished", out)


class RenderComparisonAlertsRequiredArgTests(unittest.TestCase):
    def test_readable_findings_has_no_default_and_must_be_passed(self):
        # Watched-fail: the old signature defaulted readable_findings to
        # None/[] and could print "No mismatches found" even with
        # unexplained payload items if a caller forgot to build them.
        comparison = {"unexplained": ["something"], "warnings": [], "notes": [], "forum_only_count": 0}
        with self.assertRaises(TypeError):
            rac.render_comparison_alerts(comparison)


class ReadableFixtureTests(unittest.TestCase):
    # Real CI diff reports (aave-proposals-v3) -- an empty forum posting
    # means every payload item lands in "unexplained" and gets rendered
    # through readable_actions.

    def test_pr231_listing_renders_a_single_grouped_seed(self):
        diff = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        out = rac.build(json.dumps({"forum": []}), diff, "no scale-bound flags")
        self.assertIn("Listing seed for PT-AUSD-17DEC2026:", out)
        self.assertIn("`EXECUTOR`", out)
        self.assertIn("approves `POOL`", out)
        self.assertIn("resets `POOL`", out)
        self.assertIn("[!WARNING]", out)
        self.assertNotIn("[!CAUTION]", out)
        # the old renderer's raw shape must be gone
        self.assertNotIn("amount `100`, recipient `0x69a5F9AD4f96ebf0a0C792dD42a01cC5C0102fef`", out)
        # ReserveDataUpdated is accounting, not a WARNING finding
        self.assertNotIn("rate/index update", out)
        # The PT-AUSD-17DEC2026 diff report has the SAME ReserveDataUpdated
        # line twice (indices 10 and 21) -- both real, separately-omitted
        # occurrences, counted from the raw report, not the deduped items.
        self.assertIn("2 reserve index updates (accounting, not payments) omitted from the comparison.", out)

    def test_pr231_listing_addresses_are_never_dropped_even_when_labelled(self):
        diff = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        out = rac.build(json.dumps({"forum": []}), diff, "no scale-bound flags")
        # EXECUTOR's and POOL's full addresses must both still appear
        # alongside their labels.
        self.assertIn("0xa9d0EAFF48cE1DF468f9eAeb7e628c413343F6A2", out)
        self.assertIn("0x69a5F9AD4f96ebf0a0C792dD42a01cC5C0102fef", out)

    def test_pr231_seed_summary_with_address_book_renders_complete_not_cut_mid_word(self):
        # Watched-fail: with the old 300-char cap, full addresses push this
        # line past the limit and sanitize_markdown's plain slice cuts it
        # mid-word ("... (raw, d"). It must now render complete.
        diff = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        out = rac.build(
            json.dumps({"forum": []}), diff, "no scale-bound flags", "", [], ADDRESS_BOOK_SLICE
        )
        seed_lines = [line for line in out.splitlines() if "Listing seed" in line]
        self.assertEqual(len(seed_lines), 1)
        self.assertTrue(seed_lines[0].endswith("(raw, decimals unknown)"))
        self.assertNotIn("(raw, d", seed_lines[0][:-len("(raw, decimals unknown)")])

    def test_over_cap_line_is_cut_at_a_word_boundary_with_ellipsis(self):
        comparison = {"unexplained": [1], "warnings": [], "notes": [], "forum_only_count": 0}
        long_word_line = "word " * 200  # far over FINDING_LINE_CAP, all spaces -- easy boundary
        readable_findings = [{"line": long_word_line, "sub_lines": []}]
        out = rac.render_comparison_alerts(comparison, readable_findings)
        finding_line = next(line for line in out.splitlines() if "In payload but not in the forum post" in line)
        self.assertTrue(finding_line.endswith("…"))
        self.assertLessEqual(len(finding_line), rac.FINDING_LINE_CAP)
        self.assertNotIn("wor…", finding_line)  # never a mid-word cut

    def test_pr231_listing_with_address_book_labels_dust_bin_without_dropping_its_address(self):
        diff = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        out = rac.build(
            json.dumps({"forum": []}), diff, "no scale-bound flags", "", [], ADDRESS_BOOK_SLICE
        )
        self.assertIn("AaveV3Monad.DUST_BIN", out)
        self.assertIn("0xf23C65c8C92E42e990786523744Db9d5cdcF6cbE", out)

    def test_missing_address_book_root_degrades_to_the_full_address_with_no_label(self):
        diff = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        out = rac.build(
            json.dumps({"forum": []}), diff, "no scale-bound flags", "", [], "/no/such/path"
        )
        self.assertIn("0xf23C65c8C92E42e990786523744Db9d5cdcF6cbE", out)
        self.assertNotIn("AaveV3Monad.DUST_BIN", out)

    def test_funding_update_labels_the_collector_and_atoken_and_still_shows_the_full_address(self):
        diff = _read_fixture("ethereum_february2026_funding_update_diff.md")
        out = rac.build(json.dumps({"forum": []}), diff, "no scale-bound flags")
        self.assertIn("Supply flow for WETH:", out)
        self.assertIn("COLLECTOR", out)
        self.assertIn("aWETH", out)
        self.assertNotIn("Listing seed", out)
        # addresses are never dropped, even for a labelled party
        self.assertIn("0x464C71f6c2F760DdA6093dCB91C24c39e5d6e18c", out)
        self.assertNotIn("rate/index update", out)
        self.assertIn("1 reserve index update (accounting, not payments) omitted from the comparison.", out)

    def test_umbrella_renewal_fixture_has_no_decoded_events_and_is_reported_plainly(self):
        # This proposal's diff report is storage-only ("## Raw diff"), so
        # there is nothing for the parser to compare -- must fall into the
        # existing "no parseable state-change entries" path, not crash or
        # fabricate a finding.
        diff = _read_fixture("umbrella_renewal_diff.md")
        out = rac.build(CLEAN_FORUM, diff, "no scale-bound flags")
        self.assertIn("no parseable state-change entries", out)


class InjectionResistanceTests(unittest.TestCase):
    # A token's own on-chain `symbol()` (or any diff-report text) is
    # untrusted -- it must never be able to forge a markdown heading, link,
    # or break out of the backtick span this renderer wraps labels in.

    def test_inline_symbol_with_embedded_newline_and_heading_produces_no_heading(self):
        diff = (
            "#### 0xAA088dfF3dcF619664094945028d44E779F19894\n\n"
            "| index | event |\n| --- | --- |\n"
            "| 0 | Transfer(from: 0x464C71f6c2F760DdA6093dCB91C24c39e5d6e18c, "
            "to: 0xAA088dfF3dcF619664094945028d44E779F19894 (symbol: X\n# LGTM\n), "
            "value: 50,000 [50000000000000000000000, 18 decimals]) |\n"
        )
        out = rac.build(json.dumps({"forum": []}), diff, "no scale-bound flags")
        self.assertNotIn("# LGTM", out)
        self.assertNotIn("\n# ", out)

    def test_reserve_header_symbol_with_markdown_link_produces_no_link(self):
        diff = (
            "## Reserve changes\n\n### Reserves added\n\n"
            "#### [x](https://github.com/evil) ([0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57]"
            "(https://etherscan.io/address/0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57))\n\n"
            "| description | value |\n| --- | --- |\n| id | 13 |\n\n"
            "## Event logs\n\n"
            "#### 0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57\n\n"
            "| index | event |\n| --- | --- |\n"
            "| 0 | Transfer(from: 0x464C71f6c2F760DdA6093dCB91C24c39e5d6e18c, "
            "to: 0xAA088dfF3dcF619664094945028d44E779F19894, "
            "value: 50,000 [50000000000000000000000, 18 decimals]) |\n"
        )
        out = rac.build(json.dumps({"forum": []}), diff, "no scale-bound flags")
        self.assertNotIn("](https://github.com", out)
        self.assertNotIn("[x]", out)


class RenderPrDescriptionAlertTests(unittest.TestCase):
    def test_empty_list_returns_empty_string(self):
        self.assertEqual(rac.render_pr_description_alert([]), "")

    def test_nonempty_list_renders_warning_block(self):
        out = rac.render_pr_description_alert(["- [ ] unticked box"])
        self.assertIn("[!WARNING]", out)
        self.assertIn("unticked box", out)


class ListingSeedNoteTests(unittest.TestCase):
    DUST_BIN_ADDRESS = "0x897c76905A3d17F71d5ea033916B65154Cf4b4f0"
    OTHER_ADDRESS = "0x1111111111111111111111111111111111111111"
    SEED_WARNING = "> 🟠 In payload but not in the forum post: Listing seed for USDG:"
    SEED_NOTE = "> Listing seed (required for every new listing): Listing seed for USDG:"
    FORUM_LINE = ">   - Forum: Deposit at least $150 USDG to Aave Short Executor"
    NO_FORUM_LINE = ">   - Forum: no seed deposit found in the forum post"

    def _build(self, forum_json, diff=None, book=ADDRESS_BOOK_SLICE):
        diff = diff if diff is not None else _read_fixture("usdg_arbitrum_listing_diff.md")
        return rac.build(forum_json, diff, "no scale-bound flags", "", [], book)

    def test_seed_with_executor_deposit_in_forum_is_a_note_with_the_forum_side(self):
        out = self._build(_read_fixture("usdg_arbitrum_listing_forum_ai_out.json"))
        self.assertIn(self.SEED_NOTE, out)
        self.assertIn(self.FORUM_LINE, out)
        self.assertNotIn("[!WARNING]", out)
        self.assertNotIn("other forum items", out)
        self.assertIn("No mismatches found", out)

    def test_seed_without_executor_deposit_in_forum_is_a_note_saying_so(self):
        out = self._build(json.dumps({"forum": []}))
        self.assertIn(self.SEED_NOTE, out)
        self.assertIn(self.NO_FORUM_LINE, out)
        self.assertNotIn(self.FORUM_LINE, out)
        self.assertNotIn("[!WARNING]", out)

    def test_seed_not_to_dust_bin_stays_a_warning(self):
        diff = _read_fixture("usdg_arbitrum_listing_diff.md").replace(
            self.DUST_BIN_ADDRESS, self.OTHER_ADDRESS
        )
        out = self._build(_read_fixture("usdg_arbitrum_listing_forum_ai_out.json"), diff)
        self.assertIn(self.SEED_WARNING, out)
        self.assertIn("[!WARNING]", out)
        self.assertNotIn(self.SEED_NOTE, out)
        self.assertIn("1 other forum items are not in this payload", out)

    def test_seed_without_address_book_stays_a_warning(self):
        out = self._build(_read_fixture("usdg_arbitrum_listing_forum_ai_out.json"), book=None)
        self.assertIn(self.SEED_WARNING, out)
        self.assertNotIn(self.SEED_NOTE, out)

    def test_forum_deposit_of_a_different_asset_does_not_pair(self):
        forum = json.dumps({"forum": [
            {"action": "Deposit", "asset": "USDC", "amount": "at least $150",
             "recipient": "Aave Short Executor", "network": "Arbitrum"}
        ]})
        out = self._build(forum)
        self.assertIn(self.NO_FORUM_LINE, out)
        self.assertIn("1 other forum items are not in this payload", out)

    def test_forum_deposit_to_a_non_executor_does_not_pair(self):
        forum = json.dumps({"forum": [
            {"action": "Deposit", "asset": "USDG", "amount": "at least $150",
             "recipient": "TokenLogic", "network": "Arbitrum"}
        ]})
        out = self._build(forum)
        self.assertIn(self.NO_FORUM_LINE, out)
        self.assertIn("1 other forum items are not in this payload", out)

    def test_supply_flow_to_collector_on_existing_reserve_stays_a_warning(self):
        diff = _read_fixture("ethereum_february2026_funding_update_diff.md")
        out = self._build(json.dumps({"forum": []}), diff)
        self.assertIn("> 🟠 In payload but not in the forum post: Supply flow for WETH:", out)
        self.assertNotIn("Listing seed", out)

    def test_supply_flow_to_dust_bin_on_existing_reserve_stays_a_warning(self):
        diff = _read_fixture("usdg_arbitrum_listing_diff.md").replace(
            "### Reserves added", "### Reserves altered"
        )
        out = self._build(_read_fixture("usdg_arbitrum_listing_forum_ai_out.json"), diff)
        self.assertIn("> 🟠 In payload but not in the forum post: Supply flow for USDG:", out)
        self.assertNotIn(self.SEED_NOTE, out)
        self.assertNotIn("Listing seed (required for every new listing)", out)

    def test_crafted_seed_with_fake_atoken_mint_stays_a_warning(self):
        attacker = "0x2222222222222222222222222222222222222222"
        executor = "0xFF1137243698CaA18EE364Cc966CF0e02A4e6327"
        usdg = "0x004B506865409877C9fA29bfb1ebA929984B9bbC"
        atoken = "0xf59036CAEBeA7dC4b86638DFA2E3C97dA9FcCd40"
        diff = _read_fixture("usdg_arbitrum_listing_diff.md")
        genuine = (
            f"| 15 | Transfer(from: {executor}, to: {atoken}, value: 150 [150000000, 6 decimals]) |\n"
        )
        self.assertIn(genuine, diff)
        diff = diff.replace(
            genuine,
            genuine + f"| 19 | Transfer(from: {executor}, to: {attacker}, value: 150 [150000000, 6 decimals]) |\n",
        )
        diff += (
            f"\n#### {attacker}\n\n| index | event |\n| --- | --- |\n"
            f"| 20 | Transfer(from: 0x0000000000000000000000000000000000000000, "
            f"to: {self.DUST_BIN_ADDRESS}, value: 150,000,000 [150000000, 0 decimals]) |\n"
        )
        forum = json.dumps({"forum": [
            {"action": "Transfer", "asset": "USDG", "amount": "150", "recipient": atoken},
            {"action": "Mint", "asset": "aArbUSDG", "amount": "150,000,000", "recipient": self.DUST_BIN_ADDRESS},
        ]})
        out = self._build(forum, diff)
        self.assertIn("[!WARNING]", out)
        block = out.split("> [!WARNING]", 1)[1].split("\n\n", 1)[0]
        self.assertIn(attacker, block)
        self.assertIn(self.SEED_NOTE, out)
        self.assertNotIn(attacker, out.split(self.SEED_NOTE, 1)[1].split("\n\n", 1)[0])
        self.assertNotIn("No mismatches found", out)

    def test_seed_with_wrong_mint_amount_stays_a_warning(self):
        original = _read_fixture("usdg_arbitrum_listing_diff.md")
        diff = original.replace(
            "value: 150,000,000 [150000000, 0 decimals]) |\n| 17 |",
            "value: 149,999,999 [149999999, 0 decimals]) |\n| 17 |",
        )
        self.assertNotEqual(diff, original)
        out = self._build(_read_fixture("usdg_arbitrum_listing_forum_ai_out.json"), diff)
        self.assertNotIn(self.SEED_NOTE, out)
        self.assertIn("[!WARNING]", out)

    def test_seed_from_a_non_pool_emitter_stays_a_warning(self):
        real_pool = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
        fake_pool = "0x3333333333333333333333333333333333333333"
        original = _read_fixture("usdg_arbitrum_listing_diff.md")
        section = f"#### {real_pool} (AaveV3Arbitrum.POOL)"
        spender = f"spender: {real_pool}, value: 150 [150000000, 6 decimals]"
        self.assertIn(section, original)
        self.assertIn(spender, original)
        diff = original.replace(section, f"#### {fake_pool}").replace(spender, spender.replace(real_pool, fake_pool))
        self.assertNotEqual(diff, original)
        out = self._build(_read_fixture("usdg_arbitrum_listing_forum_ai_out.json"), diff)
        self.assertNotIn(self.SEED_NOTE, out)
        self.assertIn("[!WARNING]", out)

    def _two_seed_flow_diff(self):
        executor = "0xFF1137243698CaA18EE364Cc966CF0e02A4e6327"
        pool = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
        atoken = "0xf59036CAEBeA7dC4b86638DFA2E3C97dA9FcCd40"
        zero = "0x0000000000000000000000000000000000000000"
        value = "1,000,000 [1000000000000, 6 decimals]"
        diff = _read_fixture("usdg_arbitrum_listing_diff.md")
        anchors = {
            "atoken": "| 17 | Mint(caller",
            "pool": "\n#### 0x004B506865409877C9fA29bfb1ebA929984B9bbC\n",
            "usdg": f"| 15 | Transfer(from: {executor}, to: {atoken}, value: 150 [150000000, 6 decimals]) |\n",
        }
        for anchor in anchors.values():
            self.assertEqual(diff.count(anchor), 1)
        diff = diff.replace(
            anchors["usdg"],
            anchors["usdg"]
            + f"| 21 | Approval(owner: {executor}, spender: {pool}, value: {value}) |\n"
            + f"| 23 | Transfer(from: {executor}, to: {atoken}, value: {value}) |\n",
        )
        mint_row = next(line for line in diff.splitlines() if line.startswith(anchors["atoken"]))
        diff = diff.replace(
            mint_row + "\n",
            mint_row + "\n"
            + f"| 24 | Transfer(from: {zero}, to: {self.DUST_BIN_ADDRESS}, value: 1,000,000,000,000 [1000000000000, 0 decimals]) |\n",
        )
        supply_row = next(line for line in diff.splitlines() if line.startswith("| 18 | Supply("))
        diff = diff.replace(
            supply_row + "\n",
            supply_row + "\n"
            + supply_row.replace("| 18 |", "| 22 |").replace("amount: 150 [150000000, 6 decimals]", f"amount: {value}")
            + "\n",
        )
        return diff

    def test_second_seed_supply_of_the_same_reserve_stays_a_warning(self):
        out = self._build(_read_fixture("usdg_arbitrum_listing_forum_ai_out.json"), self._two_seed_flow_diff())
        self.assertEqual(out.count(self.SEED_NOTE), 0)
        warning = out.split("> [!WARNING]", 1)[1].split("\n\n", 1)[0]
        self.assertIn("1,000,000", warning)
        self.assertNotIn("No mismatches found", out)

    def test_forum_that_explains_the_genuine_seed_cannot_promote_a_second_seed(self):
        executor = "0xFF1137243698CaA18EE364Cc966CF0e02A4e6327"
        pool = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
        usdg = "0x004B506865409877C9fA29bfb1ebA929984B9bbC"
        atoken = "0xf59036CAEBeA7dC4b86638DFA2E3C97dA9FcCd40"
        forum = json.dumps({"forum": [
            {"action": "Approve", "asset": "USDG", "amount": "150", "recipient": pool},
            {"action": "Supply", "asset": "USDG", "amount": "150", "recipient": usdg},
            {"action": "Transfer", "asset": "USDG", "amount": "150", "recipient": atoken},
            {"action": "Mint", "asset": "aArbUSDG", "amount": "150,000,000", "recipient": self.DUST_BIN_ADDRESS},
        ]})
        out = self._build(forum, self._two_seed_flow_diff())
        self.assertEqual(out.count(self.SEED_NOTE), 0)
        warning = out.split("> [!WARNING]", 1)[1].split("\n\n", 1)[0]
        self.assertIn("1,000,000", warning)
        self.assertNotIn("No mismatches found", out)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import address_book
import diff_parser
import readable_actions
import spec_compare as sc


class LeadingNumberScaleSuffixTests(unittest.TestCase):
    def test_m_suffix_expands_to_millions(self):
        self.assertEqual(sc._leading_number("0.5M"), 500_000.0)
        self.assertEqual(sc._leading_number("8M"), 8_000_000.0)

    def test_k_suffix_expands_to_thousands(self):
        self.assertEqual(sc._leading_number("150K"), 150_000.0)

    def test_no_suffix_is_unscaled(self):
        self.assertEqual(sc._leading_number("50,000"), 50_000.0)
        self.assertEqual(sc._leading_number("0.5"), 0.5)

    def test_word_starting_with_suffix_letter_is_not_mistaken_for_a_scale(self):
        # "150 Kraken" must not be read as 150 * 1000
        self.assertEqual(sc._leading_number("150 Kraken tokens"), 150.0)

    def test_scale_mismatch_flagged_as_a_warning(self):
        # forum says 0.5M, payload (misapplied decimals) decodes to 0.5 -- a
        # real 1,000,000x scale bug that a naive leading-digit compare misses.
        forum = [{"action": "Approve", "asset": "aEthLidoGHO", "amount": "0.5M",
                  "recipient": "ALC 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b", "network": "Ethereum"}]
        payload = [{"amount": "0.5", "recipient": "0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b", "decimals": 6}]
        out = sc.compare(forum, payload)
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("amount", out["warnings"][0]["detail"])


class CompareTests(unittest.TestCase):
    def test_matching_amount_and_recipient_is_clean(self):
        forum = [{"action": "Reimburse", "asset": "aEthLidoGHO", "amount": "50,000",
                  "recipient": "TokenLogic 0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}]
        payload = [{"amount": "50,000", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["unexplained"], [])
        self.assertEqual(out["forum_only_count"], 0)

    def test_amount_mismatch_on_matched_recipient_is_a_warning(self):
        forum = [{"action": "Reimburse", "asset": "aEthLidoGHO", "amount": "50,000",
                  "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}]
        payload = [{"amount": "35,000", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("amount", out["warnings"][0]["detail"])
        self.assertEqual(out["unexplained"], [])

    def test_payload_item_with_no_forum_counterpart_is_unexplained(self):
        forum = []
        payload = [{"amount": "50,000", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(len(out["unexplained"]), 1)
        self.assertEqual(out["warnings"], [])

    def test_forum_items_with_no_payload_counterpart_are_counted_not_warned(self):
        forum = [
            {"action": "Acquire", "asset": "GHO", "amount": "8M", "recipient": None, "network": "Ethereum"},
            {"action": "Refresh Allowance", "asset": "USDC", "amount": None, "recipient": "MainnetSwapSteward", "network": "Ethereum"},
        ]
        payload = []
        out = sc.compare(forum, payload)
        self.assertEqual(out["forum_only_count"], 2)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["unexplained"], [])

    def test_no_matching_recipient_address_goes_to_unexplained_despite_same_amount(self):
        # same amount coincidentally, but payload recipient has an address that
        # doesn't match any forum address -> goes to unexplained, not warnings,
        # since matching is address-driven.
        forum = [{"action": "Reimburse", "asset": "aEthLidoGHO", "amount": "50,000",
                  "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}]
        payload = [{"amount": "50,000", "recipient": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(len(out["unexplained"]), 1)

    def test_address_matching_is_case_insensitive(self):
        # forum text carries a checksummed address, the payload's decoded
        # address is lowercase -- they must still match as the same recipient.
        forum = [{"action": "Reimburse", "asset": "aEthLidoGHO", "amount": "50,000",
                  "recipient": "TokenLogic 0xAA088dfF3dcF619664094945028d44E779F19894",
                  "network": "Ethereum"}]
        payload = [{"amount": "50,000",
                    "recipient": "0xaa088dff3dcf619664094945028d44e779f19894", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["unexplained"], [])

    def test_no_recipient_address_on_payload_side_is_unexplained(self):
        forum = [{"action": "Reimburse", "asset": "GHO", "amount": "50,000", "recipient": None, "network": "Ethereum"}]
        payload = [{"amount": "50,000", "recipient": None, "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(len(out["unexplained"]), 1)


class FormulaAmountTests(unittest.TestCase):
    def test_formula_amount_is_not_compared_and_produces_a_note_not_a_warning(self):
        forum = [{
            "action": "Refresh Allowance", "asset": "USDC",
            "amount": "currentAllowance + 50,500 / 4 + emissionPerSecond x (block.timestamp - snapshot + 90 days)",
            "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum",
        }]
        payload = [{"amount": "71,532.10", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 6}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["unexplained"], [])
        self.assertEqual(len(out["notes"]), 1)
        self.assertIn("formula", out["notes"][0]["detail"])

    def test_plain_literal_amount_is_not_treated_as_a_formula(self):
        forum = [{"action": "Reimburse", "asset": "aEthLidoGHO", "amount": "50,000",
                  "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}]
        payload = [{"amount": "50,000", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["notes"], [])
        self.assertEqual(out["warnings"], [])

    def test_amount_with_a_token_symbol_is_not_a_formula_and_mismatches_are_still_caught(self):
        # A token symbol (GHO, USDC, aEthWBTC, ...) trailing the number is
        # not an identifier -- it must not suppress a real mismatch.
        forum = [{"action": "Reimburse", "asset": "GHO", "amount": "50,000 GHO",
                  "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}]
        payload = [{"amount": "35,000", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["notes"], [])
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("amount", out["warnings"][0]["detail"])

    def test_scaled_amount_with_a_token_symbol_is_not_a_formula(self):
        forum = [{"action": "Reimburse", "asset": "USDC", "amount": "1.5M USDC",
                  "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}]
        payload = [{"amount": "1,500,000", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 6}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["notes"], [])
        self.assertEqual(out["warnings"], [])

    def test_bare_token_symbol_amount_is_not_a_formula(self):
        forum = [{"action": "Reimburse", "asset": "aEthWBTC", "amount": "72 aEthWBTC",
                  "recipient": "0xAA2461f0f0A3dE5fEAF3273eAe16DEF861cf594e", "network": "Ethereum"}]
        payload = [{"amount": "72", "recipient": "0xAA2461f0f0A3dE5fEAF3273eAe16DEF861cf594e", "decimals": 8}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["notes"], [])
        self.assertEqual(out["warnings"], [])

    def test_multi_word_identifier_formula_still_produces_a_note(self):
        forum = [{"action": "Reimburse", "asset": "stkAAVE", "amount": "Current Balance + buffer",
                  "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}]
        payload = [{"amount": "1,000", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(len(out["notes"]), 1)

    def test_amount_with_a_trailing_time_range_is_compared_not_treated_as_a_formula(self):
        forum = [{"action": "Reimburse", "asset": "GHO", "amount": "10,000,000 GHO over 3 months",
                  "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}]
        payload = [{"amount": "10,000,000", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["notes"], [])
        self.assertEqual(out["warnings"], [])

    def test_amount_with_an_unspaced_rate_slash_is_compared_not_treated_as_a_formula(self):
        forum = [{"action": "Reimburse", "asset": "GHO", "amount": "50k GHO/month",
                  "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}]
        payload = [{"amount": "35,000", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["notes"], [])
        self.assertEqual(len(out["warnings"]), 1)

    def test_amount_with_parenthesized_symbol_is_compared_not_treated_as_a_formula(self):
        forum = [{"action": "Reimburse", "asset": "GHO", "amount": "50,000 (GHO)",
                  "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "network": "Ethereum"}]
        payload = [{"amount": "50,000", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894", "decimals": 18}]
        out = sc.compare(forum, payload)
        self.assertEqual(out["notes"], [])
        self.assertEqual(out["warnings"], [])


class ForumOnlyTests(unittest.TestCase):
    def test_returns_unmatched_forum_items_and_count_equals_their_length(self):
        matched = {"action": "Reimburse", "asset": "GHO", "amount": "5",
                   "recipient": "TL 0xAA088dfF3dcF619664094945028d44E779F19894"}
        stray = {"action": "Deposit", "asset": "USDG", "amount": "at least $150",
                 "recipient": "Aave Short Executor"}
        payload = [{"amount": "5", "recipient": "0xAA088dfF3dcF619664094945028d44E779F19894"}]
        out = sc.compare([matched, stray], payload)
        self.assertEqual(out["forum_only"], [stray])
        self.assertEqual(out["forum_only_count"], 1)


class AddressPairingTests(unittest.TestCase):
    SAFE = "0x22740deBa78d5a0c24C58C740e3715ec29de1bFa"
    GHO_A = "0xb77E872A68C62CfC0dFb02C067Ecc3DA23B4bbf3"
    GHO_B = "0xAd571979b4245E163A7E2119EB4dFd94AfDaebC5"

    def _forum(self, network, asset, amount, asset_address=None):
        return {"action": "Create Allowance", "kind": "allowance", "asset": asset, "asset_address": asset_address,
                "amount": amount, "recipient": f"AFC {self.SAFE}", "network": network}

    def _approval(self, chain, token, amount, asset="aGHO"):
        return {"event_name": "Approval", "chain": chain, "asset": asset, "amount": amount,
                "recipient": self.SAFE, "section": token.lower()}

    def test_multi_chain_funding_update_pairs_every_allowance_to_the_afc(self):
        diff = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_fixtures",
                                 "multichain_november2026_funding_update_diff.md"), encoding="utf-8").read()
        _, symbol_map = address_book.build_maps(diff)
        payload = readable_actions.fold_flows(diff_parser.parse_payload_actions(diff), symbol_map)
        forum = [
            self._forum("Plasma", "GHO", "1,000,000", "0xb77E872A68C62CfC0dFb02C067Ecc3DA23B4bbf3"),
            self._forum("Plasma", "aPlaGHO", "1,000,000", "0xAd571979b4245E163A7E2119EB4dFd94AfDaebC5"),
            self._forum("Monad", "GHO", "250,000", "0xfc421aD3C883Bf9E7C4f42dE845C4e4405799e73"),
            self._forum("Monad", "aMonGHO", "250,000", "0x4586face17B0e3D4d51EcABb4B4EBC2354b61b0D"),
            self._forum("Arbitrum", "GHO", "50,000", "0x7dfF72693f6A4149b17e7C6314655f6A9F7c8B33"),
            self._forum("Mantle", "aManUSDT0", "570,000", "0x7053bAD224F0C021839f6AC645BdaE5F8b585b69"),
            self._forum("Mantle", "aManWETH", "59", "0xeAC30Ed8609F564aE65C809C4bf42dB2fF426D2C"),
            self._forum("Gnosis", "aGnoWXDAI", "305,000", "0xd0Dd6cEF72143E22cCED4867eb0d5F2328715533"),
            self._forum("Gnosis", "aGnoUSDC", "90,000", "0xc6B7AcA6DE8a6044E0e32d0c841a89244A10D284"),
            self._forum("Gnosis", "aGnoUSDCe", "41,000", "0xC0333cb85B59a788d8C7CAe5e1Fd6E229A3E5a65"),
            self._forum("Sonic", "aSonUSDC", "100,000", "0x578Ee1ca3a8E1b54554Da1Bf7C583506C4CD11c6"),
        ]
        out = sc.compare(forum, payload)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["forum_only"], [])
        paired_to_the_afc = [p for p in payload if p.get("event_name") == "Approval" and p["recipient"] == self.SAFE]
        self.assertEqual(len(paired_to_the_afc), 11)
        self.assertEqual([p for p in out["unexplained"] if p in paired_to_the_afc], [])

    def test_pool_event_section_is_the_pool_so_the_token_address_is_not_compared(self):
        recipient = "0x0DDE46b923eB74F1860727914f179e82b9eE47B9"
        usdc = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
        diff = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_fixtures",
                                 "multichain_november2026_funding_update_diff.md"), encoding="utf-8").read()
        items = [p for p in diff_parser.parse_payload_actions(diff)
                 if p["recipient"] == recipient and p["event_name"] in ("Withdraw", "Transfer")]
        self.assertEqual([p["event_name"] for p in items], ["Withdraw", "Transfer"])
        forum = [{"action": "Transfer", "kind": "movement", "asset": "USDC", "asset_address": usdc,
                  "amount": "1,000", "recipient": recipient, "network": "Ethereum"}]
        out = sc.compare(forum, items)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["forum_only"], [])
        self.assertNotIn(items[0], out["unexplained"])

    def test_swapped_amounts_on_one_network_are_two_warnings(self):
        forum = [self._forum("Plasma", "GHO", "1,000,000", self.GHO_A),
                 self._forum("Plasma", "aPlaGHO", "500,000", self.GHO_B)]
        payload = [self._approval("Plasma", self.GHO_A, "500,000"), self._approval("Plasma", self.GHO_B, "1,000,000")]
        out = sc.compare(forum, payload)
        self.assertEqual(len(out["warnings"]), 2)

    def test_same_recipient_with_a_different_token_address_is_unexplained_not_a_warning(self):
        out = sc.compare([self._forum("Plasma", "GHO", "1,000,000", self.GHO_A)],
                         [self._approval("Plasma", self.GHO_B, "50,000")])
        self.assertEqual(out["warnings"], [])
        self.assertEqual(len(out["unexplained"]), 1)

    def test_forum_item_without_an_asset_address_still_pairs_and_prefers_the_same_network(self):
        forum = [self._forum("Plasma", "GHO", "1,000,000"), self._forum("Monad", "GHO", "250,000")]
        out = sc.compare(forum, [self._approval("Monad", self.GHO_A, "250,000")])
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["forum_only"], [forum[0]])


class AmountMatchTests(unittest.TestCase):
    GHO_65M = {"amount": "65,000,000", "asset": "GHO", "recipient": "0x15f22f39FD7b3612840cF0De49b6f9C4879Aa642"}

    def _forum(self, recipient, network, asset="GHO", amount="65M"):
        return {"action": "Transfer", "kind": "movement", "asset": asset, "amount": amount, "recipient": recipient, "network": network}

    def test_named_recipient_matches_on_asset_and_amount_and_is_reported_as_unproven(self):
        forum = [self._forum("GHO Reserve", "Avalanche")]
        out = sc.compare(forum, [dict(self.GHO_65M, chain="Avalanche")])
        self.assertEqual(out["unexplained"], [])
        self.assertEqual(out["forum_only_count"], 0)
        self.assertEqual(len(out["amount_matches"]), 1)
        self.assertEqual(out["amount_matches"][0]["forum"]["recipient"], "GHO Reserve")

    def test_same_network_forum_item_is_preferred(self):
        forum = [self._forum(None, "Ethereum"), self._forum("GHO Reserve", "Avalanche")]
        out = sc.compare(forum, [dict(self.GHO_65M, chain="Avalanche")])
        self.assertEqual(out["amount_matches"][0]["forum"]["network"], "Avalanche")

    def test_other_asset_or_amount_does_not_match(self):
        for forum_item in (self._forum("GHO Reserve", "Avalanche", asset="USDC"),
                           self._forum("GHO Reserve", "Avalanche", amount="6.5M")):
            with self.subTest(forum_item=forum_item):
                out = sc.compare([forum_item], [dict(self.GHO_65M, chain="Avalanche")])
                self.assertEqual(len(out["unexplained"]), 1)
                self.assertEqual(out["amount_matches"], [])

    def test_forum_item_with_an_address_never_matches_on_amount_alone(self):
        forum = [self._forum("0x1111111111111111111111111111111111111111", "Avalanche")]
        out = sc.compare(forum, [dict(self.GHO_65M, chain="Avalanche")])
        self.assertEqual(len(out["unexplained"]), 1)

    def test_payload_item_without_an_asset_never_matches_on_amount(self):
        forum = [self._forum("GHO Reserve", "Avalanche")]
        out = sc.compare(forum, [dict(self.GHO_65M, asset=None)])
        self.assertEqual(len(out["unexplained"]), 1)

    def test_a_movement_and_an_approval_never_explain_each_other(self):
        approval = dict(self.GHO_65M, chain="Avalanche", event_name="Approval")
        out = sc.compare([self._forum("GHO Reserve", "Avalanche")], [approval])
        self.assertEqual(out["unexplained"], [approval])
        self.assertEqual(out["amount_matches"], [])
        forum_approve = dict(self._forum("GHO Reserve", "Avalanche"), action="Approve", kind="allowance")
        transfer = dict(self.GHO_65M, chain="Avalanche", event_name="Transfer")
        out = sc.compare([forum_approve], [transfer])
        self.assertEqual(out["unexplained"], [transfer])
        out = sc.compare([forum_approve], [approval])
        self.assertEqual(len(out["amount_matches"]), 1)

    def test_the_forum_kind_field_decides_allowance_or_movement(self):
        approval = dict(self.GHO_65M, chain="Avalanche", event_name="Approval")
        transfer = dict(self.GHO_65M, chain="Avalanche", event_name="Transfer")
        refresh = dict(self._forum("GHO Reserve", "Avalanche"), action="Refresh Allowance", kind="allowance")
        self.assertEqual(len(sc.compare([refresh], [approval])["amount_matches"]), 1)
        self.assertEqual(sc.compare([refresh], [transfer])["unexplained"], [transfer])
        no_kind = {k: v for k, v in self._forum("GHO Reserve", "Avalanche").items() if k != "kind"}
        self.assertEqual(sc.compare([no_kind], [transfer])["unexplained"], [transfer])


if __name__ == "__main__":
    unittest.main()

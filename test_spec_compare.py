import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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


if __name__ == "__main__":
    unittest.main()

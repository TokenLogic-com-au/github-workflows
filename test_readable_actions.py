import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import address_book as ab
import diff_parser as dp
import readable_actions as ra

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_fixtures")


def _read_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


class DescribeActionPatternTests(unittest.TestCase):
    def test_approval_names_owner_spender_token_and_amount(self):
        item = {
            "event_name": "Approval",
            "amount": "100",
            "decimals": 6,
            "recipient": "0xPOOL",
            "counterparty": "0xEXEC",
            "section": "0xreserve",
            "inline_symbol": None,
        }
        label_map = {"0xpool": "POOL", "0xexec": "EXECUTOR"}
        symbol_map = {"0xreserve": "PT-AUSD-17DEC2026"}
        self.assertEqual(
            ra.describe_action(item, label_map, symbol_map),
            "Approval: EXECUTOR approves POOL to spend 100 PT-AUSD-17DEC2026",
        )

    def test_zero_value_approval_renders_as_a_reset(self):
        item = {
            "event_name": "Approval",
            "amount": "0",
            "decimals": 6,
            "recipient": "0xPOOL",
            "counterparty": "0xEXEC",
            "section": "0xreserve",
            "inline_symbol": None,
        }
        label_map = {"0xpool": "POOL", "0xexec": "EXECUTOR"}
        out = ra.describe_action(item, label_map, {})
        self.assertEqual(out, "Approval: EXECUTOR resets POOL's allowance to 0")

    def test_transfer_names_sender_and_receiver(self):
        item = {
            "event_name": "Transfer",
            "amount": "50,000",
            "decimals": 18,
            "recipient": "0xTO",
            "counterparty": "0xFROM",
            "section": "0xtoken",
            "inline_symbol": None,
        }
        symbol_map = {"0xtoken": "GHO"}
        out = ra.describe_action(item, {"0xto": "COLLECTOR", "0xfrom": "EXECUTOR"}, symbol_map)
        self.assertEqual(out, "Transfer: 50,000 GHO from EXECUTOR to COLLECTOR")

    def test_from_zero_transfer_renders_as_a_mint(self):
        item = {
            "event_name": "Transfer",
            "amount": "100",
            "decimals": 6,
            "recipient": "0xBEN",
            "counterparty": "0x0000000000000000000000000000000000000000",
            "section": "0xatoken",
            "inline_symbol": None,
        }
        symbol_map = {"0xatoken": "aWETH"}
        out = ra.describe_action(item, {"0xben": "DUST_BIN"}, symbol_map)
        self.assertEqual(out, "Mint: 100 aWETH to DUST_BIN")

    def test_supply_names_the_beneficiary(self):
        item = {
            "event_name": "Supply",
            "amount": "100",
            "decimals": 6,
            "recipient": "0xreserve",
            "on_behalf_of": "0xBEN",
            "section": "0xpool",
            "inline_symbol": "PT-AUSD-17DEC2026",
        }
        out = ra.describe_action(item, {"0xben": "DUST_BIN"}, {})
        self.assertEqual(out, "Supply: 100 PT-AUSD-17DEC2026 supplied on behalf of DUST_BIN")

    def test_cap_changed_event_names_the_cap_kind_symbol_and_new_value(self):
        item = {
            "event_name": "BorrowCapChanged",
            "amount": "1",
            "decimals": None,
            "recipient": "0xasset",
            "section": "0xconfigurator",
            "inline_symbol": "PT-AUSD-17DEC2026",
        }
        out = ra.describe_action(item, {}, {})
        self.assertEqual(out, "Borrow cap on PT-AUSD-17DEC2026 set to 1")

    def test_reserve_data_updated_is_labelled_as_not_a_payment(self):
        item = {
            "event_name": "ReserveDataUpdated",
            "amount": "1",
            "decimals": 27,
            "recipient": "0xasset",
            "section": "0xpool",
            "inline_symbol": "PT-AUSD-17DEC2026",
        }
        out = ra.describe_action(item, {}, {})
        self.assertEqual(out, "PT-AUSD-17DEC2026 rate/index update (not a payment): 1 PT-AUSD-17DEC2026")

    def test_unknown_event_still_gets_a_generic_readable_line(self):
        item = {
            "event_name": "SomeNewEvent",
            "amount": "42",
            "decimals": 8,
            "recipient": "0xthing",
            "section": "0xthing",
            "inline_symbol": None,
        }
        out = ra.describe_action(item, {"0xthing": "SOME_CONTRACT"}, {})
        self.assertEqual(out, "SomeNewEvent: 42 (raw), contract SOME_CONTRACT")

    def test_amount_says_raw_when_decimals_are_zero(self):
        item = {
            "event_name": "Transfer",
            "amount": "100,000,000",
            "decimals": 0,
            "recipient": "0xben",
            "counterparty": "0x0000000000000000000000000000000000000000",
            "section": "0xatoken",
            "inline_symbol": None,
        }
        symbol_map = {"0xatoken": "aMonPT_AUSD_17DEC2026"}
        out = ra.describe_action(item, {}, symbol_map)
        self.assertIn("(raw, decimals unknown)", out)


class ListingSeedGroupingTests(unittest.TestCase):
    def test_pr231_fixture_groups_the_seed_into_one_summary_with_four_sub_lines(self):
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        items = dp.parse_payload_actions(text)
        label_map, symbol_map = ab.build_maps(text)
        new_reserves = ab.new_reserve_symbols(text)
        findings = ra.build_readable_findings(items, label_map, symbol_map, new_reserves)

        self.assertEqual(len(items), 6)
        seed = next(f for f in findings if f["sub_lines"])
        self.assertTrue(seed["line"].startswith("Listing seed for PT-AUSD-17DEC2026:"))
        self.assertEqual(len(seed["sub_lines"]), 4)
        # every item is covered exactly once: 4 grouped + 2 standalone
        self.assertEqual(len(findings), 3)
        self.assertEqual(sum(len(f["sub_lines"]) or 1 for f in findings), 6)

    def test_existing_reserve_supply_flow_is_not_mislabelled_as_a_listing(self):
        # Same approve->supply->mint shape as a listing seed, but on an
        # ALREADY-listed reserve (no "Reserves added" section) -- must be
        # worded as an ordinary supply flow, not a "Listing seed".
        text = _read_fixture("ethereum_february2026_funding_update_diff.md")
        items = dp.parse_payload_actions(text)
        label_map, symbol_map = ab.build_maps(text)
        new_reserves = ab.new_reserve_symbols(text)
        self.assertEqual(new_reserves, set())
        findings = ra.build_readable_findings(items, label_map, symbol_map, new_reserves)
        seed = next(f for f in findings if f["sub_lines"])
        self.assertTrue(seed["line"].startswith("Supply flow for WETH:"))
        self.assertNotIn("Listing seed", seed["line"])

    def test_no_seed_shape_present_yields_no_groups(self):
        items = [
            {
                "event_name": "Approval",
                "amount": "100",
                "decimals": 18,
                "recipient": "0xspender",
                "counterparty": "0xowner",
                "section": "0xtoken",
                "inline_symbol": None,
                "on_behalf_of": None,
            }
        ]
        findings = ra.build_readable_findings(items, {}, {})
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["sub_lines"], [])


if __name__ == "__main__":
    unittest.main()

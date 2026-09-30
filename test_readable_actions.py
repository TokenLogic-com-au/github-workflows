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
            "Approval: `EXECUTOR` (0xEXEC) approves `POOL` (0xPOOL) to spend 100 `PT-AUSD-17DEC2026`",
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
        self.assertEqual(out, "Approval: `EXECUTOR` (0xEXEC) resets `POOL` (0xPOOL)'s allowance to 0")

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
        self.assertEqual(
            out, "Transfer: 50,000 `GHO` from `EXECUTOR` (0xFROM) to `COLLECTOR` (0xTO)"
        )

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
        self.assertEqual(out, "Mint: 100 `aWETH` to `DUST_BIN` (0xBEN)")

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
        self.assertEqual(
            out, "Supply: 100 `PT-AUSD-17DEC2026` supplied on behalf of `DUST_BIN` (0xBEN)"
        )

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
        self.assertEqual(out, "SomeNewEvent: 42, contract `SOME_CONTRACT` (0xthing)")

    def test_amount_says_raw_only_when_decimals_are_zero(self):
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

    def test_known_decimals_amount_with_no_symbol_is_not_called_raw(self):
        # Watched-fail: 5,000,000 at 6 decimals is already a correctly
        # scaled human amount (diff_parser's own "human" group) -- it must
        # never be shown as "5,000,000 (raw)" just because no token symbol
        # is known for it.
        item = {
            "event_name": "Transfer",
            "amount": "5,000,000",
            "decimals": 6,
            "recipient": "0xben",
            "counterparty": "0xfrom",
            "section": "0xtoken",
            "inline_symbol": None,
        }
        out = ra.describe_action(item, {}, {})
        self.assertIn("5,000,000", out)
        self.assertNotIn("raw", out)


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
        self.assertIn("`EXECUTOR`", seed["line"])
        self.assertIn("supplies 100 `PT-AUSD-17DEC2026`", seed["line"])
        self.assertIn("minting 100,000,000", seed["line"])
        self.assertEqual(len(seed["sub_lines"]), 4)
        # every item is covered exactly once: 4 grouped + 1 approval reset;
        # the 1 ReserveDataUpdated item is omitted by design (see
        # build_readable_findings' own docstring / test_render_advisory_comment
        # for the separately-reported omitted count)
        self.assertEqual(len(findings), 2)

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

    def test_reserve_data_updated_items_are_omitted_from_findings(self):
        items = [
            {
                "event_name": "ReserveDataUpdated",
                "amount": "1",
                "decimals": 27,
                "recipient": "0xasset",
                "section": "0xpool",
                "inline_symbol": "WETH",
                "counterparty": None,
                "on_behalf_of": None,
            }
        ]
        findings = ra.build_readable_findings(items, {}, {})
        self.assertEqual(findings, [])

    def _seed_items(self, amount="100", decimals=6, wrong_approval=None):
        """A minimal, synthetic but structurally faithful approve -> supply
        -> transfer -> mint chain, built directly as diff_parser-shaped
        dicts (not through diff_parser itself) so the negative-control
        decoy approval below can be inserted precisely."""
        reserve = "0xReserve0000000000000000000000000000001"
        pool = "0xPool00000000000000000000000000000000002"
        a_token_addr = "0xAReceiver000000000000000000000000000003"
        payer = "0xPayer000000000000000000000000000000004"
        beneficiary = "0xBeneficiary0000000000000000000000000005"
        items = []
        if wrong_approval:
            items.append(wrong_approval)
        items.append(
            {
                "event_name": "Approval",
                "amount": amount,
                "decimals": decimals,
                "recipient": pool,
                "counterparty": payer,
                "section": reserve,
                "inline_symbol": None,
                "on_behalf_of": None,
            }
        )
        items.append(
            {
                "event_name": "Supply",
                "amount": amount,
                "decimals": decimals,
                "recipient": reserve,
                "section": pool,
                "on_behalf_of": beneficiary,
                "user": payer,
                "inline_symbol": "WETH",
                "counterparty": None,
            }
        )
        items.append(
            {
                "event_name": "Transfer",
                "amount": amount,
                "decimals": decimals,
                "recipient": a_token_addr,
                "counterparty": payer,
                "section": reserve,
                "inline_symbol": None,
                "on_behalf_of": None,
            }
        )
        items.append(
            {
                "event_name": "Transfer",
                "amount": amount,
                "decimals": decimals,
                "recipient": beneficiary,
                "counterparty": "0x0000000000000000000000000000000000000000",
                "section": a_token_addr,
                "inline_symbol": None,
                "on_behalf_of": None,
            }
        )
        return items, reserve, pool, a_token_addr, payer, beneficiary

    def test_synthetic_seed_groups_correctly_by_pool_payer_and_amount(self):
        items, *_ = self._seed_items()
        findings = ra.build_readable_findings(items, {}, {})
        self.assertEqual(len(findings), 1)
        self.assertEqual(len(findings[0]["sub_lines"]), 4)

    def test_extra_decoy_approval_with_wrong_spender_and_amount_stays_its_own_finding(self):
        # Negative control: an Approval(EXECUTOR/payer -> 0xdead..., a
        # DIFFERENT amount) placed BEFORE the real Pool approval must not be
        # swept into the group, and the real Pool approval must still be
        # found and grouped.
        decoy = {
            "event_name": "Approval",
            "amount": "5,000,000",
            "decimals": 6,
            "recipient": "0xdEaDdEaDdEaDdEaDdEaDdEaDdEaDdEaDdEaDdEaD",
            "counterparty": "0xPayer000000000000000000000000000000004",
            "section": "0xReserve0000000000000000000000000000001",
            "inline_symbol": None,
            "on_behalf_of": None,
        }
        items, reserve, pool, a_token_addr, payer, beneficiary = self._seed_items(wrong_approval=decoy)
        findings = ra.build_readable_findings(items, {}, {})

        seed = next(f for f in findings if f["sub_lines"])
        self.assertEqual(len(seed["sub_lines"]), 4)
        self.assertIn(pool, seed["sub_lines"][0])  # the real Approval's spender
        self.assertIn("5,000,000", "".join(f["line"] for f in findings if not f["sub_lines"]))
        standalone = [f for f in findings if not f["sub_lines"]]
        self.assertEqual(len(standalone), 1)
        self.assertIn("0xdEaDdEaDdEaDdEaDdEaDdEaDdEaDdEaDdEaDdEaD", standalone[0]["line"])

    def test_approval_with_wrong_owner_is_not_grouped(self):
        # Approval on the right section/spender/amount but from a DIFFERENT
        # owner than the Supply's payer -- must not be grouped.
        wrong_owner_approval = {
            "event_name": "Approval",
            "amount": "100",
            "decimals": 6,
            "recipient": "0xPool00000000000000000000000000000000002",
            "counterparty": "0xSomeoneElse000000000000000000000000006",
            "section": "0xReserve0000000000000000000000000000001",
            "inline_symbol": None,
            "on_behalf_of": None,
        }
        # Build items WITHOUT the correct approval at all, so only the
        # wrong-owner one is present -- the group must form with no
        # approval sub-line (approval is optional), not adopt this one.
        reserve = "0xReserve0000000000000000000000000000001"
        pool = "0xPool00000000000000000000000000000000002"
        a_token_addr = "0xAReceiver000000000000000000000000000003"
        payer = "0xPayer000000000000000000000000000000004"
        beneficiary = "0xBeneficiary0000000000000000000000000005"
        items = [
            wrong_owner_approval,
            {
                "event_name": "Supply",
                "amount": "100",
                "decimals": 6,
                "recipient": reserve,
                "section": pool,
                "on_behalf_of": beneficiary,
                "user": payer,
                "inline_symbol": "WETH",
                "counterparty": None,
            },
            {
                "event_name": "Transfer",
                "amount": "100",
                "decimals": 6,
                "recipient": a_token_addr,
                "counterparty": payer,
                "section": reserve,
                "inline_symbol": None,
                "on_behalf_of": None,
            },
            {
                "event_name": "Transfer",
                "amount": "100",
                "decimals": 6,
                "recipient": beneficiary,
                "counterparty": "0x0000000000000000000000000000000000000000",
                "section": a_token_addr,
                "inline_symbol": None,
                "on_behalf_of": None,
            },
        ]
        findings = ra.build_readable_findings(items, {}, {})
        seed = next(f for f in findings if f["sub_lines"])
        # only Supply + Transfer + Mint grouped (3), the wrong-owner
        # Approval stays its own finding
        self.assertEqual(len(seed["sub_lines"]), 3)
        standalone = [f for f in findings if not f["sub_lines"]]
        self.assertEqual(len(standalone), 1)
        self.assertIn("0xSomeoneElse000000000000000000000000006", standalone[0]["line"])


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diff_parser as dp


class ParsePayloadActionsTests(unittest.TestCase):
    def test_empty_text_returns_empty_list(self):
        self.assertEqual(dp.parse_payload_actions(""), [])
        self.assertEqual(dp.parse_payload_actions("   \n  "), [])

    def test_extracts_decoded_value_and_address(self):
        line = "Transfer to 0xAA088dfF3dcF619664094945028d44E779F19894: value: 50,000 [50000000000000000000000, 18 decimals]"
        out = dp.parse_payload_actions(line)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["amount"], "50,000")
        self.assertEqual(out[0]["decimals"], 18)
        self.assertEqual(out[0]["recipient"], "0xAA088dfF3dcF619664094945028d44E779F19894")

    def test_ignores_lines_without_decoded_value(self):
        text = "some unrelated line\nanother line with no brackets"
        self.assertEqual(dp.parse_payload_actions(text), [])

    def test_multiple_decoded_lines(self):
        text = (
            "value: 50,000 [50000000000000000000000, 18 decimals] to 0xAA088dfF3dcF619664094945028d44E779F19894\n"
            "value: 72 [7200000000, 8 decimals] to 0xAA2461f0f0A3dE5fEAF3273eAe16DEF861cf594e\n"
        )
        out = dp.parse_payload_actions(text)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["amount"], "72")
        self.assertEqual(out[1]["decimals"], 8)

    def test_from_to_shaped_line_extracts_the_to_address_not_the_from_address(self):
        # ProtocolV3TestBase event-log lines put the sender's address first:
        # Transfer(from: <sender>, to: <recipient>, value: ...). The FIRST
        # 0x-address in the line is the sender, not the recipient -- a naive
        # "grab the first address" extraction picks the wrong one, which then
        # never matches the forum's real recipient address downstream.
        line = (
            "Transfer(from: 0x464C71f6c2F760DdA6093dCB91C24c39e5d6e18c, "
            "to: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 0.0000 [500000000000, 18 decimals])"
        )
        out = dp.parse_payload_actions(line)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["recipient"], "0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b")

    def test_dedup_uses_the_raw_amount_not_the_rounded_display_amount(self):
        # Two genuinely different raw amounts (5e11 and 7e11) that both
        # round to the same displayed "0.0000" at 18 decimals, to the same
        # recipient, must NOT collapse into one finding.
        text = (
            "Transfer(from: 0x464C71f6c2F760DdA6093dCB91C24c39e5d6e18c, "
            "to: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 0.0000 [500000000000, 18 decimals])\n"
            "Transfer(from: 0x464C71f6c2F760DdA6093dCB91C24c39e5d6e18c, "
            "to: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 0.0000 [700000000000, 18 decimals])\n"
        )
        out = dp.parse_payload_actions(text)
        self.assertEqual(len(out), 2)

    def test_duplicate_transfer_and_balance_transfer_lines_for_the_same_move_collapse_to_one(self):
        # An aToken transfer emits both a standard Transfer event and Aave's
        # own BalanceTransfer event for the SAME underlying move -- both
        # decode to identical amount/decimals/recipient. Without dedup this
        # becomes two duplicate findings for one real action.
        text = (
            "Transfer(from: 0x464C71f6c2F760DdA6093dCB91C24c39e5d6e18c, "
            "to: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 0.0000 [500000000000, 18 decimals])\n"
            "BalanceTransfer(from: 0x464C71f6c2F760DdA6093dCB91C24c39e5d6e18c, "
            "to: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 0.0000 [500000000000, 18 decimals], index: 1000000000000000000000000000)\n"
        )
        out = dp.parse_payload_actions(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["recipient"], "0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b")


FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_fixtures")


def _read_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


class InterestAccrualAndBalanceTransferTests(unittest.TestCase):
    # Real CI diff reports from halnation/proposals-trial PR #9 (WBTC) and
    # PR #10 (USDC): a Transfer(from: 0x0...0) paired with a Mint whose
    # balanceIncrease equals the Transfer's raw value is Aave accruing
    # interest to the Collector, not a payload action; the paired
    # BalanceTransfer line is the scaled-balance mirror of the real Transfer,
    # not a second action.
    def test_pr9_wbtc_diff_yields_exactly_one_real_action(self):
        out = dp.parse_payload_actions(_read_fixture("art9_diff.md"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["amount"], "72")
        self.assertEqual(out[0]["recipient"], "0xAA2461f0f0A3dE5fEAF3273eAe16DEF861cf594e")
        self.assertEqual(out[0]["action"], "Transfer")

    def test_pr10_usdc_diff_yields_exactly_one_real_action(self):
        out = dp.parse_payload_actions(_read_fixture("art10_diff.md"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["amount"], "100,000")
        self.assertEqual(out[0]["recipient"], "0xAA870e4B82deaDa3727235f34183Ec9B728714C8")

    def test_from_zero_transfer_not_paired_with_a_matching_mint_still_counts(self):
        # A real mint/supply: from-zero Transfer whose balanceIncrease does
        # NOT match the transferred raw amount (i.e. not interest accrual
        # on an existing balance -- a genuine new mint).
        text = (
            "Transfer(from: 0x0000000000000000000000000000000000000000, "
            "to: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 100 [10000000000, 8 decimals])\n"
            "Mint(caller: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "onBehalfOf: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 100 [10000000000, 8 decimals], balanceIncrease: 5, "
            "index: 1000000000000000000000000000)\n"
        )
        out = dp.parse_payload_actions(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["amount"], "100")

    def test_balance_transfer_line_never_produces_its_own_action(self):
        text = (
            "BalanceTransfer(from: 0x464C71f6c2F760DdA6093dCB91C24c39e5d6e18c, "
            "to: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 71.7532 [7175324699, 8 decimals], index: 1003438910754959289035564842)\n"
        )
        self.assertEqual(dp.parse_payload_actions(text), [])

    def test_mint_two_lines_after_a_matching_from_zero_transfer_is_not_paired(self):
        # aave-v3-origin's AToken._mintScaled emits Mint on the very next
        # line after the Transfer (AToken.sol:299-305) -- MINT_PAIR_WINDOW
        # is 1, so a Mint two lines later (even with a matching
        # balanceIncrease) must NOT be treated as the pairing, and the
        # from-zero Transfer must still count as a real action.
        text = (
            "Transfer(from: 0x0000000000000000000000000000000000000000, "
            "to: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 0.0000 [1382, 8 decimals])\n"
            "PayloadExecuted(payloadId: 999)\n"
            "Mint(caller: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "onBehalfOf: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 0.0000 [1382, 8 decimals], balanceIncrease: 1382, "
            "index: 1003438910754959289035564842)\n"
        )
        out = dp.parse_payload_actions(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["amount"], "0.0000")

    def test_mint_with_matching_balance_increase_but_different_on_behalf_of_still_counts(self):
        # Same raw balanceIncrease as the Transfer's value, but paid to a
        # DIFFERENT account than the Transfer's recipient -- not the same
        # accrual event, so the from-zero Transfer must still count.
        text = (
            "Transfer(from: 0x0000000000000000000000000000000000000000, "
            "to: 0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b, "
            "value: 0.0000 [1382, 8 decimals])\n"
            "Mint(caller: 0xB2c93D2687f7014Aaf588c764E3Ce80aF016229c, "
            "onBehalfOf: 0xB2c93D2687f7014Aaf588c764E3Ce80aF016229c, "
            "value: 0.0000 [1382, 8 decimals], balanceIncrease: 1382, "
            "index: 1003438910754959289035564842)\n"
        )
        out = dp.parse_payload_actions(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["amount"], "0.0000")
        self.assertEqual(out[0]["recipient"], "0xA1c93D2687f7014Aaf588c764E3Ce80aF016229b")


class ApprovalRecipientTests(unittest.TestCase):
    # Real CI diff report from aave-dao/aave-proposals-v3 PR #1200 ("Safety
    # Module August 2026 - Allowance Update"): on an Approval line the
    # recipient of the action is the spender, not the owner (the first
    # address on the line).
    def test_approval_recipient_is_the_spender_not_the_owner(self):
        # The fixture is a revoke-then-set pair (0, then 30,612.4365) for one
        # spender -- the zero revoke is superseded and dropped; only the
        # real nonzero approval counts.
        out = dp.parse_payload_actions(_read_fixture("approval_522_diff.md"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["action"], "Approve")
        self.assertEqual(out[0]["recipient"], "0x4da27a545c0c5B758a6BA100e3a049001de870f5")
        self.assertEqual(out[0]["amount"], "30,612.4365")

    def test_full_522_fixture_yields_only_the_nonzero_approval_per_spender(self):
        # The full real diff report has four revoke-then-set pairs (one per
        # spender) -- expected output is exactly the four nonzero approvals.
        out = dp.parse_payload_actions(_read_fixture("approval_522_full_diff.md"))
        self.assertEqual(len(out), 4)
        for a in out:
            self.assertEqual(a["action"], "Approve")
            self.assertNotEqual(a["amount"], "0")
        recipients = {a["recipient"] for a in out}
        self.assertEqual(
            recipients,
            {
                "0x4da27a545c0c5B758a6BA100e3a049001de870f5",
                "0xa1116930326D21fB917d5A27F1E9943A9595fb47",
                "0x1a88Df1cFe15Af22B3c4c783D4e6F7F9e0C1885d",
                "0x9eDA81C21C273a82BE9Bbc19B6A6182212068101",
            },
        )

    def test_standalone_zero_approval_with_no_later_nonzero_still_counts(self):
        # A zero Approval for a pair that never gets a later nonzero
        # Approval in the report is a real cancel, not noise -- it must
        # still be reported.
        text = (
            "Approval(owner: 0x25F2226B597E8F9514B3F68F00f494cF4f286491, "
            "spender: 0x4da27a545c0c5B758a6BA100e3a049001de870f5, "
            "value: 0 [0, 18 decimals])\n"
        )
        out = dp.parse_payload_actions(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["amount"], "0")
        self.assertEqual(out[0]["recipient"], "0x4da27a545c0c5B758a6BA100e3a049001de870f5")

    def test_zero_approval_before_a_later_nonzero_for_a_different_spender_still_counts(self):
        # A zero for spender A followed by a nonzero for spender B must not
        # cause A's zero to be dropped -- supersession is per (owner, spender).
        text = (
            "Approval(owner: 0x25F2226B597E8F9514B3F68F00f494cF4f286491, "
            "spender: 0x4da27a545c0c5B758a6BA100e3a049001de870f5, "
            "value: 0 [0, 18 decimals])\n"
            "Approval(owner: 0x25F2226B597E8F9514B3F68F00f494cF4f286491, "
            "spender: 0xa1116930326D21fB917d5A27F1E9943A9595fb47, "
            "value: 1,250 [1250000000000000000000, 18 decimals])\n"
        )
        out = dp.parse_payload_actions(text)
        self.assertEqual(len(out), 2)

    def test_zero_approval_revoke_on_one_token_is_not_superseded_by_a_nonzero_approval_on_another_token(self):
        # Same (owner, spender) pair, but the zero revoke is on the AAVE
        # token contract's `####` section and the nonzero approval is on a
        # DIFFERENT token's (USDC) section further down the report -- these
        # are two unrelated actions on two different token contracts. The
        # AAVE revoke must NOT be dropped as if it were superseded.
        text = (
            "#### 0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9 (AaveV3Ethereum.ASSETS.AAVE.UNDERLYING)\n"
            "\n"
            "| index | event |\n"
            "| --- | --- |\n"
            "| 0 | Approval(owner: 0x25F2226B597E8F9514B3F68F00f494cF4f286491, "
            "spender: 0x4da27a545c0c5B758a6BA100e3a049001de870f5, value: 0 [0, 18 decimals]) |\n"
            "\n"
            "#### 0x98C23E9d8f34FEFb1B7BD6a91B7FF122F4e16F5c (AaveV3Ethereum.ASSETS.USDC.UNDERLYING)\n"
            "\n"
            "| index | event |\n"
            "| --- | --- |\n"
            "| 1 | Approval(owner: 0x25F2226B597E8F9514B3F68F00f494cF4f286491, "
            "spender: 0x4da27a545c0c5B758a6BA100e3a049001de870f5, "
            "value: 1,000 [1000000000, 6 decimals]) |\n"
        )
        out = dp.parse_payload_actions(text)
        self.assertEqual(len(out), 2)
        amounts = {a["amount"] for a in out}
        self.assertEqual(amounts, {"0", "1,000"})


if __name__ == "__main__":
    unittest.main()

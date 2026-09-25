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


if __name__ == "__main__":
    unittest.main()

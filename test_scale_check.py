import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scale_check as sc


class CheckTests(unittest.TestCase):
    def test_first_token_on_the_line_is_not_mistaken_for_the_symbol(self):
        # "MainnetSwapSteward" is the first token on the line but is not a
        # recognized asset symbol -- the real symbol (USDC) is later on the
        # line, directly before the raw amount.
        line = "MainnetSwapSteward UpdatedTokenBudget USDC 10000000000000000000000000"
        flags = sc.check(line)
        self.assertEqual(len(flags), 1)
        self.assertIn("USDC", flags[0])
        self.assertIn("10000000000000000000000000", flags[0])

    def test_address_before_the_symbol_does_not_hide_the_real_flag(self):
        line = (
            "UpdatedTokenBudget(0x8B3f33234abD88493c0Cd28De33D583B70beDe6 "
            "USDC 10000000000000000000000000)"
        )
        flags = sc.check(line)
        self.assertEqual(len(flags), 1)
        self.assertIn("USDC", flags[0])

    def test_already_decoded_line_is_skipped(self):
        line = (
            "value: 50,000 [50000000000000000000000, 18 decimals] to "
            "0xAA088dfF3dcF619664094945028d44E779F19894"
        )
        self.assertEqual(sc.check(line), [])

    def test_in_bounds_amount_is_not_flagged(self):
        line = "MainnetSwapSteward UpdatedTokenBudget USDC 15000000"
        self.assertEqual(sc.check(line), [])

    def test_unrecognized_symbol_is_not_flagged(self):
        line = "MainnetSwapSteward UpdatedTokenBudget NOTATOKEN 10000000000000000000000000"
        self.assertEqual(sc.check(line), [])


if __name__ == "__main__":
    unittest.main()

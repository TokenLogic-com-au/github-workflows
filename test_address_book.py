import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import address_book as ab

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_fixtures")


def _read_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


class BuildMapsTests(unittest.TestCase):
    def test_empty_text_returns_empty_maps(self):
        label_map, symbol_map = ab.build_maps("")
        self.assertEqual(label_map, {})
        self.assertEqual(symbol_map, {})

    def test_role_label_picked_from_event_log_header(self):
        text = (
            "#### 0xC7A386Da9cB528aa86feD862a7bf33d10AA8455B (AaveV3Monad.POOL_CONFIGURATOR)\n\n"
            "| index | event |\n| --- | --- |\n"
        )
        label_map, _ = ab.build_maps(text)
        self.assertEqual(label_map["0xc7a386da9cb528aa86fed862a7bf33d10aa8455b"], "POOL_CONFIGURATOR")

    def test_executor_lvl_label_preferred_over_other_roles_on_the_same_address(self):
        text = (
            "#### 0x5300A1a15135EA4dc7aD5a167152C01EFc9b192A (AaveV2Ethereum.POOL_ADMIN, "
            "AaveV3Ethereum.ACL_ADMIN, GovernanceV3Ethereum.EXECUTOR_LVL_1)\n\n"
            "| index | event |\n| --- | --- |\n"
        )
        label_map, _ = ab.build_maps(text)
        self.assertEqual(label_map["0x5300a1a15135ea4dc7ad5a167152c01efc9b192a"], "EXECUTOR")

    def test_payloads_controller_label_preferred_over_other_roles(self):
        text = "#### 0xdAbad81aF85554E9ae636395611C58F7eC1aAEc5 (GovernanceV3Ethereum.PAYLOADS_CONTROLLER)\n\n"
        label_map, _ = ab.build_maps(text)
        self.assertEqual(
            label_map["0xdabad81af85554e9ae636395611c58f7ec1aaec5"], "PAYLOADS_CONTROLLER"
        )

    def test_underlying_asset_label_becomes_bare_symbol(self):
        text = "#### 0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9 (AaveV3Ethereum.ASSETS.AAVE.UNDERLYING)\n\n"
        label_map, _ = ab.build_maps(text)
        self.assertEqual(label_map["0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9"], "AAVE")

    def test_a_token_label_gets_the_a_prefix(self):
        text = "#### 0x4d5F47FA6A74757f35C14fD3a6Ef8E3C9BC514E8 (AaveV3Ethereum.ASSETS.WETH.A_TOKEN)\n\n"
        label_map, _ = ab.build_maps(text)
        self.assertEqual(label_map["0x4d5f47fa6a74757f35c14fd3a6ef8e3c9bc514e8"], "aWETH")

    def test_header_with_no_label_produces_no_entry(self):
        text = "#### 0x7C10Ebde9C6ba023d4410Da645E013Fd8677795e\n\n**Nonce diff**: 0 -> 1\n"
        label_map, _ = ab.build_maps(text)
        self.assertNotIn("0x7c10ebde9c6ba023d4410da645e013fd8677795e", label_map)

    def test_inline_symbol_is_captured(self):
        text = "RateDataUpdate(reserve: 0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57 (symbol: PT-AUSD-17DEC2026), optimalUsageRatio: 4500)"
        _, symbol_map = ab.build_maps(text)
        self.assertEqual(
            symbol_map["0x8b562578b2f9aa8c14ccda3c5d6cbcead3b06a57"], "PT-AUSD-17DEC2026"
        )

    def test_reserve_table_atoken_symbol_is_captured(self):
        text = (
            "#### PT-AUSD-17DEC2026 ([0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57]"
            "(https://monadscan.com/address/0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57))\n\n"
            "| description | value |\n| --- | --- |\n"
            "| aToken | [0x8F8d143F1FCe0A57A6e80D8DF7f7288703b2Eb7e]"
            "(https://monadscan.com/address/0x8F8d143F1FCe0A57A6e80D8DF7f7288703b2Eb7e) |\n"
            "| aTokenSymbol | aMonPT_AUSD_17DEC2026 |\n"
        )
        _, symbol_map = ab.build_maps(text)
        self.assertEqual(symbol_map["0x8b562578b2f9aa8c14ccda3c5d6cbcead3b06a57"], "PT-AUSD-17DEC2026")
        self.assertEqual(
            symbol_map["0x8f8d143f1fce0a57a6e80d8df7f7288703b2eb7e"], "aMonPT_AUSD_17DEC2026"
        )

    def test_full_pr231_fixture_labels_executor_pool_and_atoken(self):
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        label_map, symbol_map = ab.build_maps(text)
        self.assertEqual(label_map["0xa9d0eaff48ce1df468f9eaeb7e628c413343f6a2"], "EXECUTOR")
        self.assertEqual(label_map["0x69a5f9ad4f96ebf0a0c792dd42a01cc5c0102fef"], "POOL")
        self.assertEqual(
            symbol_map["0x8f8d143f1fce0a57a6e80d8df7f7288703b2eb7e"], "aMonPT_AUSD_17DEC2026"
        )


class DescribeAddressTests(unittest.TestCase):
    def test_label_map_preferred_over_symbol_map(self):
        addr = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        label_map = {addr.lower(): "POOL"}
        symbol_map = {addr.lower(): "WETH"}
        self.assertEqual(ab.describe_address(addr, label_map, symbol_map), "POOL")

    def test_symbol_map_used_when_no_label(self):
        addr = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
        symbol_map = {addr.lower(): "WETH"}
        self.assertEqual(ab.describe_address(addr, {}, symbol_map), "WETH")

    def test_falls_back_to_short_address_when_no_label_or_symbol(self):
        addr = "0xf23C65c8C92E42e990786523744Db9d5cdcF6cbE"
        self.assertEqual(ab.describe_address(addr, {}, {}), "0xf23C…6cbE")

    def test_none_address_is_unknown(self):
        self.assertEqual(ab.describe_address(None, {}, {}), "unknown address")


class NewReserveSymbolsTests(unittest.TestCase):
    def test_empty_text_returns_empty_set(self):
        self.assertEqual(ab.new_reserve_symbols(""), set())

    def test_reserve_under_reserves_added_is_new(self):
        text = (
            "## Reserve changes\n\n"
            "### Reserves added\n\n"
            "#### PT-AUSD-17DEC2026 ([0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57](https://x))\n\n"
            "| description | value |\n| --- | --- |\n| id | 13 |\n\n"
            "## EMode changes\n"
        )
        self.assertEqual(ab.new_reserve_symbols(text), {"PT-AUSD-17DEC2026"})

    def test_reserve_under_reserves_changed_is_not_new(self):
        text = (
            "## Reserve changes\n\n"
            "### Reserves changed\n\n"
            "#### WETH ([0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2](https://x))\n\n"
            "| description | value before | value after |\n| --- | --- | --- |\n"
        )
        self.assertEqual(ab.new_reserve_symbols(text), set())

    def test_full_pr231_fixture_reports_the_listed_pt_as_new(self):
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        self.assertEqual(ab.new_reserve_symbols(text), {"PT-AUSD-17DEC2026"})


if __name__ == "__main__":
    unittest.main()

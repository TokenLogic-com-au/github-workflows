import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import address_book as ab

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_fixtures")
ADDRESS_BOOK_SLICE = os.path.join(FIXTURES_DIR, "address_book_slice")
# Real, read-only aave-address-book checkout used ONLY for regression tests
# that need the actual, ambiguous cross-chain data (e.g. cbBTC deployed at
# the identical address on both Ethereum and Base) -- skipped, not failed,
# when this sibling clone isn't present (e.g. in CI, which never checks out
# a foreign proposals repo just to run this repo's own unit tests).
REAL_ADDRESS_BOOK = os.path.abspath(
    os.path.join(
        FIXTURES_DIR,
        "..",
        "..",
        "aave-proposals-v3",
        "lib",
        "aave-helpers",
        "lib",
        "aave-address-book",
    )
)


def _read_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


class SanitizeTokenTests(unittest.TestCase):
    def test_plain_identifier_passes(self):
        self.assertEqual(ab.sanitize_token("PT-AUSD-17DEC2026"), "PT-AUSD-17DEC2026")

    def test_none_and_empty_are_rejected(self):
        self.assertIsNone(ab.sanitize_token(None))
        self.assertIsNone(ab.sanitize_token(""))
        self.assertIsNone(ab.sanitize_token("   "))

    def test_embedded_newline_is_rejected(self):
        self.assertIsNone(ab.sanitize_token("X\n# LGTM\n"))

    def test_markdown_link_syntax_is_rejected(self):
        self.assertIsNone(ab.sanitize_token("[x](https://github.com/evil)"))

    def test_backtick_is_rejected(self):
        self.assertIsNone(ab.sanitize_token("a`b"))

    def test_overlong_value_is_rejected(self):
        self.assertIsNone(ab.sanitize_token("A" * 65))

    def test_surrounding_whitespace_is_trimmed(self):
        self.assertEqual(ab.sanitize_token("  WETH  "), "WETH")


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

    def test_malicious_inline_symbol_with_embedded_newline_is_dropped(self):
        text = "asset: 0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57 (symbol: X\n# LGTM\n)"
        _, symbol_map = ab.build_maps(text)
        self.assertNotIn("0x8b562578b2f9aa8c14ccda3c5d6cbcead3b06a57", symbol_map)

    def test_malicious_reserve_header_symbol_with_markdown_link_is_dropped(self):
        text = (
            "#### [x](https://github.com/evil) ([0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57]"
            "(https://monadscan.com/address/0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57))\n\n"
            "| description | value |\n| --- | --- |\n| id | 13 |\n"
        )
        _, symbol_map = ab.build_maps(text)
        self.assertNotIn("0x8b562578b2f9aa8c14ccda3c5d6cbcead3b06a57", symbol_map)

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


class LoadSolidityLabelsTests(unittest.TestCase):
    # Fixture: test_fixtures/address_book_slice/src/{AaveV3Monad,
    # MiscEthereum}.sol -- real files from the read-only aave-address-book
    # checkout at cloned_repos/aave-proposals-v3/lib/aave-helpers/lib/
    # aave-address-book, trimmed so unit tests never depend on that path.
    # AaveV3Monad.sol keeps all four of its libraries (AaveV3Monad,
    # AaveV3MonadAssets, AaveV3MonadEModes, AaveV3MonadExternalLibraries)
    # verbatim except AaveV3MonadAssets, trimmed to two assets'
    # UNDERLYING/DECIMALS/ORACLE/INTEREST_RATE_STRATEGY constants only (the
    # dropped `*_A_TOKEN`/`*_V_TOKEN`/`*_STATA_TOKEN` lines trip this repo's
    # secret-guard pre-commit hook, which pattern-matches `token\s*=\s*0x...`
    # -- never bypassed; the surviving fields are enough to test multi-asset,
    # multi-library parsing).

    def test_missing_root_returns_empty_and_does_not_raise(self):
        self.assertEqual(ab.load_solidity_labels(""), {})
        self.assertEqual(ab.load_solidity_labels("/no/such/dir"), {})
        self.assertEqual(ab.load_solidity_labels(None), {})

    def test_root_without_src_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ab.load_solidity_labels(tmp), {})

    def test_bare_address_constant_is_parsed(self):
        labels = ab.load_solidity_labels(ADDRESS_BOOK_SLICE)
        self.assertIn(
            ("AaveV3Monad", "DUST_BIN"),
            labels["0xf23c65c8c92e42e990786523744db9d5cdcf6cbe"],
        )

    def test_typed_wrapper_constant_on_one_line_is_parsed(self):
        # `IPool internal constant POOL = IPool(0x...);` all on one line.
        labels = ab.load_solidity_labels(ADDRESS_BOOK_SLICE)
        self.assertIn(
            ("AaveV3Monad", "POOL"),
            labels["0x69a5f9ad4f96ebf0a0c792dd42a01cc5c0102fef"],
        )

    def test_typed_wrapper_constant_wrapped_across_two_lines_is_parsed(self):
        # `IPoolConfigurator internal constant POOL_CONFIGURATOR =\n
        #     IPoolConfigurator(0x...);`
        labels = ab.load_solidity_labels(ADDRESS_BOOK_SLICE)
        self.assertIn(
            ("AaveV3Monad", "POOL_CONFIGURATOR"),
            labels["0xc7a386da9cb528aa86fed862a7bf33d10aa8455b"],
        )

    def test_bare_address_constant_wrapped_across_two_lines_is_parsed(self):
        # MiscEthereum's TOKENLOGIC_FUNDING_RECEIVER: `address internal
        # constant NAME =\n    0x...;` with no type wrapper at all.
        labels = ab.load_solidity_labels(ADDRESS_BOOK_SLICE)
        self.assertIn(
            ("MiscEthereum", "TOKENLOGIC_FUNDING_RECEIVER"),
            labels["0xaa088dff3dcf619664094945028d44e779f19894"],
        )

    def test_multiple_libraries_in_one_file_are_all_parsed(self):
        labels = ab.load_solidity_labels(ADDRESS_BOOK_SLICE)
        # AaveV3Monad (base), AaveV3MonadAssets, AaveV3MonadExternalLibraries
        self.assertIn(("AaveV3MonadAssets", "USDC_UNDERLYING"), labels["0x754704bc059f8c67012fed69bc8a327a5aafb603"])
        self.assertIn(
            ("AaveV3MonadExternalLibraries", "SUPPLY_LOGIC"),
            labels["0x584c7d8c4cb05304fe5ac7fbc97f20a10fb07564"],
        )

    def test_an_address_not_in_the_book_is_absent(self):
        labels = ab.load_solidity_labels(ADDRESS_BOOK_SLICE)
        self.assertNotIn("0xac140648435d03f784879cd789130f22ef588fcd", labels)

    def test_non_utf8_file_does_not_crash_and_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "src")
            os.makedirs(src)
            with open(os.path.join(src, "Broken.sol"), "wb") as f:
                f.write(b"library Broken {\n  address internal constant X = 0x")
                f.write(bytes([0xFF, 0xFE, 0x00, 0xFF]))  # invalid UTF-8
                f.write(b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa;\n}\n")
            # must not raise
            labels = ab.load_solidity_labels(tmp)
            self.assertIsInstance(labels, dict)

    def test_only_src_tree_is_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib_dir = os.path.join(tmp, "lib", "vendored")
            os.makedirs(lib_dir)
            with open(os.path.join(lib_dir, "Vendored.sol"), "w") as f:
                f.write(
                    "library Vendored {\n"
                    "  address internal constant X = 0x1234567890123456789012345678901234567890;\n"
                    "}\n"
                )
            labels = ab.load_solidity_labels(tmp)
            self.assertNotIn("0x1234567890123456789012345678901234567890", labels)


class InferChainTests(unittest.TestCase):
    def test_empty_text_returns_none(self):
        self.assertIsNone(ab.infer_chain(""))

    def test_most_common_chain_suffix_wins(self):
        text = (
            "#### 0x1 (AaveV3Monad.POOL)\n"
            "#### 0x2 (GovernanceV3Monad.EXECUTOR_LVL_1)\n"
            "#### 0x3 (AaveV3Ethereum.POOL)\n"
        )
        self.assertEqual(ab.infer_chain(text), "Monad")


class LibraryChainMatchingTests(unittest.TestCase):
    def test_same_chain_asset_library_matches(self):
        self.assertTrue(ab._library_matches_chain("AaveV3EthereumAssets", "Ethereum"))

    def test_different_chain_asset_library_does_not_match(self):
        self.assertFalse(ab._library_matches_chain("AaveV3BaseAssets", "Ethereum"))

    def test_emodes_and_external_libraries_suffixes_recognized(self):
        self.assertTrue(ab._library_matches_chain("AaveV3EthereumEModes", "Ethereum"))
        self.assertTrue(ab._library_matches_chain("AaveV3EthereumExternalLibraries", "Ethereum"))

    def test_lido_instance_accepts_base_chain_misc_library(self):
        self.assertTrue(ab._library_matches_chain("MiscEthereum", "EthereumLido"))
        self.assertTrue(ab._library_matches_chain("MiscEthereum", "EthereumEtherFi"))
        self.assertTrue(ab._library_matches_chain("MiscEthereum", "EthereumHorizon"))

    def test_lido_instance_does_not_accept_a_different_base_chains_misc_library(self):
        self.assertFalse(ab._library_matches_chain("MiscArbitrum", "EthereumLido"))

    def test_lido_instance_does_not_accept_base_chains_aavev3_library(self):
        # AaveV3Ethereum (no Lido) must NOT stand in for AaveV3EthereumLido --
        # the base-chain fallback is only for Misc/GovernanceV3/Umbrella/Gho.
        self.assertFalse(ab._library_matches_chain("AaveV3Ethereum", "EthereumLido"))

    def test_governance_and_umbrella_and_gho_get_the_same_base_chain_fallback(self):
        self.assertTrue(ab._library_matches_chain("GovernanceV3Ethereum", "EthereumLido"))
        self.assertTrue(ab._library_matches_chain("UmbrellaEthereum", "EthereumLido"))
        self.assertTrue(ab._library_matches_chain("GhoEthereum", "EthereumLido"))

    def test_unrecognized_family_never_matches(self):
        self.assertFalse(ab._library_matches_chain("SomeRandomLibrary", "Ethereum"))


class DescribeAddressWithSolidityBookTests(unittest.TestCase):
    def test_diff_report_label_wins_over_solidity_book(self):
        solidity_labels = {"0xaddr": [("SomeLib", "SOME_NAME")]}
        label_map = {"0xaddr": "POOL"}
        self.assertEqual(
            ab.describe_address("0xADDR", label_map, {}, solidity_labels, None),
            "`POOL` (0xADDR)",
        )

    def test_solidity_book_used_when_diff_report_has_no_label_and_entry_is_unambiguous(self):
        solidity_labels = {"0xaddr": [("AaveV3Monad", "DUST_BIN")]}
        self.assertEqual(
            ab.describe_address("0xADDR", {}, {}, solidity_labels, None),
            "`AaveV3Monad.DUST_BIN` (0xADDR)",
        )

    def test_ambiguous_entry_with_no_known_chain_is_not_guessed(self):
        solidity_labels = {
            "0xaddr": [("MiscEthereum", "AFC_SAFE"), ("MiscMonad", "AFC_SAFE")]
        }
        self.assertEqual(ab.describe_address("0xADDR", {}, {}, solidity_labels, None), "0xADDR")

    def test_same_chain_entry_preferred_when_address_has_several(self):
        solidity_labels = {
            "0xaddr": [("MiscEthereum", "AFC_SAFE"), ("MiscMonad", "AFC_SAFE")]
        }
        self.assertEqual(
            ab.describe_address("0xADDR", {}, {}, solidity_labels, "Ethereum"),
            "`MiscEthereum.AFC_SAFE` (0xADDR)",
        )
        self.assertEqual(
            ab.describe_address("0xADDR", {}, {}, solidity_labels, "Monad"),
            "`MiscMonad.AFC_SAFE` (0xADDR)",
        )

    def test_lido_payload_resolves_the_base_chain_misc_entry(self):
        solidity_labels = {
            "0xaddr": [("MiscEthereum", "AHAB_SAFE"), ("MiscArbitrum", "AHAB_SAFE")]
        }
        self.assertEqual(
            ab.describe_address("0xADDR", {}, {}, solidity_labels, "EthereumLido"),
            "`MiscEthereum.AHAB_SAFE` (0xADDR)",
        )

    def test_no_match_for_known_chain_falls_back_to_full_address_never_another_chain(self):
        solidity_labels = {"0xaddr": [("MiscArbitrum", "AHAB_SAFE")]}
        self.assertEqual(
            ab.describe_address("0xADDR", {}, {}, solidity_labels, "EthereumLido"), "0xADDR"
        )

    def test_falls_back_to_full_address_when_book_has_nothing_either(self):
        addr = "0xac140648435d03f784879cd789130F22Ef588Fcd"
        self.assertEqual(ab.describe_address(addr, {}, {}, {}, "Ethereum"), addr)

    def test_missing_solidity_labels_degrades_silently(self):
        # No book passed at all -- must behave exactly like before this
        # source existed, not raise.
        addr = "0xac140648435d03f784879cd789130F22Ef588Fcd"
        self.assertEqual(ab.describe_address(addr, {}, {}), addr)

    def test_full_slice_resolves_dust_bin_on_the_pt_ausd_listing_fixture(self):
        diff_text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        label_map, symbol_map = ab.build_maps(diff_text)
        solidity_labels = ab.load_solidity_labels(ADDRESS_BOOK_SLICE)
        chain = ab.infer_chain(diff_text)
        self.assertEqual(chain, "Monad")
        self.assertEqual(
            ab.describe_address(
                "0xf23C65c8C92E42e990786523744Db9d5cdcF6cbE", label_map, symbol_map, solidity_labels, chain
            ),
            "`AaveV3Monad.DUST_BIN` (0xf23C65c8C92E42e990786523744Db9d5cdcF6cbE)",
        )


@unittest.skipUnless(
    os.path.isdir(REAL_ADDRESS_BOOK), "requires the real aave-address-book checkout sibling clone"
)
class RealAddressBookRegressionTests(unittest.TestCase):
    # Confidence beyond the fixture slice, using the real book's own
    # cross-chain ambiguity -- skipped (not failed) where that sibling
    # clone isn't present, e.g. in CI for this repo alone.

    def test_cbbtc_on_ethereum_payload_is_not_labelled_with_bases_library(self):
        solidity_labels = ab.load_solidity_labels(REAL_ADDRESS_BOOK)
        cbbtc_addr = "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf"
        entries = solidity_labels.get(cbbtc_addr.lower(), [])
        self.assertIn(("AaveV3EthereumAssets", "cbBTC_UNDERLYING"), entries)
        self.assertIn(("AaveV3BaseAssets", "cbBTC_UNDERLYING"), entries)
        result = ab.describe_address(cbbtc_addr, {}, {}, solidity_labels, "Ethereum")
        self.assertIn("AaveV3EthereumAssets", result)
        self.assertNotIn("AaveV3BaseAssets", result)

    def test_ahab_safe_on_ethereum_lido_payload_is_misc_ethereum_or_full_address_never_arbitrum(self):
        solidity_labels = ab.load_solidity_labels(REAL_ADDRESS_BOOK)
        ahab_entries = None
        for addr, entries in solidity_labels.items():
            names = {name for _lib, name in entries}
            if "AHAB_SAFE" in names and any(lib == "MiscEthereum" for lib, name in entries if name == "AHAB_SAFE"):
                ahab_entries = (addr, entries)
                break
        self.assertIsNotNone(ahab_entries, "MiscEthereum.AHAB_SAFE not found in the real book")
        addr, entries = ahab_entries
        result = ab.describe_address(addr, {}, {}, solidity_labels, "EthereumLido")
        self.assertNotIn("MiscArbitrum", result)
        if "MiscEthereum.AHAB_SAFE" not in result:
            self.assertEqual(result, addr)


class DescribeAddressTests(unittest.TestCase):
    def test_label_map_preferred_over_symbol_map(self):
        addr = "0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        label_map = {addr.lower(): "POOL"}
        symbol_map = {addr.lower(): "WETH"}
        self.assertEqual(ab.describe_address(addr, label_map, symbol_map), f"`POOL` ({addr})")

    def test_symbol_map_used_when_no_label(self):
        addr = "0xBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
        symbol_map = {addr.lower(): "WETH"}
        self.assertEqual(ab.describe_address(addr, {}, symbol_map), f"`WETH` ({addr})")

    def test_falls_back_to_the_full_unshortened_address_when_no_label_or_symbol(self):
        addr = "0xf23C65c8C92E42e990786523744Db9d5cdcF6cbE"
        self.assertEqual(ab.describe_address(addr, {}, {}), addr)
        self.assertNotIn("…", ab.describe_address(addr, {}, {}))

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


PT_AUSD_UNDERLYING = "0x8B562578b2f9Aa8C14cCda3c5d6CBCEaD3B06a57"
PT_AUSD_ORACLE = "0x608250bbc11eeaeD31794f976946399eB49bd57c"
V4_REPORT = (
    "## Hub Asset Changes\n\n"
    "### PT-USDG-24SEP2026 (assetId: 5) on Hub [0x62d63197660c080236193CA60b70E49A08E90368](https://x)\n\n"
    "**NEW ASSET**\n\n"
    "| description | value |\n| --- | --- |\n"
    "| symbol | PT-USDG-24SEP2026 |\n"
    "| underlying | [0x45804880De22913dAFE09f4980848ECE6EcbAf78](https://x) |\n"
    "| irStrategy | [0xD7eC225DC053151100A0ef47b94a77AAD9C413b7](https://x) |\n\n"
    "### WETH (assetId: 1) on Hub [0x62d63197660c080236193CA60b70E49A08E90368](https://x)\n\n"
    "| description | value before | value after |\n| --- | --- | --- |\n"
    "| underlying | [0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2](https://x) | same |\n\n"
    "## Event logs\n\n"
    "#### 0x62d63197660c080236193CA60b70E49A08E90368 (AaveV4Ethereum.HUBS.GLOBAL_DOLLAR_HUB)\n"
)


class PendingListingMessageTests(unittest.TestCase):
    def test_pt_ausd_underlying_is_generated_after_listing(self):
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        self.assertEqual(
            ab.pending_listing_message(text, PT_AUSD_UNDERLYING),
            "0x8B56\u20266a57: PT-AUSD-17DEC2026 underlying, not in the address book yet; "
            "expected as AaveV3MonadAssets.PT_AUSD_17DEC2026_UNDERLYING after the listing executes",
        )

    def test_pt_ausd_oracle_is_generated_after_listing(self):
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        self.assertEqual(
            ab.pending_listing_message(text, PT_AUSD_ORACLE),
            "0x6082\u2026d57c: PT-AUSD-17DEC2026 oracle, not in the address book yet; "
            "expected as AaveV3MonadAssets.PT_AUSD_17DEC2026_ORACLE after the listing executes",
        )

    def test_unrelated_address_is_not_pending(self):
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        self.assertIsNone(ab.pending_listing_message(text, "0x1111111111111111111111111111111111111111"))

    def test_address_match_is_case_insensitive(self):
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md")
        msg = ab.pending_listing_message(text, PT_AUSD_UNDERLYING.lower())
        self.assertIn("AaveV3MonadAssets.PT_AUSD_17DEC2026_UNDERLYING", msg)

    def test_non_listing_diff_has_nothing_pending(self):
        text = _read_fixture("ethereum_february2026_funding_update_diff.md")
        self.assertIsNone(ab.pending_listing_message(text, PT_AUSD_UNDERLYING))
        self.assertIsNone(ab.pending_listing_message("", PT_AUSD_UNDERLYING))

    def test_reserve_under_reserves_changed_is_not_pending(self):
        text = (
            "### Reserves changed\n\n"
            "#### WETH ([0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2](https://x))\n\n"
            "| description | value before | value after |\n| --- | --- | --- |\n"
            "| oracle | [0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419](https://x) | same |\n\n"
            "#### 0x69a5F9AD4f96ebf0a0C792dD42a01cC5C0102fef (AaveV3Monad.POOL)\n"
        )
        self.assertIsNone(
            ab.pending_listing_message(text, "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
        )

    def test_library_not_derivable_prints_entry_name_only(self):
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md").replace("AaveV3Monad.POOL)", "POOL)")
        self.assertEqual(
            ab.pending_listing_message(text, PT_AUSD_UNDERLYING),
            "0x8B56\u20266a57: PT-AUSD-17DEC2026 underlying, not in the address book yet; "
            "expected as PT_AUSD_17DEC2026_UNDERLYING after the listing executes",
        )

    def test_two_different_pool_libraries_is_not_derivable(self):
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md") + (
            "\n#### 0x1111111111111111111111111111111111111111 (AaveV3Base.POOL)\n"
        )
        self.assertNotIn("AaveV3", ab.pending_listing_message(text, PT_AUSD_UNDERLYING))

    def test_v3_symbol_follows_generator_rules(self):
        base = (
            "### Reserves added\n\n"
            "#### {sym} ([0x2222222222222222222222222222222222222222](https://x))\n\n"
            "| description | value |\n| --- | --- |\n| id | 1 |\n\n"
            "#### 0x69a5F9AD4f96ebf0a0C792dD42a01cC5C0102fef (AaveV3Arbitrum.POOL)\n"
        )
        cases = {
            "1INCH": "ONE_INCH_UNDERLYING",
            "fUSDT": "USDT_UNDERLYING",
            "stETH.v2": "stETHv2_UNDERLYING",
            "A B C": "A_B_C_UNDERLYING",
            "3CRV": "_3CRV_UNDERLYING",
            "BTC+": "BTCPlus_UNDERLYING",
        }
        for sym, expected in cases.items():
            msg = ab.pending_listing_message(
                base.format(sym=sym), "0x2222222222222222222222222222222222222222"
            )
            self.assertIn(f"expected as AaveV3ArbitrumAssets.{expected} after", msg, sym)

    def test_v4_new_hub_asset_underlying_is_pending(self):
        self.assertEqual(
            ab.pending_listing_message(V4_REPORT, "0x45804880De22913dAFE09f4980848ECE6EcbAf78"),
            "0x4580\u2026Af78: PT-USDG-24SEP2026 underlying, not in the address book yet; "
            "expected as AaveV4EthereumAssets.PT_USDG_24SEP2026_UNDERLYING after the listing executes",
        )

    def test_v4_ir_strategy_and_changed_asset_are_not_pending(self):
        for addr in (
            "0xD7eC225DC053151100A0ef47b94a77AAD9C413b7",
            "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        ):
            self.assertIsNone(ab.pending_listing_message(V4_REPORT, addr))

    def test_fabricated_block_inside_a_code_fence_is_ignored(self):
        fabricated = (
            "```\n### Reserves added\n\n"
            "#### EVIL ([0x3333333333333333333333333333333333333333](https://x))\n\n"
            "| description | value |\n| --- | --- |\n"
            "| oracle | [0x4444444444444444444444444444444444444444](https://x) |\n```\n"
        )
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md") + "\n" + fabricated
        for addr in ("0x3333333333333333333333333333333333333333", "0x4444444444444444444444444444444444444444"):
            self.assertIsNone(ab.pending_listing_message(text, addr))
        self.assertEqual(ab.new_reserve_symbols(text), {"PT-AUSD-17DEC2026"})

    def test_pool_label_inside_a_code_fence_does_not_name_the_library(self):
        text = _read_fixture("pt_ausd_17dec2026_monad_listing_diff.md").replace(
            "AaveV3Monad.POOL)", "POOL)"
        ) + "\n~~~\n#### 0x1111111111111111111111111111111111111111 (AaveV3Base.POOL)\n~~~\n"
        self.assertNotIn("AaveV3", ab.pending_listing_message(text, PT_AUSD_UNDERLYING))

    def test_non_ascii_usdt_symbol_maps_to_usdt_like_the_generator(self):
        text = (
            "### Reserves added\n\n"
            "#### USD\u20ae0 ([0x3333333333333333333333333333333333333333](https://x))\n\n"
            "| description | value |\n| --- | --- |\n"
            "| oracle | [0x4444444444444444444444444444444444444444](https://x) |\n\n"
            "#### 0x69a5F9AD4f96ebf0a0C792dD42a01cC5C0102fef (AaveV3Arbitrum.POOL)\n"
        )
        self.assertEqual(
            ab.pending_listing_message(text, "0x3333333333333333333333333333333333333333"),
            "0x3333\u20263333: USDT underlying, not in the address book yet; "
            "expected as AaveV3ArbitrumAssets.USDT_UNDERLYING after the listing executes",
        )
        self.assertIn(
            "AaveV3ArbitrumAssets.USDT_ORACLE",
            ab.pending_listing_message(text, "0x4444444444444444444444444444444444444444"),
        )


class PendingListingCliTests(unittest.TestCase):
    def _run(self, report_name, addr):
        import subprocess

        return subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(ab.__file__), "address_book.py"),
             "pending-listing", os.path.join(FIXTURES_DIR, report_name), addr],
            capture_output=True, text=True,
        )

    def test_prints_message_for_pending_address(self):
        r = self._run("pt_ausd_17dec2026_monad_listing_diff.md", PT_AUSD_ORACLE)
        self.assertEqual(r.returncode, 0)
        self.assertIn("PT_AUSD_17DEC2026_ORACLE", r.stdout)

    def test_invalid_utf8_report_prints_nothing_and_exits_zero(self):
        path = os.path.join(tempfile.mkdtemp(), "bad.md")
        with open(path, "wb") as f:
            f.write(b"### Reserves added\n\xff\xfe\x80 broken")
        import subprocess

        r = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(ab.__file__), "address_book.py"),
             "pending-listing", path, PT_AUSD_ORACLE],
            capture_output=True, text=True,
        )
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_prints_nothing_for_other_address_and_missing_report(self):
        r = self._run("pt_ausd_17dec2026_monad_listing_diff.md", "0x1111111111111111111111111111111111111111")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = self._run("does_not_exist.md", PT_AUSD_ORACLE)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()

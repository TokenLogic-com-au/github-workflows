import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proposal_scope as ps


class ChangedProposalDirsTests(unittest.TestCase):
    def test_no_changed_files(self):
        self.assertEqual(ps.changed_proposal_dirs([]), [])

    def test_single_proposal_folder(self):
        files = [
            "src/20260910_AaveV3Ethereum_Foo/AaveV3Ethereum_Foo.sol",
            "src/20260910_AaveV3Ethereum_Foo/AaveV3Ethereum_Foo.md",
            "src/20260910_AaveV3Ethereum_Foo/test/AaveV3Ethereum_Foo.t.sol",
        ]
        self.assertEqual(ps.changed_proposal_dirs(files), ["src/20260910_AaveV3Ethereum_Foo"])

    def test_two_proposal_folders_reported_together(self):
        files = [
            "src/20260910_AaveV3Ethereum_Foo/AaveV3Ethereum_Foo.sol",
            "src/20260911_AaveV3Ethereum_Bar/AaveV3Ethereum_Bar.sol",
        ]
        self.assertEqual(
            ps.changed_proposal_dirs(files),
            ["src/20260910_AaveV3Ethereum_Foo", "src/20260911_AaveV3Ethereum_Bar"],
        )

    def test_file_directly_under_src_is_ignored(self):
        files = ["src/README.md"]
        self.assertEqual(ps.changed_proposal_dirs(files), [])

    def test_deleted_file_still_counts(self):
        # git diff --name-only reports the (now-gone) path for a deletion --
        # same as any other changed file, no special casing needed.
        files = ["src/20260910_AaveV3Ethereum_Foo/Old.sol"]
        self.assertEqual(ps.changed_proposal_dirs(files), ["src/20260910_AaveV3Ethereum_Foo"])

    def test_blank_lines_and_non_src_files_are_ignored(self):
        files = ["", "README.md", "  ", "src/20260910_AaveV3Ethereum_Foo/Foo.sol"]
        self.assertEqual(ps.changed_proposal_dirs(files), ["src/20260910_AaveV3Ethereum_Foo"])

    def test_pr_1185_file_list_counts_one_proposal_folder(self):
        # aave-dao/aave-proposals-v3#1185: the proposal folder plus a shared
        # src/interfaces/ file, a diffs/ report, and a lib/ submodule bump.
        # Only the dated proposal folder counts -- interfaces/diffs/lib are
        # not proposal payloads.
        files = [
            "src/20260811_AaveV3Monad_AssetListingPendlePTAUSDMonad/AaveV3Monad_AssetListingPendlePTAUSDMonad.sol",
            "src/20260811_AaveV3Monad_AssetListingPendlePTAUSDMonad/AaveV3Monad_AssetListingPendlePTAUSDMonad.md",
            "src/interfaces/IPendlePriceCapAdapter.sol",
            "diffs/20260811_AaveV3Monad_AssetListingPendlePTAUSDMonad.md",
            "lib/aave-helpers",
        ]
        self.assertEqual(
            ps.changed_proposal_dirs(files),
            ["src/20260811_AaveV3Monad_AssetListingPendlePTAUSDMonad"],
        )

    def test_only_shared_src_interfaces_changed_counts_zero(self):
        files = ["src/interfaces/IPendlePriceCapAdapter.sol"]
        self.assertEqual(ps.changed_proposal_dirs(files), [])


if __name__ == "__main__":
    unittest.main()

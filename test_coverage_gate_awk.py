import os
import shutil
import subprocess
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
AWK_SCRIPT = os.path.join(
    REPO_ROOT, ".github", "actions", "coverage-gate", "coverage.awk"
)

AWK_BINARIES = [b for b in ("mawk", "gawk") if shutil.which(b)]


def naive_lh_lf(lcov_text, path_prefix, exclude_suffixes):
    # Independent stand-in for today's plain LH/LF summation, used only to
    # prove a test actually exercises the header-vs-body fix (it must
    # disagree with the new script wherever that fix matters).
    covered = 0
    total = 0
    in_scope = False
    suffixes = exclude_suffixes.split()
    for line in lcov_text.splitlines():
        if line.startswith("SF:"):
            path = line[3:]
            in_scope = path.startswith(path_prefix) and not any(
                path.endswith(s) for s in suffixes
            )
        elif line.startswith("LH:") and in_scope:
            covered += int(line[3:])
        elif line.startswith("LF:") and in_scope:
            total += int(line[3:])
    return covered, total


def run_awk(awk_bin, lcov_text, path_prefix="src/", exclude_suffixes=".t.sol .s.sol"):
    with tempfile.TemporaryDirectory() as d:
        lcov_path = os.path.join(d, "lcov.info")
        sample_path = os.path.join(d, "sample.txt")
        with open(lcov_path, "w") as f:
            f.write(lcov_text)
        env = dict(os.environ)
        env["PATH_PREFIX"] = path_prefix
        env["EXCLUDE_SUFFIXES"] = exclude_suffixes
        env["SAMPLE_FILE"] = sample_path
        result = subprocess.run(
            [awk_bin, "-f", AWK_SCRIPT, lcov_path],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        covered, total = (int(x) for x in result.stdout.strip().split())
        sample = []
        if os.path.exists(sample_path):
            with open(sample_path) as f:
                sample = [l for l in f.read().splitlines() if l]
        return covered, total, sample


class CoverageAwkTests(unittest.TestCase):
    def setUp(self):
        if not AWK_BINARIES:
            self.skipTest("neither mawk nor gawk is installed")

    def for_each_awk(self, fn):
        for awk_bin in AWK_BINARIES:
            with self.subTest(awk=awk_bin):
                fn(awk_bin)

    def test_internally_called_function_header_counts_as_covered(self):
        lcov = (
            "TN:\n"
            "SF:src/A.sol\n"
            "FN:10,execute\n"
            "FN:20,newListings\n"
            "DA:10,1\n"
            "DA:11,1\n"
            "DA:20,0\n"
            "DA:21,1\n"
            "DA:22,1\n"
            "LF:5\n"
            "LH:4\n"
            "end_of_record\n"
        )
        naive_covered, naive_total = naive_lh_lf(lcov, "src/", ".t.sol .s.sol")
        self.assertEqual((naive_covered, naive_total), (4, 5))

        def check(awk_bin):
            covered, total, sample = run_awk(awk_bin, lcov)
            self.assertEqual((covered, total), (5, 5))
            self.assertEqual(sample, [])

        self.for_each_awk(check)

    def test_uncalled_one_liner_fails(self):
        lcov = (
            "TN:\n"
            "SF:src/B.sol\n"
            "FN:5,foo\n"
            "DA:5,0\n"
            "LF:1\n"
            "LH:0\n"
            "end_of_record\n"
        )

        def check(awk_bin):
            covered, total, sample = run_awk(awk_bin, lcov)
            self.assertEqual((covered, total), (0, 1))
            self.assertEqual(sample, ["src/B.sol:5"])

        self.for_each_awk(check)

    def test_uncalled_multiline_function_fails_and_body_lines_sampled(self):
        lcov = (
            "TN:\n"
            "SF:src/C.sol\n"
            "FN:5,bar\n"
            "DA:5,0\n"
            "DA:6,0\n"
            "DA:7,0\n"
            "LF:3\n"
            "LH:0\n"
            "end_of_record\n"
        )

        def check(awk_bin):
            covered, total, sample = run_awk(awk_bin, lcov)
            self.assertEqual((covered, total), (0, 3))
            self.assertEqual(sample, ["src/C.sol:5", "src/C.sol:6", "src/C.sol:7"])

        self.for_each_awk(check)

    def test_externally_called_header_hit_matches_plain_lh_lf(self):
        lcov = (
            "TN:\n"
            "SF:src/D.sol\n"
            "FN:5,baz\n"
            "DA:5,1\n"
            "DA:6,1\n"
            "DA:7,0\n"
            "LF:3\n"
            "LH:2\n"
            "end_of_record\n"
        )
        naive_covered, naive_total = naive_lh_lf(lcov, "src/", ".t.sol .s.sol")

        def check(awk_bin):
            covered, total, _ = run_awk(awk_bin, lcov)
            self.assertEqual((covered, total), (naive_covered, naive_total))

        self.for_each_awk(check)

    def test_bodies_never_cross_sf_record_boundary(self):
        # record1's uncalled header sits right before record2's hit lines.
        # A boundary bug (arrays not reset per SF) would let record2's
        # DA:25,1 look like a "body hit" for record1's header at line 20.
        lcov = (
            "TN:\n"
            "SF:src/E.sol\n"
            "FN:20,onlyHeader\n"
            "DA:20,0\n"
            "LF:1\n"
            "LH:0\n"
            "end_of_record\n"
            "TN:\n"
            "SF:src/F.sol\n"
            "FN:1,other\n"
            "DA:1,1\n"
            "DA:25,1\n"
            "LF:2\n"
            "LH:2\n"
            "end_of_record\n"
        )

        def check(awk_bin):
            covered, total, sample = run_awk(awk_bin, lcov)
            # if boundary bug: covered would be 3/3 (record1 header wrongly covered)
            self.assertEqual((covered, total), (2, 3))
            self.assertEqual(sample, ["src/E.sol:20"])

        self.for_each_awk(check)

    def test_exclude_suffixes_and_prefix_match(self):
        lcov = (
            "TN:\n"
            "SF:src/G.sol\n"
            "FN:1,g\n"
            "DA:1,1\n"
            "LF:1\n"
            "LH:1\n"
            "end_of_record\n"
            "TN:\n"
            "SF:src/G.t.sol\n"
            "FN:1,gTest\n"
            "DA:1,0\n"
            "LF:1\n"
            "LH:0\n"
            "end_of_record\n"
            "TN:\n"
            "SF:src/DeployG.s.sol\n"
            "FN:1,deploy\n"
            "DA:1,0\n"
            "LF:1\n"
            "LH:0\n"
            "end_of_record\n"
            "TN:\n"
            "SF:other/H.sol\n"
            "FN:1,h\n"
            "DA:1,0\n"
            "LF:1\n"
            "LH:0\n"
            "end_of_record\n"
        )

        def check(awk_bin):
            covered, total, sample = run_awk(awk_bin, lcov)
            self.assertEqual((covered, total), (1, 1))
            self.assertEqual(sample, [])

        self.for_each_awk(check)

    def test_zero_over_zero_matches_today(self):
        lcov = (
            "TN:\n"
            "SF:test/Y.sol\n"
            "FN:1,y\n"
            "DA:1,0\n"
            "LF:1\n"
            "LH:0\n"
            "end_of_record\n"
        )

        def check(awk_bin):
            covered, total, sample = run_awk(awk_bin, lcov)
            self.assertEqual((covered, total), (0, 0))
            self.assertEqual(sample, [])

        self.for_each_awk(check)

    def test_sample_sorted_by_file_then_line_and_capped_at_15(self):
        lines = []
        lines.append("TN:")
        lines.append("SF:src/Z.sol")
        lines.append("FN:1,z")
        # 20 uncovered single-line functions in descending, scrambled order
        for n in sorted(range(1, 21), reverse=True):
            lines.append(f"DA:{n},0")
        lines.append("LF:20")
        lines.append("LH:0")
        lines.append("end_of_record")
        lcov = "\n".join(lines) + "\n"

        def check(awk_bin):
            covered, total, sample = run_awk(awk_bin, lcov)
            self.assertEqual((covered, total), (0, 20))
            self.assertEqual(len(sample), 15)
            expected = [f"src/Z.sol:{n}" for n in range(1, 16)]
            self.assertEqual(sample, expected)

        self.for_each_awk(check)


if __name__ == "__main__":
    unittest.main()

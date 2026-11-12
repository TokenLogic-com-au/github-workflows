import base64
import os
import subprocess
import tempfile
import unittest

import yaml

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "proposal-checks.yml")
BOOK = "lib/aave-helpers/lib/aave-address-book/src/ChainlinkArbitrum.sol"
IN_BOOK = "0x" + "ab" * 20
NOT_IN_BOOK = "0x" + "cd" * 20
BOOK_SOL = f"library ChainlinkArbitrum {{\n  address internal constant USDG__USD = {IN_BOOK};\n}}\n"
PAYLOAD = "src/20260101_Aave_V3_Arbitrum_Foo/Foo.sol"
TEST = "src/20260101_Aave_V3_Arbitrum_Foo/Foo.t.sol"


def step_script():
    with open(WORKFLOW, encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    for job in wf["jobs"].values():
        for step in job.get("steps", []):
            if step.get("id") == "measure":
                return step["run"]
    raise AssertionError("measure step not found")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def run_step(path, line):
    """Runs the real step on a diff adding `line` to `path`; returns (stdout, decoded details)."""
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        os.makedirs(os.path.dirname(os.path.join(work, BOOK)))
        with open(os.path.join(work, BOOK), "w") as f:
            f.write(BOOK_SOL)
        git(work, "init", "-q")
        git(work, "add", "-A")
        git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
        base = git(work, "rev-parse", "HEAD")
        os.makedirs(os.path.dirname(os.path.join(work, path)), exist_ok=True)
        with open(os.path.join(work, path), "w") as f:
            f.write(line + "\n")
        git(work, "add", "-A")
        git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "head")
        out = os.path.join(tmp, "output")
        env = dict(
            os.environ,
            GW=REPO_ROOT,
            RUNNER_TEMP=os.path.join(tmp, "temp"),
            GITHUB_OUTPUT=out,
            BASE_SHA=base,
            HEAD_SHA=git(work, "rev-parse", "HEAD"),
        )
        proc = subprocess.run(["bash", "-e", "-c", step_script()], cwd=work, env=env, check=True, capture_output=True, text=True)
        outputs = dict(l.rstrip("\n").partition("=")[::2] for l in open(out))
        return proc.stdout, base64.b64decode(outputs["details"]).decode()


class AddressBookStepTest(unittest.TestCase):
    def test_in_book_address_in_test_file_names_the_constant(self):
        stdout, details = run_step(TEST, f"address whale = {IN_BOOK};")
        self.assertIn(f"{TEST}|1|notice|", details)
        self.assertIn("use ChainlinkArbitrum.USDG__USD", details)
        self.assertIn(f"::notice file={TEST},line=1::", stdout)

    def test_unknown_address_in_test_file_is_silent(self):
        stdout, details = run_step(TEST, f"address whale = {NOT_IN_BOOK};")
        self.assertEqual(details, "")
        self.assertNotIn("::warning", stdout)

    def test_in_book_address_in_payload_names_the_constant(self):
        _, details = run_step(PAYLOAD, f"address feed = {IN_BOOK};")
        self.assertIn(f"{PAYLOAD}|1|notice|", details)
        self.assertIn("use ChainlinkArbitrum.USDG__USD", details)

    def test_unknown_address_in_payload_still_warns(self):
        stdout, details = run_step(PAYLOAD, f"address feed = {NOT_IN_BOOK};")
        self.assertIn(f"{PAYLOAD}|1|warning|raw address {NOT_IN_BOOK} not in the address book", details)
        self.assertIn("::warning", stdout)

    def test_comment_only_address_is_ignored(self):
        _, details = run_step(TEST, f"// {IN_BOOK}")
        self.assertEqual(details, "")


class BookConstantTest(unittest.TestCase):
    def test_prefers_the_chain_named_by_the_path(self):
        import address_book as ab

        labels = {IN_BOOK: [("ChainlinkBase", "X"), ("ChainlinkArbitrum", "Y")]}
        self.assertEqual(ab.book_constant(IN_BOOK, labels, "src/A_V3_Arbitrum/Foo.t.sol"), "ChainlinkArbitrum.Y")
        self.assertEqual(ab.book_constant(IN_BOOK, labels, "src/other/Foo.t.sol"), "ChainlinkArbitrum.Y")
        self.assertEqual(ab.book_constant(IN_BOOK, labels, "src/A_Base/Foo.t.sol"), "ChainlinkBase.X")


if __name__ == "__main__":
    unittest.main()

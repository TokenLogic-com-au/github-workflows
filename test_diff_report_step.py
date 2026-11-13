import os
import stat
import subprocess
import tempfile
import unittest

import yaml

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "proposal-checks.yml")

FAKE_FORGE = "#!/bin/sh\nexec \"$FORGE_SCRIPT\"\n"


def diff_step_script():
    with open(WORKFLOW, encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    for job in wf["jobs"].values():
        for step in job.get("steps", []):
            if step.get("id") == "diff":
                return step["run"].replace("${{ steps.folder.outputs.dir }}", "src/p")
    raise AssertionError("diff step not found")


def run_step(committed, produced, log=""):
    """Runs the real workflow step with a fake forge that writes `produced`
    (name -> text) into diffs/; returns (outputs dict, report text or None)."""
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        temp = os.path.join(tmp, "runner-temp")
        bindir = os.path.join(tmp, "bin")
        for d in (os.path.join(work, "diffs"), temp, bindir):
            os.makedirs(d)
        for name, text in committed.items():
            with open(os.path.join(work, "diffs", name), "w") as f:
                f.write(text)
        forge_script = os.path.join(tmp, "fake-forge.sh")
        body = "#!/bin/sh\nmkdir -p diffs\n"
        for name, text in produced.items():
            body += f"printf '%s' '{text}' > diffs/{name}\n"
        if log:
            log_path = os.path.join(tmp, "forge-output.txt")
            with open(log_path, "w") as f:
                f.write(log)
            body += f"cat '{log_path}'\n"
        with open(forge_script, "w") as f:
            f.write(body)
        forge = os.path.join(bindir, "forge")
        with open(forge, "w") as f:
            f.write(FAKE_FORGE)
        for p in (forge, forge_script):
            os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        out = os.path.join(tmp, "output")
        env = dict(
            os.environ,
            PATH=bindir + os.pathsep + os.environ["PATH"],
            RUNNER_TEMP=temp,
            GITHUB_OUTPUT=out,
            FORGE_SCRIPT=forge_script,
        )
        subprocess.run(["bash", "-e", "-c", diff_step_script()], cwd=work, env=env, check=True, capture_output=True)
        outputs = {}
        with open(out) as f:
            for line in f:
                k, _, v = line.rstrip("\n").partition("=")
                outputs[k] = v
        report = outputs.get("report")
        text = None
        if report:
            with open(report, encoding="utf-8") as f:
                text = f.read()
        return outputs, text


# forge -vv shape: per-suite results first, then the "Failing tests:" summary that names each test contract.
FORGE_FAILURE_LOG = """Ran 1 test for src/p/PayloadC.t.sol:PayloadC_Test
[FAIL: unknown hardfork 'monad:MonadTen' for key "default.hardfork" in inline config] setUp() (gas: 0)
Suite result: FAILED. 0 passed; 1 failed; 0 skipped; finished in 381.41µs (0.00ns CPU time)

Ran 3 tests for src/p/PayloadD.t.sol:PayloadD_Test
[PASS] test_ok() (gas: 1)
[FAIL: EvmError: Revert] test_swap() (gas: 918236)
[FAIL: EvmError: Revert] test_price() (gas: 16991)
Suite result: FAILED. 1 passed; 2 failed; 0 skipped; finished in 14.26s (10.66s CPU time)

Ran 2 test suites in 15.94s (17.30s CPU time): 1 tests passed, 3 failed, 0 skipped (4 total tests)

Failing tests:
Encountered 1 failing test in src/p/PayloadC.t.sol:PayloadC_Test
[FAIL: unknown hardfork 'monad:MonadTen' for key "default.hardfork" in inline config] setUp() (gas: 0)

Encountered 2 failing tests in src/p/PayloadD.t.sol:PayloadD_Test
[FAIL: EvmError: Revert] test_swap() (gas: 918236)
[FAIL: EvmError: Revert] test_price() (gas: 16991)

Encountered a total of 3 failing tests, 1 tests succeeded
"""


class DiffReportStepTest(unittest.TestCase):
    def test_several_ci_reports_are_all_kept_with_payload_headings(self):
        outputs, text = run_step({}, {"PayloadA.md": "alpha-body", "PayloadB.md": "beta-body"})
        self.assertEqual(outputs["fork_test_status"], "")
        self.assertEqual(outputs["ci_report"], outputs["report"])
        self.assertIn("# Payload report: PayloadA", text)
        self.assertIn("alpha-body", text)
        self.assertIn("# Payload report: PayloadB", text)
        self.assertIn("beta-body", text)

    def test_reports_are_joined_in_name_order(self):
        outputs, text = run_step({}, {"PayloadB.md": "beta-body", "PayloadA.md": "alpha-body"})
        self.assertLess(text.index("# Payload report: PayloadA"), text.index("# Payload report: PayloadB"))
        self.assertLess(text.index("alpha-body"), text.index("beta-body"))

    def test_partial_run_keeps_the_failing_test_status_alongside_reports(self):
        outputs, text = run_step(
            {}, {"PayloadA.md": "alpha-body", "PayloadB.md": "beta-body"},
            log=FORGE_FAILURE_LOG,
        )
        self.assertIn("alpha-body", text)
        self.assertEqual(
            outputs["fork_test_status"],
            "PayloadC_Test.setUp (unknown hardfork 'monad:MonadTen' for key \"default.hardfork\" in inline config); "
            "PayloadD_Test.test_swap (EvmError: Revert); PayloadD_Test.test_price (EvmError: Revert)",
        )

    def test_single_ci_report_is_kept(self):
        outputs, text = run_step({}, {"Only.md": "solo-body"})
        self.assertIn("solo-body", text)
        self.assertEqual(outputs["fork_test_status"], "")

    def test_committed_reports_are_never_trusted(self):
        outputs, text = run_step({"Evil.md": "committed-body"}, {"Real.md": "real-body"})
        self.assertIn("real-body", text)
        self.assertNotIn("committed-body", text)
        self.assertNotIn("Evil", text)

    def test_no_ci_report_is_a_fork_test_failure(self):
        outputs, text = run_step({"Evil.md": "committed-body"}, {})
        self.assertEqual(outputs["report"], "")
        self.assertNotIn("ci_report", outputs)
        self.assertIn("forge test failed", outputs["fork_test_status"])


if __name__ == "__main__":
    unittest.main()

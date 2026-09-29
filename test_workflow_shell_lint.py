import os
import unittest

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
GITHUB_DIR = os.path.join(REPO_ROOT, ".github")
BANNED = "$(printf '\\n')"


class NoStrippedNewlineBugTest(unittest.TestCase):
    def test_no_github_file_uses_command_substitution_printf_newline(self):
        # $(printf '\n') is stripped to "" by command substitution, so
        # accumulating "$var$(printf '\n')" glues every entry onto one line.
        offenders = []
        for dirpath, _, filenames in os.walk(GITHUB_DIR):
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                with open(path, "r", errors="ignore") as f:
                    content = f.read()
                if BANNED in content:
                    offenders.append(os.path.relpath(path, REPO_ROOT))
        self.assertEqual(offenders, [], f"found $(printf '\\n') in: {offenders}")


if __name__ == "__main__":
    unittest.main()

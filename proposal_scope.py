#!/usr/bin/env python3
"""Lists the src/YYYYMMDD_* proposal folders touched by a changed-file list (stdin, one path per line)."""
import json
import re
import sys

PROPOSAL_FOLDER = re.compile(r"^\d{8}_")


def changed_proposal_dirs(changed_files):
    dirs = set()
    for f in changed_files:
        f = f.strip()
        if not f or not f.startswith("src/"):
            continue
        rest = f[len("src/"):]
        if "/" not in rest:
            continue
        folder = rest.split("/", 1)[0]
        if not PROPOSAL_FOLDER.match(folder):
            continue
        dirs.add(f"src/{folder}")
    return sorted(dirs)


def main():
    changed_files = sys.stdin.read().splitlines()
    dirs = changed_proposal_dirs(changed_files)
    json.dump({"count": len(dirs), "dirs": dirs}, sys.stdout)
    print()


if __name__ == "__main__":
    main()

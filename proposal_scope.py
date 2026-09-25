#!/usr/bin/env python3
"""Decides which proposal folder(s) a PR touches, from a list of changed
files (base..head, `git diff --name-only`, works for added/modified/deleted
files since git reports only the final path for each).

A "proposal folder" is a first-level directory under src/ matching the
YYYYMMDD_ naming convention every proposal folder uses (src/<dir>/...).
A changed file directly under src/, or under a non-dated src/ subfolder
(e.g. src/interfaces/, src/helpers/ -- shared code, not a proposal payload),
is ignored: it can't be scoped to a single payload.

One source of truth for this decision: the proposal-checks workflow's
`scope` job uses it to gate every other job, and the (now-removed) advisory
job's own folder-detection step used to duplicate this logic.
"""
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
            continue  # file directly under src/, not inside a proposal folder
        folder = rest.split("/", 1)[0]
        if not PROPOSAL_FOLDER.match(folder):
            continue  # a shared src/ subfolder (interfaces/, helpers/, …), not a proposal
        dirs.add(f"src/{folder}")
    return sorted(dirs)


def main():
    changed_files = sys.stdin.read().splitlines()
    dirs = changed_proposal_dirs(changed_files)
    json.dump({"count": len(dirs), "dirs": dirs}, sys.stdout)
    print()


if __name__ == "__main__":
    main()

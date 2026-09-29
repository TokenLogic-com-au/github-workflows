"""Builds the "Upstream PR" line for the proposal-checks summary comment: a
prefilled compare-across-forks link (or, once one exists, a direct link to
the already-open upstream PR) from this fork's proposal branch to its
upstream parent repo. The prefilled body is the fork PR's own description,
verbatim -- never AI-generated or reworded.

Also flags an unfinished fork PR description (an unedited template line, or
a checklist box still unticked) so the advisory comment can warn about it
before the upstream PR gets a half-written body.

Pure/no-network -- the gh lookups (parent repo, an existing upstream PR) and
the fork PR's body/template text are read by the caller and passed in.
"""
import re
from urllib.parse import urlencode

LOOKUP_FAILED_LINE = "Upstream PR: lookup failed (see the job log)"
NO_DESCRIPTION_LINE = "Upstream PR: write the PR description on this PR first (it becomes the upstream PR body)"
TOO_LONG_NOTE = " (description too long for a link; paste it from this PR)"
MAX_COMPARE_URL_LEN = 7500

_UNTICKED_BOX_RE = re.compile(r"^-\s*\[\s*\]")
_HEADING_RE = re.compile(r"^#{1,6}\s")


def pick_upstream_pr(prs: list) -> dict:
    """Picks which upstream PR the summary line should point to, when more
    than one PR on the parent already has this fork's branch as its head: an
    OPEN one wins regardless of age, otherwise the most recently updated one.
    Returns None for an empty/falsy list."""
    if not prs:
        return None
    return sorted(prs, key=lambda p: (p.get("state") == "open", p.get("updated_at") or ""), reverse=True)[0]


def find_unresolved_template_items(pr_body: str, template: str) -> list:
    """Returns the fork PR body's lines that still look like unfinished
    template boilerplate: a line copied verbatim from the repo's PR template,
    or an unticked `- [ ]` checklist box. Empty when the body has none, or
    when there's no body/template to compare."""
    if not pr_body:
        return []
    # Headings (e.g. "### Pre-review checklist:") are expected to survive
    # unedited in a fully-filled-out body -- only compare non-heading
    # template lines (instructional text, unticked checklist bullets) for
    # a verbatim match.
    template_lines = {
        line.strip()
        for line in (template or "").splitlines()
        if line.strip() and not _HEADING_RE.match(line.strip())
    }
    found = []
    for line in pr_body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in template_lines or _UNTICKED_BOX_RE.match(stripped):
            found.append(stripped)
    return found


def has_unresolved_template_items(pr_body: str, template: str) -> bool:
    return bool(find_unresolved_template_items(pr_body, template))


def compare_url(parent_repo: str, base_branch: str, fork_owner: str, fork_repo: str, head_branch: str, title: str, body: str) -> str:
    query = urlencode({"quick_pull": "1", "title": title, "body": body})
    return f"https://github.com/{parent_repo}/compare/{base_branch}...{fork_owner}:{fork_repo}:{head_branch}?{query}"


def render_upstream_pr_line(
    is_fork: bool,
    parent_repo: str,
    parent_default_branch: str,
    fork_owner: str,
    fork_repo: str,
    head_branch: str,
    pr_title: str,
    fork_pr_body: str,
    existing_pr: dict = None,
) -> str:
    if not is_fork:
        return ""
    if existing_pr:
        return f"Upstream PR: [{parent_repo}#{existing_pr['number']}]({existing_pr['html_url']}) ({existing_pr['state']})"
    if not parent_default_branch:
        return LOOKUP_FAILED_LINE

    body = (fork_pr_body or "").strip()
    if not body:
        return NO_DESCRIPTION_LINE

    url = compare_url(parent_repo, parent_default_branch, fork_owner, fork_repo, head_branch, pr_title, body)
    if len(url) > MAX_COMPARE_URL_LEN:
        title_only_url = compare_url(parent_repo, parent_default_branch, fork_owner, fork_repo, head_branch, pr_title, "")
        return f"Upstream PR: [open a prefilled PR on {parent_repo}]({title_only_url}){TOO_LONG_NOTE}"
    return f"Upstream PR: [open a prefilled PR on {parent_repo}]({url})"


def main():
    import json
    import sys

    payload = json.load(sys.stdin)
    existing_pr = payload.get("existing_pr")
    if existing_pr is None and "candidate_prs" in payload:
        existing_pr = pick_upstream_pr(payload.get("candidate_prs") or [])
    out = render_upstream_pr_line(
        payload["is_fork"],
        payload.get("parent_repo", ""),
        payload.get("parent_default_branch", ""),
        payload.get("fork_owner", ""),
        payload.get("fork_repo", ""),
        payload.get("head_branch", ""),
        payload.get("pr_title", ""),
        payload.get("fork_pr_body", ""),
        existing_pr,
    )
    sys.stdout.write(out)


if __name__ == "__main__":
    main()

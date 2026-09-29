"""Builds the "Upstream PR" line for the proposal-checks summary comment: a
prefilled compare-across-forks link (or, once one exists, a direct link to
the already-open upstream PR) from this fork's proposal branch to its
upstream parent repo. Pure/no-network -- the gh lookups (parent repo, an
existing upstream PR) are done by the caller and passed in.
"""
import re
from urllib.parse import urlencode

HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)$", re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
NO_SUMMARY_NOTE = " (no Simple Summary found; add a body by hand)"


def extract_simple_summary(markdown: str) -> str:
    """Returns the plain-text body of the "## Simple Summary" section (any
    heading level), or "" if the proposal .md has none."""
    if not markdown:
        return ""
    headings = [(m.start(), len(m.group(1)), m.group(2).strip()) for m in HEADING_RE.finditer(markdown)]
    matches = [h for h in headings if h[2].strip().lower() == "simple summary"]
    if not matches:
        return ""
    start_pos, level, _ = matches[0]
    start = start_pos + markdown[start_pos:].index("\n") + 1 if "\n" in markdown[start_pos:] else len(markdown)
    end = len(markdown)
    for pos, lvl, _ in headings:
        if pos <= start_pos:
            continue
        if lvl <= level:
            end = pos
            break
    return markdown[start:end].strip()


def first_two_sentences(text: str) -> str:
    if not text:
        return ""
    sentences = _SENTENCE_SPLIT_RE.split(text.strip())
    return " ".join(s.strip() for s in sentences[:2] if s.strip())


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
    fork_pr_url: str,
    simple_summary: str,
    existing_pr: dict = None,
) -> str:
    if not is_fork:
        return ""
    if existing_pr:
        return f"Upstream PR: [{parent_repo}#{existing_pr['number']}]({existing_pr['html_url']}) ({existing_pr['state']})"

    summary = (simple_summary or "").strip()
    body = f"{summary}\n\nInternal review: {fork_pr_url}" if summary else f"Internal review: {fork_pr_url}"
    url = compare_url(parent_repo, parent_default_branch, fork_owner, fork_repo, head_branch, pr_title, body)
    note = "" if summary else NO_SUMMARY_NOTE
    return f"Upstream PR: [open a prefilled PR on {parent_repo}]({url}){note}"


def main():
    import json
    import sys

    payload = json.load(sys.stdin)
    out = render_upstream_pr_line(
        payload["is_fork"],
        payload.get("parent_repo", ""),
        payload.get("parent_default_branch", ""),
        payload.get("fork_owner", ""),
        payload.get("fork_repo", ""),
        payload.get("head_branch", ""),
        payload.get("pr_title", ""),
        payload.get("fork_pr_url", ""),
        payload.get("simple_summary", ""),
        payload.get("existing_pr"),
    )
    sys.stdout.write(out)


if __name__ == "__main__":
    main()

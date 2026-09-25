#!/usr/bin/env python3
"""Builds the proposal-checks summary comment: one line per check with its
pass/fail/warning icon, and for a failing blocking check, a compact table
of what actually went wrong with file:line links to the PR head. Never
fails on its own -- called from a job that must post something even when
every upstream job errored."""
import sys

from sanitize import sanitize_markdown

CHECK_ORDER = ["address-book", "spelling", "coverage", "advisory"]
BLOCKING = {"address-book", "spelling", "coverage"}


def _icon(name: str, result: str, advisory_has_issues: bool) -> str:
    if name == "advisory":
        if result != "success":
            return "❌"
        return "⚠️" if advisory_has_issues else "✅"
    return "✅" if result == "success" else "❌"


def _blob_link(repo: str, head_sha: str, file: str, line: str) -> str:
    if not repo or not head_sha or not file:
        return file or "?"
    short = file.rsplit("/", 1)[-1]
    url = f"https://github.com/{repo}/blob/{head_sha}/{file}#L{line}"
    return f"[{short}:{line}]({url})"


def _render_address_book_table(raw_detail: str, repo: str, head_sha: str) -> str:
    rows = []
    for line in raw_detail.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        file, ln, msg = parts
        link = _blob_link(repo, head_sha, file, ln)
        rows.append(f"| {link} | {sanitize_markdown(msg, 200)} |")
    if not rows:
        return "(no details captured)"
    return "| File:Line | Issue |\n|---|---|\n" + "\n".join(rows)


def _render_spelling_table(raw_detail: str, repo: str, head_sha: str) -> str:
    rows = []
    for line in raw_detail.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 4)
        if len(parts) != 5:
            continue
        file, ln, word, sugg, context = parts
        link = _blob_link(repo, head_sha, file, ln)
        sugg = sugg or "—"
        marked_context = context.replace(word, f"**{word}**") if word else context
        rows.append(
            f"| {link} | **{sanitize_markdown(word, 60)}** | {sanitize_markdown(sugg, 60)} | "
            f"{sanitize_markdown(marked_context, 80)} |"
        )
    if not rows:
        return "(no details captured)"
    return "| File:Line | Word | Suggestion | Context |\n|---|---|---|---|\n" + "\n".join(rows)


def render(
    results: dict,
    details: dict,
    coverage_pct: str,
    coverage_min: str,
    advisory_url: str,
    advisory_has_issues: bool = False,
    repo: str = "",
    head_sha: str = "",
) -> str:
    lines = ["**Check summary**", ""]
    for name in CHECK_ORDER:
        result = results.get(name, "unknown")
        lines.append(f"- {_icon(name, result, advisory_has_issues)} **{name}**")

    for name in CHECK_ORDER:
        result = results.get(name, "unknown")
        if result == "success" or name not in BLOCKING:
            continue
        raw_detail = details.get(name, "").strip()
        lines.append("")
        if name == "coverage":
            header = f"coverage: {coverage_pct or '?'}% measured, {coverage_min or '?'}% required"
            body_lines = [header]
            if raw_detail:
                body_lines.append("uncovered lines (sample):")
                body_lines.extend(f"  {line}" for line in raw_detail.splitlines() if line.strip())
            safe_lines = [sanitize_markdown(line, 300) for line in body_lines if line.strip()]
            block = "\n".join(f"> 🔴 {line}" for line in safe_lines) or "> 🔴 (no details captured)"
            lines.append(f"> [!CAUTION]\n> **{name} failed**\n{block}")
        elif name == "address-book":
            lines.append(f"**{name} failed**\n\n" + _render_address_book_table(raw_detail, repo, head_sha))
        elif name == "spelling":
            lines.append(f"**{name} failed**\n\n" + _render_spelling_table(raw_detail, repo, head_sha))

    if results.get("advisory") and advisory_url:
        lines.append("")
        lines.append(f"Advisory comment (forum-vs-payload spec check): {advisory_url}")

    return "\n".join(lines)


def main():
    import json

    payload = json.load(sys.stdin)
    out = render(
        payload["results"],
        payload["details"],
        payload.get("coverage_pct", ""),
        payload.get("coverage_min", ""),
        payload.get("advisory_url", ""),
        payload.get("advisory_has_issues", False),
        payload.get("repo", ""),
        payload.get("head_sha", ""),
    )
    sys.stdout.write(out)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Builds the proposal-checks advisory comment body: deterministic
comparison (spec_compare) of the model's strict-JSON forum extraction
against the diff report's deterministically parsed payload actions
(diff_parser), rendered as alert blocks the model cannot forge itself.
"""
import json
import sys

import address_book
import diff_parser
import readable_actions
import spec_compare
from sanitize import sanitize_markdown

SCALE_OUTPUT_CAP = 4000
# A readable finding line now always carries full, unshortened addresses
# (address_book.describe_address) -- 300 chars was tight enough to cut a
# seed summary mid-word ("... (raw, d"). 800 comfortably fits the longest
# real line across every committed fixture (the PR #231 seed summary, the
# longest, is well under 400) with headroom for a busier proposal, while
# still guarding against a pathological/adversarial input.
FINDING_LINE_CAP = 800
SEED_NOTE_PREFIX = "Listing seed (required for every new listing): "
NO_SEED_FORUM_LINE = "Forum: no seed deposit found in the forum post"


def _truncate_at_word_boundary(text: str, max_len: int) -> str:
    """Cuts `text` to at most `max_len` chars at the last whitespace
    boundary and appends "…", instead of slicing mid-word. `text` is
    assumed already <= max_len is not required -- this both shortens and
    cleans up a hard cut a prior step may have made."""
    if len(text) <= max_len:
        return text
    cut = text[: max_len - 1]
    boundary = cut.rfind(" ")
    if boundary > 0:
        cut = cut[:boundary]
    return cut.rstrip() + "…"


def _parse_forum_json(ai_out_text: str):
    text = ai_out_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None, "AI extraction failed: model did not return valid JSON"
    if not isinstance(data, dict) or "forum" not in data or not isinstance(data["forum"], list):
        return None, "AI extraction failed: JSON missing a 'forum' list"
    if data.get("error"):
        return None, f"AI extraction failed: {data['error']}"
    return data["forum"], None


def render_pr_description_alert(unresolved_items: list) -> str:
    """Flags an unfinished fork PR description -- an unedited PR-template
    line, or an unticked checklist box -- still in the way of the Upstream
    PR prefill (upstream_pr.find_unresolved_template_items)."""
    if not unresolved_items:
        return ""
    lines = [f"> 🟠 {sanitize_markdown(item, 200)}" for item in unresolved_items[:10]]
    return (
        "> [!WARNING]\n> **PR description looks unfinished** (still has unedited template "
        "text or unticked checklist boxes -- this also becomes the Upstream PR body):\n"
        + "\n".join(lines)
    )


def render_scale_alert(scale_check_output: str) -> str:
    flags = [
        line.strip()
        for line in scale_check_output.splitlines()
        if line.strip()
        and line.strip() != "no scale-bound flags"
        and not line.startswith("no diff report was generated")
    ]
    if not flags:
        return "> [!NOTE]\n> No decimals-scale issues found."
    lines = [f"> 🔴 {sanitize_markdown(line, 300)}" for line in flags]
    return "> [!CAUTION]\n" + "\n".join(lines)


def _forum_seed_line(forum_item) -> str:
    if forum_item is None:
        return NO_SEED_FORUM_LINE
    described = " ".join(
        str(forum_item.get(key) or "") for key in ("action", "amount", "asset")
    ).split()
    return f"Forum: {' '.join(described)} to {forum_item.get('recipient') or 'unknown recipient'}"


def split_listing_seeds(readable_findings, forum_only, solidity_labels, chain):
    """Splits out the listing seeds the address book proves go to the
    instance's DUST_BIN through the instance's POOL (the seed every new
    listing requires), at most one per new reserve (a later seed of the same
    reserve stays a warning), and pairs each with at most one unmatched
    forum item. Returns (remaining_findings,
    seed_notes, remaining_forum_only); `forum_only` is not modified. Without
    an address book nothing is split out, so every seed stays a warning."""
    forum_left = list(forum_only)
    remaining, seed_notes = [], []
    noted_reserves = set()
    for finding in readable_findings:
        is_proven_seed = (
            finding.get("kind") == readable_actions.LISTING_SEED_KIND
            and finding.get("reserve") not in noted_reserves
            and address_book.names_book_constant(
                finding.get("beneficiary"), solidity_labels, chain, address_book.DUST_BIN_CONSTANT
            )
            and address_book.names_book_constant(
                finding.get("pool"), solidity_labels, chain, address_book.POOL_CONSTANT
            )
        )
        if not is_proven_seed:
            remaining.append(finding)
            continue
        noted_reserves.add(finding["reserve"])
        paired = spec_compare.pop_seed_forum_item(forum_left, finding.get("asset_symbol"))
        seed_notes.append({**finding, "forum_line": _forum_seed_line(paired)})
    return remaining, seed_notes, forum_left


def _render_seed_notes(seed_notes) -> str:
    lines = []
    for note in seed_notes:
        raw_lines = [f"> {SEED_NOTE_PREFIX}{note['line']}"]
        raw_lines += [f">   - {sub}" for sub in note["sub_lines"]]
        raw_lines.append(f">   - {note['forum_line']}")
        lines += [_truncate_at_word_boundary(sanitize_markdown(raw), FINDING_LINE_CAP) for raw in raw_lines]
    return "> [!NOTE]\n" + "\n".join(lines)


def render_comparison_alerts(
    comparison: dict, readable_findings: list, omitted_index_updates: int = 0, seed_notes: list = ()
) -> str:
    """`readable_findings` is required (not `None`-defaulted): a caller
    that forgets to build it must fail loudly, not silently print "No
    mismatches found" while `comparison["unexplained"]` is nonempty."""
    blocks = []
    if readable_findings:
        lines = []
        for finding in readable_findings:
            # sanitize BEFORE the word-boundary cut, uncapped (its own
            # default max_len is a generous 20000) -- if it cut to
            # FINDING_LINE_CAP itself first, the result would already sit
            # exactly at the cap and look "not over it" to the boundary
            # cut below, silently keeping the mid-word truncation.
            raw = f"> 🟠 In payload but not in the forum post: {finding['line']}"
            lines.append(_truncate_at_word_boundary(sanitize_markdown(raw), FINDING_LINE_CAP))
            for sub in finding.get("sub_lines", []):
                sub_raw = f">   - {sub}"
                lines.append(_truncate_at_word_boundary(sanitize_markdown(sub_raw), FINDING_LINE_CAP))
        blocks.append("> [!WARNING]\n" + "\n".join(lines))
    if comparison["warnings"]:
        lines = [
            sanitize_markdown(f"> 🟠 Mismatch: {w['label']}: {w['detail']}", 300)
            for w in comparison["warnings"]
        ]
        blocks.append("> [!WARNING]\n" + "\n".join(lines))
    if not readable_findings and not comparison["warnings"]:
        blocks.append("> [!NOTE]\n> No mismatches found between the payload and the forum post.")
    if seed_notes:
        blocks.append(_render_seed_notes(seed_notes))
    if comparison.get("notes"):
        lines = [
            sanitize_markdown(f"> {n['label']}: {n['detail']}", 300) for n in comparison["notes"]
        ]
        blocks.append("> [!NOTE]\n" + "\n".join(lines))
    if omitted_index_updates:
        word = "update" if omitted_index_updates == 1 else "updates"
        blocks.append(
            f"> [!NOTE]\n> {omitted_index_updates} reserve index {word} "
            "(accounting, not payments) omitted from the comparison."
        )
    if comparison["forum_only_count"] > 0:
        blocks.append(
            f"<details><summary>{comparison['forum_only_count']} other forum items are not in this "
            "payload (expected when a proposal is split into parts)</summary>\n\nThese are not "
            "flagged: a forum post can cover a whole funding update that ships as several separate "
            "payloads.\n\n</details>"
        )
    return "\n\n".join(blocks)


def build(
    ai_out_text: str,
    diff_report_text: str,
    scale_out_text: str,
    fork_test_status: str = "",
    pr_description_unresolved: list = None,
    address_book_root: str = None,
) -> str:
    forum_items, error = _parse_forum_json(ai_out_text)
    parts = ["**Forum-vs-payload spec check (advisory, not a review or approval)**", ""]

    pr_description_alert = render_pr_description_alert(pr_description_unresolved or [])
    if pr_description_alert:
        parts.append(pr_description_alert)
        parts.append("")

    if error:
        parts.append(f"> [!NOTE]\n> {sanitize_markdown(error, 300)}")
        parts.append("")
        parts.append(render_scale_alert(scale_out_text))
        return "\n".join(parts)

    payload_items = diff_parser.parse_payload_actions(diff_report_text)
    if not payload_items:
        fork_test_status = fork_test_status.strip()
        if fork_test_status:
            parts.append(
                f"> [!WARNING]\n> the fork test failed, so the diff report could not be generated: "
                f"{sanitize_markdown(fork_test_status, 300)}"
            )
        else:
            parts.append(
                "> [!NOTE]\n> The diff report has no parseable state-change entries for this run "
                "(the fork test may not have completed) -- comparison against the forum post was skipped."
            )
        parts.append("")
        parts.append(render_scale_alert(scale_out_text))
        return "\n".join(parts)

    comparison = spec_compare.compare(forum_items, payload_items)
    label_map, symbol_map = address_book.build_maps(diff_report_text)
    new_reserves = address_book.new_reserves(diff_report_text)
    # A missing/empty address_book_root degrades to {} (no book) rather than
    # raising -- callers that don't pass one at all get today's behaviour.
    solidity_labels = address_book.load_solidity_labels(address_book_root)
    chain = address_book.infer_chain(diff_report_text)
    readable_findings = readable_actions.build_readable_findings(
        comparison["unexplained"], label_map, symbol_map, new_reserves, solidity_labels, chain
    )
    readable_findings, seed_notes, forum_only = split_listing_seeds(
        readable_findings, comparison["forum_only"], solidity_labels, chain
    )
    comparison = {**comparison, "forum_only": forum_only, "forum_only_count": len(forum_only)}
    # Counted from the RAW diff report, not the deduped `payload_items` --
    # the same reserve index can legitimately update more than once in one
    # execution, and each occurrence was real, omitted activity.
    omitted_index_updates = diff_parser.count_reserve_data_updates(diff_report_text)
    parts.append(render_comparison_alerts(comparison, readable_findings, omitted_index_updates, seed_notes))
    parts.append("")
    parts.append(render_scale_alert(scale_out_text))
    return "\n".join(parts)


def main():
    ai_out_path, diff_report_path, scale_out_path, out_path = (
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    )
    fork_status_path = sys.argv[5] if len(sys.argv) > 5 else None
    pr_body_path = sys.argv[6] if len(sys.argv) > 6 else None
    pr_template_path = sys.argv[7] if len(sys.argv) > 7 else None
    # Optional and additive: an absent arg (old callers) degrades to no
    # Solidity address-book source, never an error.
    address_book_root = sys.argv[8] if len(sys.argv) > 8 else None
    with open(ai_out_path, encoding="utf-8") as f:
        ai_out_text = f.read()
    try:
        with open(diff_report_path, encoding="utf-8") as f:
            diff_report_text = f.read()
    except (FileNotFoundError, OSError):
        diff_report_text = ""
    try:
        with open(scale_out_path, encoding="utf-8") as f:
            scale_out_text = f.read()[:SCALE_OUTPUT_CAP]
    except FileNotFoundError:
        scale_out_text = ""
    fork_test_status = ""
    if fork_status_path:
        try:
            with open(fork_status_path, encoding="utf-8") as f:
                fork_test_status = f.read()
        except FileNotFoundError:
            fork_test_status = ""
    pr_description_unresolved = []
    if pr_body_path and pr_template_path:
        import upstream_pr

        try:
            with open(pr_body_path, encoding="utf-8") as f:
                pr_body_text = f.read()
        except FileNotFoundError:
            pr_body_text = ""
        try:
            with open(pr_template_path, encoding="utf-8") as f:
                pr_template_text = f.read()
        except FileNotFoundError:
            pr_template_text = ""
        pr_description_unresolved = upstream_pr.find_unresolved_template_items(pr_body_text, pr_template_text)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(
            build(
                ai_out_text,
                diff_report_text,
                scale_out_text,
                fork_test_status,
                pr_description_unresolved,
                address_book_root,
            )
        )


if __name__ == "__main__":
    main()

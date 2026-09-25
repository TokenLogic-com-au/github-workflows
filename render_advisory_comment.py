#!/usr/bin/env python3
"""Builds the proposal-checks advisory comment body: deterministic
comparison (spec_compare) of the model's strict-JSON forum extraction
against the diff report's deterministically parsed payload actions
(diff_parser), rendered as alert blocks the model cannot forge itself.
"""
import json
import sys

import diff_parser
import spec_compare
from sanitize import sanitize_markdown

SCALE_OUTPUT_CAP = 4000


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


def render_comparison_alerts(comparison: dict) -> str:
    blocks = []
    if comparison["unexplained"]:
        lines = []
        for p in comparison["unexplained"]:
            line = f"> 🔴 In payload but not in the forum post: amount `{p.get('amount')}`"
            if p.get("recipient"):
                line += f", recipient `{p.get('recipient')}`"
            lines.append(sanitize_markdown(line, 300))
        blocks.append("> [!CAUTION]\n" + "\n".join(lines))
    if comparison["warnings"]:
        lines = [
            sanitize_markdown(f"> 🟠 Mismatch: {w['label']}: {w['detail']}", 300)
            for w in comparison["warnings"]
        ]
        blocks.append("> [!WARNING]\n" + "\n".join(lines))
    if not comparison["unexplained"] and not comparison["warnings"]:
        blocks.append("> [!NOTE]\n> No mismatches found between the payload and the forum post.")
    if comparison["forum_only_count"] > 0:
        blocks.append(
            f"<details><summary>{comparison['forum_only_count']} other forum items are not in this "
            "payload (expected when a proposal is split into parts)</summary>\n\nThese are not "
            "flagged: a forum post can cover a whole funding update that ships as several separate "
            "payloads.\n\n</details>"
        )
    return "\n\n".join(blocks)


def build(ai_out_text: str, diff_report_text: str, scale_out_text: str, fork_test_status: str = "") -> str:
    forum_items, error = _parse_forum_json(ai_out_text)
    parts = ["**Forum-vs-payload spec check (advisory, not a review or approval)**", ""]

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
    parts.append(render_comparison_alerts(comparison))
    parts.append("")
    parts.append(render_scale_alert(scale_out_text))
    return "\n".join(parts)


def main():
    ai_out_path, diff_report_path, scale_out_path, out_path = (
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    )
    fork_status_path = sys.argv[5] if len(sys.argv) > 5 else None
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
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(build(ai_out_text, diff_report_text, scale_out_text, fork_test_status))


if __name__ == "__main__":
    main()

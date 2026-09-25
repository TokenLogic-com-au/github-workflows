#!/usr/bin/env python3
"""Builds the ai-comment.yml PR/issue comment body from the model's strict
JSON output (prompts/review.md, prompts/scope.md), in OUR markdown -- the
model's own text never reaches GitHub except through sanitize_markdown()
inside a bounded field. Invalid/missing JSON renders one neutral note, never
the raw model text.

Also builds the one-item results.json handed to the bot's
issue_quality.py (the "results" mode below) from the same parsed scope
output, so both consumers share one JSON-parsing path.
"""
import json
import sys

from sanitize import sanitize_markdown

FIELD_CAP = 300
NOTE_CAP = 500
TOPIC_CAP = 80

STATUS_ICON = {"delivered": "✅", "partial": "🟡", "missing": "❌", "unverifiable": "❔"}


def parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _clean(value, cap=FIELD_CAP) -> str:
    if value is None:
        return ""
    return sanitize_markdown(str(value), cap)


def _footer() -> str:
    return "_advisory, not a review_"


def build_header(kind: str, number) -> str:
    if kind == "review":
        return f"**AI review — PR #{number}**"
    return f"**AI scope check — issue #{number}**"


def _neutral(header: str) -> str:
    lines = [
        header,
        "",
        "_The AI response could not be parsed as structured output; no comment "
        "content was generated for this run._",
        "",
        _footer(),
    ]
    return "\n".join(lines) + "\n"


def _fmt_finding(f: dict) -> str:
    file_ = _clean(f.get("file"), 200)
    line = _clean(f.get("line"), 40)
    loc = f"{file_}:{line}" if file_ else (line or "?")
    defect = _clean(f.get("defect"), FIELD_CAP)
    matches = _clean(f.get("matches"), 200)
    text = f"{loc} — {defect}"
    if matches:
        text += f" — {matches}"
    if f.get("uncertain"):
        text += " (uncertain)"
    return text


def render_review(ai_out_text: str, number) -> str:
    header = build_header("review", number)
    data = parse_json(ai_out_text)
    if not isinstance(data, dict) or "deliverables" not in data or "findings" not in data:
        return _neutral(header)

    lines = [header, ""]

    deliverables = [d for d in (data.get("deliverables") or []) if isinstance(d, dict)]
    if deliverables:
        lines.append("| Deliverable | Status | Note |")
        lines.append("|---|---|---|")
        for d in deliverables:
            status = d.get("status")
            icon = STATUS_ICON.get(status, "❔")
            item = _clean(d.get("item"))
            note = _clean(d.get("note"), NOTE_CAP)
            lines.append(f"| {item} | {icon} {_clean(status, 20)} | {note} |")
        lines.append("")

    findings = [f for f in (data.get("findings") or []) if isinstance(f, dict)]
    blockers = [f for f in findings if f.get("severity") == "blocker"]
    should_fix = [f for f in findings if f.get("severity") == "should-fix"]
    nits = [f for f in findings if f.get("severity") == "nit"]

    if blockers:
        lines.append("> [!CAUTION]")
        for f in blockers:
            lines.append(f"> 🔴 {_fmt_finding(f)}")
        lines.append("")

    if should_fix:
        lines.append("**Should-fix**")
        for f in should_fix:
            lines.append(f"- 🟠 {_fmt_finding(f)}")
        lines.append("")

    if nits:
        lines.append("<details><summary>Nits</summary>")
        lines.append("")
        for f in nits:
            lines.append(f"- {_fmt_finding(f)}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    more_count = data.get("more_count")
    if isinstance(more_count, int) and more_count > 0:
        lines.append(f"_+{more_count} more_")
        lines.append("")

    if not deliverables and not blockers and not should_fix and not nits:
        lines.append("_No findings._")
        lines.append("")

    lines.append(_footer())
    return "\n".join(lines).rstrip("\n") + "\n"


def render_scope(ai_out_text: str, number) -> str:
    header = build_header("scope", number)
    data = parse_json(ai_out_text)
    if not isinstance(data, dict) or "questions" not in data:
        return _neutral(header)

    lines = [header, ""]
    questions = [q for q in (data.get("questions") or []) if isinstance(q, dict)]
    if questions:
        for i, q in enumerate(questions, 1):
            topic = _clean(q.get("topic"), TOPIC_CAP)
            question = _clean(q.get("question"), FIELD_CAP)
            label = f"**{topic}:** " if topic else ""
            lines.append(f"{i}. {label}{question}")
        lines.append("")
    else:
        lines.append("Ready to start.")
        lines.append("")

    flags = [_clean(f, FIELD_CAP) for f in (data.get("flags") or []) if isinstance(f, str) and f.strip()]
    if flags:
        lines.append("> [!NOTE]")
        for fl in flags:
            lines.append(f"> {fl}")
        lines.append("")

    lines.append(_footer())
    return "\n".join(lines).rstrip("\n") + "\n"


def build_results(ai_out_text: str, number, title: str, url: str, assignees, author: str = "") -> list:
    data = parse_json(ai_out_text)
    questions = []
    flags = []
    if isinstance(data, dict):
        for q in data.get("questions") or []:
            if isinstance(q, dict) and q.get("topic") and q.get("question"):
                questions.append({"topic": str(q["topic"]), "question": str(q["question"])})
        for f in data.get("flags") or []:
            if isinstance(f, str) and f.strip():
                flags.append(f)
    return [
        {
            "number": int(number),
            "title": title,
            "url": url,
            "assignees": list(assignees or []),
            "questions": questions,
            "flags": flags,
            "author": author,
        }
    ]


def main():
    mode = sys.argv[1]
    if mode in ("review", "scope"):
        ai_out_path, number, out_path = sys.argv[2], sys.argv[3], sys.argv[4]
        with open(ai_out_path, encoding="utf-8") as f:
            ai_out_text = f.read()
        render = render_review if mode == "review" else render_scope
        body = render(ai_out_text, number)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(body)
    elif mode == "results":
        ai_out_path, number, title, url, assignees_json, out_path = sys.argv[2:8]
        author = sys.argv[8] if len(sys.argv) > 8 else ""
        with open(ai_out_path, encoding="utf-8") as f:
            ai_out_text = f.read()
        assignees = json.loads(assignees_json) if assignees_json.strip() else []
        results = build_results(ai_out_text, number, title, url, assignees, author)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f)
    else:
        sys.exit(f"unknown mode: {mode}")


if __name__ == "__main__":
    main()

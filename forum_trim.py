"""Deterministically trims a governance forum post down to its Motivation,
Specification and Next Steps sections before it goes to the model -- cuts
token usage on long funding-update posts that cover many payloads, while
keeping the seed-deposit sentence a listing post states under Next Steps.
Each wanted heading starts a section that runs to the next heading of the
same or higher level; the sections are joined in document order, and a
wanted heading nested inside another wanted section is not repeated. Falls
back to the full post when no matching heading is found, so a
differently-formatted post is never silently truncated to nothing.
"""
import re

HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)$", re.MULTILINE)
WANTED_NAMES = ("motivation", "specification", "next steps")


def trim_to_specification(forum_text: str) -> str:
    if not forum_text or not forum_text.strip():
        return forum_text

    headings = [(m.start(), len(m.group(1)), m.group(2).strip().lower()) for m in HEADING_RE.finditer(forum_text)]
    sections = []
    covered_until = 0
    for i, (start, level, name) in enumerate(headings):
        if not name.startswith(WANTED_NAMES) or start < covered_until:
            continue
        end = next((pos for pos, lvl, _ in headings[i + 1 :] if lvl <= level), len(forum_text))
        sections.append(forum_text[start:end].strip())
        covered_until = end

    trimmed = "\n\n".join(section for section in sections if section)
    return trimmed if trimmed else forum_text


if __name__ == "__main__":
    import sys

    with open(sys.argv[1], encoding="utf-8") as f:
        text = f.read()
    sys.stdout.write(trim_to_specification(text))

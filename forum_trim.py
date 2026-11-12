"""Trims a forum post to its Motivation, Specification and Next Steps sections; returns the full post if no Motivation/Specification heading exists."""
import re

HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)$", re.MULTILINE)
CORE_NAMES = ("motivation", "specification")
EXTRA_NAME = "next steps"
WANTED_NAMES = CORE_NAMES + (EXTRA_NAME,)


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

    if not any(name.startswith(CORE_NAMES) for _, _, name in headings):
        return forum_text
    return "\n\n".join(section for section in sections if section)


if __name__ == "__main__":
    import sys

    with open(sys.argv[1], encoding="utf-8") as f:
        text = f.read()
    sys.stdout.write(trim_to_specification(text))

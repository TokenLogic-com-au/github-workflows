"""Deterministically trims a governance forum post down to its
Specification (and Motivation, if present) section(s) before it goes to the
model -- cuts token usage on long funding-update posts that cover many
payloads. Falls back to the full post when no matching heading is found, so
a differently-formatted post is never silently truncated to nothing.
"""
import re

HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)$", re.MULTILINE)
WANTED_NAMES = ("motivation", "specification")


def trim_to_specification(forum_text: str) -> str:
    if not forum_text or not forum_text.strip():
        return forum_text

    headings = [(m.start(), len(m.group(1)), m.group(2).strip()) for m in HEADING_RE.finditer(forum_text)]
    wanted = [h for h in headings if h[2].strip().lower().split()[:1] and h[2].strip().lower().startswith(WANTED_NAMES)]
    if not wanted:
        return forum_text

    start = wanted[0][0]
    section_level = wanted[0][1]
    end = len(forum_text)
    for pos, level, name in headings:
        if pos <= start:
            continue
        is_wanted_section_start = name.strip().lower().startswith(WANTED_NAMES) and level == section_level
        if is_wanted_section_start:
            continue
        if level <= section_level:
            end = pos
            break

    trimmed = forum_text[start:end].strip()
    return trimmed if trimmed else forum_text


if __name__ == "__main__":
    import sys

    with open(sys.argv[1], encoding="utf-8") as f:
        text = f.read()
    sys.stdout.write(trim_to_specification(text))

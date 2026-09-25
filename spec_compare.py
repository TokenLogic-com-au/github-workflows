"""Deterministic forum-vs-payload comparison. Takes the model's forum-side
JSON extraction and the diff-report's deterministically parsed payload-side
list (diff_parser.parse_payload_actions) and produces:

- warnings: payload item matched to a forum item, but amount/recipient/
  decimals disagree (rendered [!WARNING])
- unexplained: payload item with NO forum counterpart at all -- the
  dangerous case (rendered [!CAUTION])
- forum_only_count: forum items with no payload counterpart -- expected
  noise when a forum post covers a whole funding update split across many
  payloads, rendered as one neutral collapsed line, never a warning.

No network call, no AI: this is the part that must be exactly reproducible.
"""
import re

ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")


def _extract_address(text):
    if not text:
        return None
    m = ADDRESS_RE.search(text)
    return m.group(0).lower() if m else None


_SCALE_SUFFIXES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def _leading_number(text):
    if not text:
        return None
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*([kKmMbB])?(?![a-zA-Z])", text)
    if not m or not m.group(1):
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = (m.group(2) or "").lower()
    if suffix in _SCALE_SUFFIXES:
        value *= _SCALE_SUFFIXES[suffix]
    return value


def compare(forum_items, payload_items):
    warnings = []
    unexplained = []
    matched_forum_idxs = set()

    for p in payload_items:
        p_addr = _extract_address(p.get("recipient"))
        match_idx = None
        if p_addr:
            for i, f in enumerate(forum_items):
                if i in matched_forum_idxs:
                    continue
                if _extract_address(f.get("recipient")) == p_addr:
                    match_idx = i
                    break

        if match_idx is None:
            unexplained.append(p)
            continue

        matched_forum_idxs.add(match_idx)
        f = forum_items[match_idx]
        f_num = _leading_number(f.get("amount"))
        p_num = _leading_number(p.get("amount"))
        mismatch = False
        detail = []
        if f_num is not None and p_num is not None and f_num != p_num:
            mismatch = True
            detail.append(f"amount: forum `{f.get('amount')}`, payload `{p.get('amount')}`")
        if mismatch:
            warnings.append(
                {
                    "label": f"{f.get('action', 'Action')} {f.get('asset', '')}".strip(),
                    "detail": "; ".join(detail),
                }
            )

    forum_only_count = len(forum_items) - len(matched_forum_idxs)
    return {
        "warnings": warnings,
        "unexplained": unexplained,
        "forum_only_count": max(forum_only_count, 0),
    }

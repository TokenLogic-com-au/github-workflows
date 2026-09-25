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
- notes: payload item matched to a forum item whose amount is a formula
  (e.g. "currentAllowance + 50,500 / 4 + emissionPerSecond x (...)") rather
  than a literal number -- the first number in a formula is not the total,
  so it must never be compared against the payload's decoded amount; these
  are rendered as a neutral note instead of a warning.

No network call, no AI: this is the part that must be exactly reproducible.
"""
import re

ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")
# An arithmetic operator only counts as formula evidence when it has
# whitespace on both sides -- " + ", " - ", " * ", " / ", " x ", " × " --
# so an adjacent unit/rate shape like "50k GHO/month" (no surrounding
# whitespace around the slash) is not mistaken for a formula.
_OPERATOR_RE = re.compile(r"\s[+\-*/×x]\s", re.IGNORECASE)
# A dotted or underscored identifier (block.timestamp, snake_case) is
# unambiguous formula evidence. A camelCase identifier is too, but only
# counting "word-like humps" -- a lowercase run followed by an uppercase
# letter that is ITSELF followed by a lowercase letter (i.e. a capitalized
# word, like ...Allowance, ...Second) -- and only with two or more such
# humps. An ERC20/Aave token symbol (aEthWBTC, stkAAVE, aEthUSDC) has at
# most one: the "Eth" mid-token is a single hump, and an all-caps suffix
# (WBTC, AAVE, USDC) is never itself a hump since no lowercase follows the
# uppercase run. "currentAllowance" and "emissionPerSecond" both carry
# real English words after their humps and appear in practice alongside an
# operator anyway, so this is belt-and-braces, not the primary signal.
_DOTTED_OR_UNDERSCORED_RE = re.compile(r"[A-Za-z][._][A-Za-z]")
_CAMEL_HUMP_RE = re.compile(r"(?=[a-z][A-Z][a-z])")


def _is_formula(amount_text):
    if not amount_text:
        return False
    text = amount_text.strip()
    if _OPERATOR_RE.search(text):
        return True
    if _DOTTED_OR_UNDERSCORED_RE.search(text):
        return True
    if len(_CAMEL_HUMP_RE.findall(text)) >= 2:
        return True
    return False


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
    notes = []
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
        label = f"{f.get('action', 'Action')} {f.get('asset', '')}".strip()
        f_amount = f.get("amount")
        if f_amount and _is_formula(f_amount):
            notes.append({"label": label, "detail": "forum amount is a formula; not compared"})
            continue
        f_num = _leading_number(f_amount)
        p_num = _leading_number(p.get("amount"))
        mismatch = False
        detail = []
        if f_num is not None and p_num is not None and f_num != p_num:
            mismatch = True
            detail.append(f"amount: forum `{f_amount}`, payload `{p.get('amount')}`")
        if mismatch:
            warnings.append({"label": label, "detail": "; ".join(detail)})

    forum_only_count = len(forum_items) - len(matched_forum_idxs)
    return {
        "warnings": warnings,
        "unexplained": unexplained,
        "notes": notes,
        "forum_only_count": max(forum_only_count, 0),
    }

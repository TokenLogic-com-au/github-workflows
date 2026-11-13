"""Deterministic forum-vs-payload comparison.

Outputs: warnings (matched item, amount/recipient/decimals disagree), unexplained (payload item
with no forum counterpart), forum_only (neutral, expected when a post spans many payloads),
notes (forum amount is a formula, so it is never compared to the decoded amount), amount_matches
(forum item with no recipient address, matched on kind, asset and amount only: the recipient
is not proven, so the comment lists each pair for a human check).
"""
import re

SEED_RECIPIENT_MARKER = "executor"
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")
# Operators need whitespace on both sides so "50k GHO/month" is not a formula.
_OPERATOR_RE = re.compile(r"\s[+\-*/×x]\s", re.IGNORECASE)
# Dotted/underscored identifiers and 2+ camelCase word humps are formula evidence; token symbols (aEthWBTC, stkAAVE) have at most one hump.
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


def _is_approval(forum_action):
    return (forum_action or "").casefold().startswith("approv")


def _amount_match(forum_items, matched_forum_idxs, p):
    """Index of an unmatched address-less forum item of the payload's kind, asset and amount; same network first.

    Kind: an allowance moves no tokens, so a forum approval explains only an Approval and a forum movement never does.
    """
    asset = (p.get("asset") or "").casefold()
    p_is_approval = p.get("event_name") == "Approval"
    p_num = _leading_number(p.get("amount"))
    if not asset or p_num is None:
        return None
    candidates = [
        i
        for i, f in enumerate(forum_items)
        if i not in matched_forum_idxs
        and not _extract_address(f.get("recipient"))
        and _is_approval(f.get("action")) == p_is_approval
        and (f.get("asset") or "").casefold() == asset
        and not _is_formula(f.get("amount"))
        and _leading_number(f.get("amount")) == p_num
    ]
    chain = (p.get("chain") or "").casefold()
    same_network = [i for i in candidates if (forum_items[i].get("network") or "").casefold() == chain]
    return (same_network or candidates or [None])[0]


def compare(forum_items, payload_items):
    warnings = []
    unexplained = []
    notes = []
    amount_matches = []
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
            match_idx = _amount_match(forum_items, matched_forum_idxs, p)
            if match_idx is not None:
                matched_forum_idxs.add(match_idx)
                amount_matches.append({"forum": forum_items[match_idx], "payload": p})
                continue
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

    forum_only = [f for i, f in enumerate(forum_items) if i not in matched_forum_idxs]
    return {
        "warnings": warnings,
        "unexplained": unexplained,
        "notes": notes,
        "amount_matches": amount_matches,
        "forum_only": forum_only,
        "forum_only_count": len(forum_only),
    }


def pop_seed_forum_item(forum_only, asset_symbol):
    """Pops the first unmatched forum item depositing `asset_symbol` to an executor, else None; amounts are not compared (forum says USD)."""
    wanted = (asset_symbol or "").casefold()
    for i, f in enumerate(forum_only):
        if (f.get("asset") or "").casefold() == wanted and SEED_RECIPIENT_MARKER in (
            f.get("recipient") or ""
        ).casefold():
            return forum_only.pop(i)
    return None

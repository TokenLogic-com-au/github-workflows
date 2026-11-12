"""Extracts payload actions from a ProtocolV3TestBase diff report; returns [] when unparseable.

Dropped events: BalanceTransfer (scaled mirror of Transfer), from-zero Transfers paired
with a Mint of the same balanceIncrease (interest accrual), and zero Approvals superseded
by a later nonzero Approval for the same owner/spender in the same `####` section.
Everything else is kept, with no value-keyed dedup: events cannot tell transfer() from
transferFrom, so merging equal amounts could hide a live allowance.
"""
import re

from address_book import INLINE_SYMBOL_RE

DECODED_VALUE_RE = re.compile(
    r"(?P<human>[\d,]+(?:\.\d+)?)\s*\[\s*(?P<raw>\d+)\s*,\s*(?P<decimals>\d+)\s*decimals\s*\]"
)
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")
# The sender comes first on event lines, so the recipient is the address after a "to" label.
TO_ADDRESS_RE = re.compile(r"\bto:?\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
FROM_ADDRESS_RE = re.compile(r"\bfrom:?\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
SPENDER_ADDRESS_RE = re.compile(r"\bspender:?\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
OWNER_ADDRESS_RE = re.compile(r"\bowner:?\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
FROM_ZERO_RE = re.compile(r"\bfrom:?\s+0x0{40}\b", re.IGNORECASE)
ON_BEHALF_OF_RE = re.compile(r"\bonBehalfOf:?\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
USER_ADDRESS_RE = re.compile(r"\buser:?\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
BALANCE_INCREASE_RE = re.compile(r"\bbalanceIncrease:?\s*([\d,]+)", re.IGNORECASE)
EVENT_NAME_RE = re.compile(r"\b([A-Z][A-Za-z0-9]*)\(")
SECTION_HEADER_RE = re.compile(r"^####\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
# AToken._mintScaled emits the Mint on the line right after the Transfer; wider risks false pairs.
MINT_PAIR_WINDOW = 1


def _line_kind(line: str) -> str:
    # "BalanceTransfer" contains "Transfer", so it must be tested first.
    if re.search(r"\bBalanceTransfer\(", line):
        return "balance_transfer"
    if re.search(r"\bApproval\(", line):
        return "approval"
    if re.search(r"\bMint\(", line):
        return "mint"
    if re.search(r"\bTransfer\(", line):
        return "transfer"
    return "generic"


def _extract_spender(line: str):
    m = SPENDER_ADDRESS_RE.search(line)
    return m.group(1) if m else None


def _extract_recipient(line: str, kind: str):
    if kind == "approval":
        spender = _extract_spender(line)
        if spender:
            return spender
    m = TO_ADDRESS_RE.search(line)
    if m:
        return m.group(1)
    m = ADDRESS_RE.search(line)
    return m.group(0) if m else None


def _approval_owner_spender(line: str):
    owner = OWNER_ADDRESS_RE.search(line)
    spender = _extract_spender(line)
    return (
        owner.group(1).lower() if owner else None,
        spender.lower() if spender else None,
    )


def _line_sections(lines: list) -> list:
    """Per line: lowercased address of the nearest preceding `#### 0x...` header, else None."""
    sections = []
    current = None
    for line in lines:
        m = SECTION_HEADER_RE.match(line.strip())
        if m:
            current = m.group(1).lower()
        sections.append(current)
    return sections


def _is_superseded_zero_approval(
    approval_line: str, raw: str, lines: list, idx: int, sections: list
) -> bool:
    """Revoke half of a revoke-then-set pair; the section scope keeps other tokens from superseding it."""
    if raw != "0":
        return False
    owner, spender = _approval_owner_spender(approval_line)
    if not owner or not spender:
        return False
    section = sections[idx]
    for later_idx in range(idx + 1, len(lines)):
        if lines[later_idx].startswith("# "):
            return False  # next payload report of a combined report
        if sections[later_idx] != section:
            continue
        later_line = lines[later_idx]
        if _line_kind(later_line) != "approval":
            continue
        later_m = DECODED_VALUE_RE.search(later_line)
        if not later_m or later_m.group("raw") == "0":
            continue
        later_owner, later_spender = _approval_owner_spender(later_line)
        if later_owner == owner and later_spender == spender:
            return True
    return False


def _is_interest_accrual(transfer_line: str, transfer_raw: str, lines: list, idx: int) -> bool:
    """From-zero Transfer followed by a Mint with matching balanceIncrease and onBehalfOf."""
    if not FROM_ZERO_RE.search(transfer_line):
        return False
    recipient = _extract_recipient(transfer_line, "transfer")
    if not recipient:
        return False
    for next_line in lines[idx + 1 : idx + 1 + MINT_PAIR_WINDOW]:
        if _line_kind(next_line) != "mint":
            continue
        on_behalf_of = ON_BEHALF_OF_RE.search(next_line)
        balance_increase = BALANCE_INCREASE_RE.search(next_line)
        if not on_behalf_of or not balance_increase:
            continue
        if on_behalf_of.group(1).lower() != recipient.lower():
            continue
        if balance_increase.group(1).replace(",", "") == transfer_raw:
            return True
    return False


def parse_payload_actions(diff_report_text: str):
    """Returns action dicts extracted from decoded value lines; no value-keyed dedup (see module docstring)."""
    if not diff_report_text or not diff_report_text.strip():
        return []
    actions = []
    lines = diff_report_text.splitlines()
    sections = _line_sections(lines)
    for idx, line in enumerate(lines):
        m = DECODED_VALUE_RE.search(line)
        if not m:
            continue
        kind = _line_kind(line)
        if kind in ("balance_transfer", "mint"):
            continue
        if kind == "transfer" and _is_interest_accrual(line, m.group("raw"), lines, idx):
            continue
        if kind == "approval" and _is_superseded_zero_approval(
            line, m.group("raw"), lines, idx, sections
        ):
            continue
        recipient = _extract_recipient(line, kind)
        event_name_m = EVENT_NAME_RE.search(line)
        inline_symbol_m = INLINE_SYMBOL_RE.search(line)
        if kind == "approval":
            counterparty_m = OWNER_ADDRESS_RE.search(line)
        elif kind == "transfer":
            counterparty_m = FROM_ADDRESS_RE.search(line)
        else:
            counterparty_m = None
        on_behalf_of_m = ON_BEHALF_OF_RE.search(line)
        user_m = USER_ADDRESS_RE.search(line)
        actions.append(
            {
                "action": "Approve" if kind == "approval" else "Transfer",
                "asset": None,
                "amount": m.group("human"),
                "raw_amount": m.group("raw"),
                "decimals": int(m.group("decimals")),
                "recipient": recipient,
                "network": None,
                "raw_line": line.strip(),
                "event_name": event_name_m.group(1) if event_name_m else None,
                "section": sections[idx],
                "counterparty": counterparty_m.group(1) if counterparty_m else None,
                "on_behalf_of": on_behalf_of_m.group(1) if on_behalf_of_m else None,
                "user": user_m.group(1) if user_m else None,
                "inline_symbol": inline_symbol_m.group(2).strip() if inline_symbol_m else None,
            }
        )
    return actions


def count_reserve_data_updates(diff_report_text: str) -> int:
    """Counts decoded ReserveDataUpdated lines in the raw report; each is real activity, not a duplicate."""
    if not diff_report_text:
        return 0
    count = 0
    for line in diff_report_text.splitlines():
        if not DECODED_VALUE_RE.search(line):
            continue
        event_name_m = EVENT_NAME_RE.search(line)
        if event_name_m and event_name_m.group(1) == "ReserveDataUpdated":
            count += 1
    return count

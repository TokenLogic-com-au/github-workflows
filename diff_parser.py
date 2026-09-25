"""Deterministic extraction of payload-side actions from a
ProtocolV3TestBase-generated diff report (diffs/*.md). No AI involved --
the diff report is the ground truth for what the payload actually executes.

Best-effort: this parser targets the common "decoded value" shape the diff
report emits for ERC20 transfer/approval-style state changes, e.g. a line
containing a human amount, a bracketed [raw, N decimals] pair, and a 0x
address. When the diff report is empty or unparseable (for example, if the
fork test could not complete -- a real live-mainnet-state failure unrelated
to any payload bug), this returns an empty list and the caller must say so
plainly rather than inventing payload data.
"""
import re

DECODED_VALUE_RE = re.compile(
    r"(?P<human>[\d,]+(?:\.\d+)?)\s*\[\s*(?P<raw>\d+)\s*,\s*(?P<decimals>\d+)\s*decimals\s*\]"
)
ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")
# ProtocolV3TestBase event-log lines are shaped "from: <sender>, to:
# <recipient>" -- the sender's address comes first on the line, so a plain
# "first address in the line" search picks the wrong one. Prefer the address
# that explicitly follows a "to" label; fall back to the first address in
# the line for shapes that have no "from"/"to" labels at all.
TO_ADDRESS_RE = re.compile(r"\bto:?\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)


def _extract_recipient(line: str):
    m = TO_ADDRESS_RE.search(line)
    if m:
        return m.group(1)
    m = ADDRESS_RE.search(line)
    return m.group(0) if m else None


def parse_payload_actions(diff_report_text: str):
    """Returns a list of {"action", "asset", "amount", "decimals",
    "recipient", "network", "raw_line"} extracted from decoded value lines.

    Deduped on (raw, decimals, recipient) -- the exact underlying integer,
    not the rounded human-readable display amount: an aToken transfer emits
    both a standard Transfer event and Aave's own BalanceTransfer event for
    the same underlying move, and both decode to an identical entry here --
    one real action must not become two duplicate findings downstream. Using
    the display amount instead would also collapse two genuinely different
    raw amounts that happen to round to the same displayed value.
    """
    if not diff_report_text or not diff_report_text.strip():
        return []
    actions = []
    seen = set()
    for line in diff_report_text.splitlines():
        m = DECODED_VALUE_RE.search(line)
        if not m:
            continue
        recipient = _extract_recipient(line)
        key = (m.group("raw"), m.group("decimals"), recipient)
        if key in seen:
            continue
        seen.add(key)
        actions.append(
            {
                "action": "Transfer",
                "asset": None,
                "amount": m.group("human"),
                "decimals": int(m.group("decimals")),
                "recipient": recipient,
                "network": None,
                "raw_line": line.strip(),
            }
        )
    return actions

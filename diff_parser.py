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

Three event shapes are recognized and handled specially, everything else
falls back to the generic "Transfer" shape below:

- `BalanceTransfer` -- Aave's scaled-balance mirror of a `Transfer` on the
  same aToken move. It decodes to a DIFFERENT raw integer than the paired
  `Transfer` (the scaled amount divided by the liquidity index, not the
  same amount twice), so it can never be deduped against the Transfer line
  by (raw, decimals, recipient) -- it is dropped outright; the `Transfer`
  line already carries the real action.
- `Mint(caller, onBehalfOf, value, balanceIncrease, index)` -- never an
  action on its own. When it immediately follows a `Transfer(from: 0x0...0,
  to: X, ...)` with `balanceIncrease` raw == the Transfer's raw value and
  `onBehalfOf` == X, that Transfer is Aave accruing interest to X's aToken
  balance before X's own transfer happens, not a payload-initiated mint --
  it is dropped too. A `Transfer(from: 0x0...0, ...)` NOT paired this way is
  a real mint/supply and still counts.
- `Approval(owner, spender, value)` -- the recipient of an approval is the
  spender, not the first address on the line (which is the owner). A
  zero-value Approval for a given (owner, spender) pair is dropped when a
  LATER Approval line in the SAME `####` contract section of the report
  (i.e. the same emitting token) sets a nonzero allowance for that same
  pair -- the standard revoke-then-set dance, where the zero is transient
  noise and the nonzero line is the real action. Section-scoping matters:
  the Collector revoking token A's allowance to S (0) then approving token
  B to S (nonzero) are two unrelated actions on two different token
  contracts and must not supersede each other. A zero-value Approval with
  no later same-section nonzero Approval for the same pair is a real
  cancel and still counts.
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
SPENDER_ADDRESS_RE = re.compile(r"\bspender:?\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
OWNER_ADDRESS_RE = re.compile(r"\bowner:?\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
FROM_ZERO_RE = re.compile(r"\bfrom:?\s+0x0{40}\b", re.IGNORECASE)
ON_BEHALF_OF_RE = re.compile(r"\bonBehalfOf:?\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
BALANCE_INCREASE_RE = re.compile(r"\bbalanceIncrease:?\s*([\d,]+)", re.IGNORECASE)
# Each diff-report event-log section is headed "#### 0x<contract address>
# (labels...)" -- everything until the next such header is emitted by that
# one contract.
SECTION_HEADER_RE = re.compile(r"^####\s+(0x[0-9a-fA-F]{40})", re.IGNORECASE)
# Lookahead window (in lines) to find the Mint paired with a from-zero
# Transfer. aave-v3-origin's AToken._mintScaled emits the Mint on the very
# next line after the Transfer (AToken.sol:299-305) -- a wider window risks
# pairing a from-zero Transfer with an unrelated later Mint that happens to
# carry the same raw balanceIncrease.
MINT_PAIR_WINDOW = 1


def _line_kind(line: str) -> str:
    # Order matters: "BalanceTransfer" contains "Transfer" as a substring.
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
    """Returns, per line index, the contract address of the nearest
    preceding `#### 0x...` section header (lowercased), or None before the
    first header."""
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
    """True for a zero-value Approval whose (owner, spender) pair gets a
    nonzero Approval later in the SAME contract section of the report --
    the revoke half of a revoke-then-set pair on one token, transient noise
    rather than a payload action. A revoke on one token followed by an
    unrelated approval on a different token must not supersede it."""
    if raw != "0":
        return False
    owner, spender = _approval_owner_spender(approval_line)
    if not owner or not spender:
        return False
    section = sections[idx]
    for later_idx in range(idx + 1, len(lines)):
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
    """True when a from-zero Transfer is paired with a following Mint whose
    balanceIncrease matches the Transfer's raw value and whose onBehalfOf is
    the same recipient -- Aave accruing interest, not a payload action."""
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
    """Returns a list of {"action", "asset", "amount", "decimals",
    "recipient", "network", "raw_line"} extracted from decoded value lines.

    Deduped on (raw, decimals, recipient) -- the exact underlying integer,
    not the rounded human-readable display amount: two genuinely different
    raw amounts that happen to round to the same displayed value must not
    collapse into one finding.
    """
    if not diff_report_text or not diff_report_text.strip():
        return []
    actions = []
    seen = set()
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
        key = (m.group("raw"), m.group("decimals"), recipient)
        if key in seen:
            continue
        seen.add(key)
        actions.append(
            {
                "action": "Approve" if kind == "approval" else "Transfer",
                "asset": None,
                "amount": m.group("human"),
                "decimals": int(m.group("decimals")),
                "recipient": recipient,
                "network": None,
                "raw_line": line.strip(),
            }
        )
    return actions

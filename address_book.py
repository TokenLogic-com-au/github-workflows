"""Builds address -> plain-language name lookups straight from a diff
report's own text -- no external address-book dependency. ProtocolV3TestBase
already prints the address-book label(s) on every `####`/`###` event-log and
raw-storage section header (`#### 0x... (AaveV3Ethereum.POOL, ...)`), the
asset symbol inline wherever an event carries one (`asset: 0x... (symbol:
WETH)`), and the aToken/debt-token symbols in the "Reserves added/changed"
tables -- this module just collects what is already there.

Two maps come out:

- `label_map`: address -> a short role name for WHO an address is (an
  address-book role like POOL/EXECUTOR/PAYLOADS_CONTROLLER, or a friendly
  asset-role name derived from an `AaveV3X.ASSETS.<SYMBOL>.<ROLE>` label,
  e.g. "aWETH" for the A_TOKEN role).
- `symbol_map`: address -> the ERC20 symbol for WHAT token an address is
  (used to describe the token an amount is denominated in).

`describe_address` picks a name for an address from label_map first (a role
is more informative than a bare symbol for describing a party), falling
back to symbol_map, then to a short `0x1234…abcd` form.
"""
import re

# Event-log and raw-storage section headers: "#### 0xADDR (label1, label2)"
# or "### 0xaddr (label)" -- raw storage headers are lowercase, event-log
# ones keep checksum casing; both use the same shape, and a header with no
# label at all (no address-book entry for that address) has no parens.
_HEADER_RE = re.compile(r"^#{2,4}\s+(0x[0-9a-fA-F]{40})(?:\s*\(([^)]*)\))?", re.MULTILINE)
_INLINE_SYMBOL_RE = re.compile(r"(0x[0-9a-fA-F]{40})\s*\(symbol:\s*([^)]+)\)", re.IGNORECASE)
# "Reserves added"/"Reserves changed" blocks: "#### SYMBOL ([0xADDR](url))"
# followed immediately (no blank line inside a markdown table) by the
# reserve's description/value table.
_RESERVE_BLOCK_RE = re.compile(
    r"^####\s+(\S.*?)\s+\(\[(0x[0-9a-fA-F]{40})\]\([^)]*\)\)\s*\n\n((?:\|.*\n?)+)",
    re.MULTILINE,
)
_TABLE_ROW_RE = re.compile(
    r"^\|\s*([A-Za-z0-9_]+)\s*\|\s*(?:\[(0x[0-9a-fA-F]{40})\]\([^)]*\)|([^|]+?))\s*\|\s*$",
    re.MULTILINE,
)

_ASSET_LABEL_RE = re.compile(r"^[\w]+\.ASSETS\.([A-Za-z0-9_.]+)\.([A-Z_]+)$")
_EXECUTOR_LVL_RE = re.compile(r"EXECUTOR_LVL_\d+$")

_RESERVE_TOKEN_FIELDS = (
    ("aToken", "aTokenSymbol"),
    ("variableDebtToken", "variableDebtTokenSymbol"),
    ("stableDebtToken", "stableDebtTokenSymbol"),
)

_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_RESERVES_ADDED_SECTION_RE = re.compile(r"^### Reserves added\n(.*?)(?=^#{1,3}\s|\Z)", re.MULTILINE | re.DOTALL)
_RESERVE_SYMBOL_HEADER_RE = re.compile(r"^####\s+(\S.*?)\s+\(\[", re.MULTILINE)


def _friendly_asset_role(label: str):
    m = _ASSET_LABEL_RE.match(label)
    if not m:
        return None
    symbol, role = m.group(1), m.group(2)
    if role == "UNDERLYING":
        return symbol
    if role == "A_TOKEN":
        return f"a{symbol}"
    if role == "VARIABLE_DEBT_TOKEN":
        return f"vDebt{symbol}"
    if role == "STABLE_DEBT_TOKEN":
        return f"sDebt{symbol}"
    if role == "INTEREST_RATE_STRATEGY":
        return f"{symbol} rate strategy"
    return f"{symbol} {role.replace('_', ' ').lower()}"


def _pick_role_label(labels_csv: str):
    labels = [label.strip() for label in labels_csv.split(",") if label.strip()]
    if not labels:
        return None
    # Governance executor and payloads-controller addresses carry several
    # per-instance role labels (ACL_ADMIN, POOL_ADMIN, ...) alongside the
    # one that actually names what the address is doing in THIS execution --
    # prefer that one over an arbitrary "first label".
    for label in labels:
        if _EXECUTOR_LVL_RE.search(label):
            return "EXECUTOR"
    for label in labels:
        if label.rsplit(".", 1)[-1] == "PAYLOADS_CONTROLLER":
            return "PAYLOADS_CONTROLLER"
    friendly = _friendly_asset_role(labels[0])
    if friendly:
        return friendly
    return labels[0].rsplit(".", 1)[-1]


def build_maps(diff_report_text: str):
    """Returns (label_map, symbol_map), both keyed by lowercased address."""
    label_map = {}
    symbol_map = {}
    if not diff_report_text:
        return label_map, symbol_map

    for addr, labels_csv in _HEADER_RE.findall(diff_report_text):
        if not labels_csv:
            continue
        role = _pick_role_label(labels_csv)
        if role:
            label_map[addr.lower()] = role
        # A friendly asset-role name (from an `AaveV3X.ASSETS.<SYM>.<ROLE>`
        # label, e.g. "aWETH") IS the token's name -- also record it as a
        # symbol, so an amount denominated in this contract's own token can
        # be described even when no `(symbol: X)` was printed inline. A
        # generic infra role (POOL, EXECUTOR, ...) never goes into
        # symbol_map: it names WHO the address is, not what token it is.
        for label in (l.strip() for l in labels_csv.split(",")):
            friendly = _friendly_asset_role(label)
            if friendly:
                symbol_map.setdefault(addr.lower(), friendly)
                break

    for addr, symbol in _INLINE_SYMBOL_RE.findall(diff_report_text):
        symbol_map.setdefault(addr.lower(), symbol.strip())

    for reserve_symbol, reserve_addr, table_text in _RESERVE_BLOCK_RE.findall(diff_report_text):
        reserve_symbol = reserve_symbol.strip()
        reserve_addr = reserve_addr.lower()
        symbol_map.setdefault(reserve_addr, reserve_symbol)
        fields = {}
        for key, addr, plain in _TABLE_ROW_RE.findall(table_text):
            fields[key] = addr.lower() if addr else plain.strip()
        for token_key, symbol_key in _RESERVE_TOKEN_FIELDS:
            token_addr = fields.get(token_key)
            token_symbol = fields.get(symbol_key)
            if token_addr and token_symbol and _ADDR_RE.match(token_addr):
                symbol_map.setdefault(token_addr, token_symbol)

    return label_map, symbol_map


def new_reserve_symbols(diff_report_text: str):
    """The symbols of every reserve listed under a "### Reserves added"
    section -- used to tell a genuine new-listing seed apart from an
    ordinary supply into an already-existing reserve (e.g. a funding
    update's Collector deposit), which shares the exact same
    approve/supply/mint event shape."""
    symbols = set()
    if not diff_report_text:
        return symbols
    for section in _RESERVES_ADDED_SECTION_RE.findall(diff_report_text):
        symbols.update(m.strip() for m in _RESERVE_SYMBOL_HEADER_RE.findall(section))
    return symbols


def describe_address(addr, label_map, symbol_map):
    if not addr:
        return "unknown address"
    key = addr.lower()
    if key in label_map:
        return label_map[key]
    if key in symbol_map:
        return symbol_map[key]
    return f"{addr[:6]}…{addr[-4:]}"

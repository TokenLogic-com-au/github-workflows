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

The diff report only labels a contract that gets its own `####`/`###`
section (something it emitted an event on, or that changed storage) -- a
plain recipient with no state change of its own (a Safe, a DUST_BIN
constant, an approval spender) never gets one. `load_solidity_labels` reads
the actual aave-address-book `.sol` sources (checked out alongside the
proposal repo as a submodule) for a second source of `Library.CONSTANT`
names to fill exactly that gap.

`describe_address` picks a name in this order: diff-report label_map (most
specific to this execution) > diff-report symbol_map > the Solidity address
book, filtered to the payload's own chain (optional, degrades silently when
absent or ambiguous) > the full address, unshortened -- a party is never
dropped to a truncated `0x1234...abcd` form, so a reviewer can always
paste the whole address into an explorer.

Every label/symbol value here ultimately traces back to untrusted on-chain
or forum data (a token's own `symbol()`, a diff-report annotation) --
`sanitize_token` enforces a conservative charset and length cap on every
value before it enters either map, so a maliciously-named token can never
inject a markdown heading, link, or code-span break into the rendered
comment. Every value pulled from either map is additionally rendered inside
a backtick code span at display time (belt-and-braces: the value passed
sanitization, but showing it as code still stops any residual GFM
auto-linking, e.g. bare `www.` / `.com` text).
"""
import os
import re
import sys
from collections import Counter, defaultdict

# Conservative charset for any label/symbol value that ends up in the
# rendered comment: letters, digits, underscore, dot, hyphen, plus, space.
# No brackets/parens/backtick/newline -- nothing that can open a markdown
# link, heading, or code span, or break out of the backtick span this
# module wraps every displayed value in.
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.\-+ ]{1,64}$")


def sanitize_token(value):
    """Returns `value` unchanged if it is a safe label/symbol (conservative
    charset, no newline, length-capped), else None. Applied to every
    label/symbol before it enters label_map/symbol_map -- an unsafe value
    is dropped outright rather than truncated or escaped."""
    if not value:
        return None
    value = value.strip()
    if not value or not SAFE_TOKEN_RE.match(value):
        return None
    return value


# Event-log and raw-storage section headers: "#### 0xADDR (label1, label2)"
# or "### 0xaddr (label)" -- raw storage headers are lowercase, event-log
# ones keep checksum casing; both use the same shape, and a header with no
# label at all (no address-book entry for that address) has no parens. The
# label-list charset intentionally allows a comma (labels are
# comma-separated) but still excludes brackets/parens/backtick/newline, and
# each individual label is re-validated with sanitize_token after splitting.
_HEADER_RE = re.compile(
    r"^#{2,4}\s+(0x[0-9a-fA-F]{40})(?:\s*\(([A-Za-z0-9_.,\-+ ]{1,300})\))?", re.MULTILINE
)
# Shared with diff_parser.py (its own per-line lookup uses group(2) for the
# symbol; this module's build_maps uses both groups to learn which address
# the symbol belongs to) -- one canonical pattern, not two copies.
INLINE_SYMBOL_RE = re.compile(
    r"(0x[0-9a-fA-F]{40})\s*\(symbol:\s*([A-Za-z0-9_.\-+ ]{1,64})\)", re.IGNORECASE
)
# "Reserves added"/"Reserves changed" blocks: "#### SYMBOL ([0xADDR](url))"
# followed immediately (no blank line inside a markdown table) by the
# reserve's description/value table.
_RESERVE_BLOCK_RE = re.compile(
    r"^####\s+([A-Za-z0-9_.\-+ ]{1,64}?)\s+\(\[(0x[0-9a-fA-F]{40})\]\([^)\n]*\)\)\s*\n\n((?:\|.*\n?)+)",
    re.MULTILINE,
)
_TABLE_ROW_RE = re.compile(
    r"^\|\s*([A-Za-z0-9_]+)\s*\|\s*(?:\[(0x[0-9a-fA-F]{40})\]\([^)\n]*\)|([^|\n]+?))\s*\|\s*$",
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
# A V4 hub asset listed by the proposal: "### SYMBOL (assetId: N) on Hub [..](..)"
# followed by a "**NEW ASSET**" marker and the asset's table.
_V4_NEW_ASSET_RE = re.compile(
    r"^###\s+([A-Za-z0-9_.\-+ ]{1,64}?)\s+\(assetId:\s*\d+\)\s+on Hub\s+\[[^\]\n]*\]\([^)\n]*\)\s*\n\n"
    r"\*\*NEW ASSET\*\*\s*\n\n((?:\|.*\n?)+)",
    re.MULTILINE,
)


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
    labels = [
        safe
        for label in labels_csv.split(",")
        for safe in [sanitize_token(label)]
        if safe
    ]
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
        for raw_label in labels_csv.split(","):
            label = sanitize_token(raw_label)
            if not label:
                continue
            friendly = _friendly_asset_role(label)
            if friendly:
                symbol_map.setdefault(addr.lower(), friendly)
                break

    for addr, symbol in INLINE_SYMBOL_RE.findall(diff_report_text):
        safe = sanitize_token(symbol)
        if safe:
            symbol_map.setdefault(addr.lower(), safe)

    for reserve_symbol, reserve_addr, table_text in _RESERVE_BLOCK_RE.findall(diff_report_text):
        reserve_addr = reserve_addr.lower()
        safe_reserve_symbol = sanitize_token(reserve_symbol)
        if safe_reserve_symbol:
            symbol_map.setdefault(reserve_addr, safe_reserve_symbol)
        fields = {}
        for key, addr, plain in _TABLE_ROW_RE.findall(table_text):
            fields[key] = addr.lower() if addr else plain.strip()
        for token_key, symbol_key in _RESERVE_TOKEN_FIELDS:
            token_addr = fields.get(token_key)
            token_symbol = sanitize_token(fields.get(symbol_key))
            if token_addr and token_symbol and _ADDR_RE.match(token_addr):
                symbol_map.setdefault(token_addr, token_symbol)

    return label_map, symbol_map


# A fenced code block is quoted text, never report structure: a fabricated
# "Reserves added" block or `Library.POOL` label inside one must not count.
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# The V3 generator (fixSymbol) rewrites the non-ASCII USD stablecoin symbols
# to USDT before naming a constant; the sanitized charset rejects them.
_NON_ASCII_USDT_HEADING_RE = re.compile(r"^(####[^\n]*?)USD\u20ae0?", re.MULTILINE)


def _strip_fences(text: str) -> str:
    """Drops fenced code blocks per CommonMark: a fence closes only on a line
    of the same character, at least as long as the opener, with nothing but
    whitespace after it; an unclosed fence runs to the end of the document."""
    kept = []
    fence = None
    for line in (text or "").split("\n"):
        if fence is None:
            m = _FENCE_OPEN_RE.match(line)
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = m.group(1)
                continue
            kept.append(line)
        else:
            stripped = line.lstrip(" ")
            indent_ok = len(line) - len(stripped) <= 3
            if indent_ok and stripped.rstrip() and set(stripped.rstrip()) == {fence[0]} and len(stripped.rstrip()) >= len(fence):
                fence = None
    return "\n".join(kept)


def _table_fields(table_text: str):
    fields = {}
    for key, addr, plain in _TABLE_ROW_RE.findall(table_text):
        fields[key] = addr.lower() if addr else plain.strip()
    return fields


def _added_reserves(diff_report_text: str):
    """Yields (symbol, underlying, fields) for every reserve listed under a
    "### Reserves added" section, `fields` being the reserve table's
    key -> lowercased address / plain value."""
    text = _strip_fences(diff_report_text)
    text = _NON_ASCII_USDT_HEADING_RE.sub(r"\1USDT", text)
    for section in _RESERVES_ADDED_SECTION_RE.findall(text):
        for raw_symbol, underlying, table_text in _RESERVE_BLOCK_RE.findall(section):
            safe = sanitize_token(raw_symbol)
            if safe:
                yield safe, underlying.lower(), _table_fields(table_text)


def new_reserve_symbols(diff_report_text: str):
    """The symbols of every reserve listed under a "### Reserves added"
    section -- used to tell a genuine new-listing seed apart from an
    ordinary supply into an already-existing reserve (e.g. a funding
    update's Collector deposit), which shares the exact same
    approve/supply/mint event shape."""
    return {symbol for symbol, _underlying, _fields in _added_reserves(diff_report_text)}


# aave-address-book's generator (scripts/generator/utils.ts keyToVar) turns
# every `<SYMBOL>_<ROLE>` key into a Solidity identifier with these rules.
def _key_to_var(key: str) -> str:
    key = re.sub(r"^(\d)", r"_\1", key)
    key = key.replace("+", "Plus").replace(".", "")
    key = re.sub(r"[^\w ]", " ", key).strip()
    return re.sub(r" +", "_", key)


# V3 generator (assetsLibraryGenerator.ts fixSymbol): the symbol rewrites that
# apply to a brand-new reserve (the per-underlying overrides cover assets that
# were listed long ago).
def _v3_constant(symbol: str, role: str) -> str:
    if symbol == "fUSDT":
        symbol = "USDT"
    elif symbol == "1INCH":
        symbol = "ONE_INCH"
    else:
        symbol = symbol.replace("-", "_").replace(".", "", 1).replace(" ", "_", 1)
    return _key_to_var(f"{symbol}_{role}")


# V4 generator (fetchHubAssets.ts): only `-` -> `_`, then keyToVar.
def _v4_constant(symbol: str, role: str) -> str:
    return _key_to_var(f"{symbol.replace('-', '_')}_{role}")


_V3_POOL_LIBRARY_RE = re.compile(r"\b(AaveV3[A-Za-z0-9]*)\.POOL\b")
_V4_LIBRARY_RE = re.compile(r"\b(AaveV4[A-Za-z0-9]*)\.[A-Z]")


def _sole_library(pattern, diff_report_text: str):
    """The generated `<library>Assets` name, only when the diff report's own
    labels name exactly one such library -- never a guess."""
    names = set(pattern.findall(diff_report_text))
    return f"{names.pop()}Assets" if len(names) == 1 else None


def pending_listing_entries(diff_report_text: str):
    """{address_lower: (symbol, role, qualified_constant)} for every address
    aave-address-book's generator will add AFTER the listing in this diff
    report executes, so it cannot be in the book yet: a V3 reserve's
    underlying and oracle (`<SYM>_UNDERLYING` / `<SYM>_ORACLE` in
    `AaveV3<Chain>Assets`) and a V4 hub asset's underlying
    (`<SYM>_UNDERLYING` in `AaveV4<Chain>Assets`; the V4 generator emits no
    per-asset oracle). `qualified_constant` is the bare constant name when
    the library cannot be derived."""
    entries = {}
    diff_report_text = _strip_fences(diff_report_text)
    if not diff_report_text:
        return entries

    def add(addr, symbol, role, constant, library):
        if addr and _ADDR_RE.match(addr):
            qualified = f"{library}.{constant}" if library else constant
            entries.setdefault(addr.lower(), (symbol, role, qualified))

    v3_library = _sole_library(_V3_POOL_LIBRARY_RE, diff_report_text)
    for symbol, underlying, fields in _added_reserves(diff_report_text):
        add(underlying, symbol, "underlying", _v3_constant(symbol, "UNDERLYING"), v3_library)
        add(fields.get("oracle"), symbol, "oracle", _v3_constant(symbol, "ORACLE"), v3_library)

    v4_library = _sole_library(_V4_LIBRARY_RE, diff_report_text)
    for raw_symbol, table_text in _V4_NEW_ASSET_RE.findall(diff_report_text):
        safe = sanitize_token(raw_symbol)
        if safe:
            add(
                _table_fields(table_text).get("underlying"),
                safe,
                "underlying",
                _v4_constant(safe, "UNDERLYING"),
                v4_library,
            )
    return entries


def pending_listing_message(diff_report_text: str, addr: str):
    """The reviewer-facing note for a raw address that this proposal's own
    listing will add to the address book, or None when it is not one."""
    entry = pending_listing_entries(diff_report_text).get(addr.lower())
    if not entry:
        return None
    symbol, role, qualified = entry
    short = f"{addr[:6]}\u2026{addr[-4:]}"
    return (
        f"{short}: {symbol} {role}, not in the address book yet; "
        f"expected as {qualified} after the listing executes"
    )


_LIBRARY_RE = re.compile(r"\blibrary\s+(\w+)\s*\{")
# A constant declaration: an optional interface-typed wrapper call around
# the address, e.g. `IPool internal constant POOL = IPool(0x...);` or the
# bare `address internal constant DUST_BIN = 0x...;` -- and either shape can
# wrap onto a second line between `=` and the address (aave-address-book's
# generator does this whenever the declaration is long), so this matches
# across newlines. The book's own source is trusted (compiled Solidity, not
# on-chain data), so this pattern is not charset-restricted the way the
# diff-report regexes above are.
_SOL_CONST_RE = re.compile(
    r"\b(?:address|[A-Z]\w*)\s+internal\s+constant\s+(\w+)\s*=\s*"
    r"(?:[A-Z]\w*\(\s*)?(0x[0-9a-fA-F]{40})\s*\)?\s*;",
    re.DOTALL,
)
# A library name is `<family><Chain>[<suffix>]`, e.g. "AaveV3EthereumAssets"
# -> family "AaveV3", chain "Ethereum", suffix "Assets"; "MiscMonad" ->
# family "Misc", chain "Monad", no suffix. The suffix list matches every
# non-chain-name tail aave-address-book appends to a per-chain library.
_LIBRARY_FAMILY_RE = re.compile(r"^(AaveV[234]|GovernanceV3|Umbrella|Gho|Misc)([A-Z][A-Za-z0-9]*)$")
_LIBRARY_SUFFIXES = ("Assets", "EModes", "ExternalLibraries")
# A per-protocol-instance chain name (e.g. "EthereumLido") shares its
# Misc/GovernanceV3/Umbrella/Gho libraries with its base chain
# ("Ethereum") -- those libraries are published once per base chain, not
# once per instance.
_INSTANCE_SUFFIXES = ("Lido", "EtherFi", "Horizon")
_CHAIN_ONLY_FAMILIES = ("Misc", "GovernanceV3", "Umbrella", "Gho")
# Used only by infer_chain: the same family prefixes, matched against the
# diff report's own label text rather than a library name.
_CHAIN_SUFFIX_RE = re.compile(r"\b(?:AaveV[234]|GovernanceV3|Umbrella|Gho|Misc)([A-Z][A-Za-z0-9]*)\b")


def _library_chain(library_name: str):
    """Splits a library name into (family, chain), e.g. "AaveV3EthereumLido"
    -> ("AaveV3", "EthereumLido"), "MiscEthereum" -> ("Misc", "Ethereum").
    Returns (None, None) if the name doesn't match a known family prefix."""
    m = _LIBRARY_FAMILY_RE.match(library_name)
    if not m:
        return None, None
    family, rest = m.group(1), m.group(2)
    for suffix in _LIBRARY_SUFFIXES:
        if rest.endswith(suffix) and len(rest) > len(suffix):
            return family, rest[: -len(suffix)]
    return family, rest


def _base_chain(chain: str):
    for suffix in _INSTANCE_SUFFIXES:
        if chain.endswith(suffix) and len(chain) > len(suffix):
            return chain[: -len(suffix)]
    return None


def _library_matches_chain(library_name: str, chain: str) -> bool:
    family, lib_chain = _library_chain(library_name)
    if lib_chain is None:
        return False
    if lib_chain == chain:
        return True
    # A Lido/EtherFi/Horizon instance payload can still use its base
    # chain's Misc/GovernanceV3/Umbrella/Gho constant (e.g. AHAB_SAFE on an
    # EthereumLido payload is MiscEthereum.AHAB_SAFE, since MiscEthereumLido
    # does not exist) -- but never the other way around, and never for
    # AaveVx itself (an AaveV3Ethereum constant is never substituted for an
    # AaveV3EthereumLido one).
    if family in _CHAIN_ONLY_FAMILIES:
        base = _base_chain(chain)
        if base and lib_chain == base:
            return True
    return False


def _parse_solidity_libraries(text: str):
    """Yields (library_name, constant_name, address) for every top-level
    `library NAME { ... }` block in one .sol file's source text."""
    for m in _LIBRARY_RE.finditer(text):
        library_name = m.group(1)
        start = m.end()
        depth = 1
        i = start
        length = len(text)
        while i < length and depth > 0:
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        body = text[start:i]
        for const_m in _SOL_CONST_RE.finditer(body):
            yield library_name, const_m.group(1), const_m.group(2)


def load_solidity_labels(address_book_root: str):
    """Returns {address_lower: [(library, constant_name), ...]} parsed from
    every `.sol` file under `<address_book_root>/src` (the aave-address-book
    checkout's own source tree -- never its `lib/`, `tests/`, `ui/`, or
    `scripts/` subtrees, which can hold unrelated or vendored `.sol` files
    with their own `library` blocks). Returns {} for a missing/empty root,
    a root with no `src/`, an unreadable file, or a file that fails to
    parse -- this never raises, so a bad or absent book only ever loses the
    second naming source, it never breaks the renderer."""
    labels = defaultdict(list)
    if not address_book_root:
        return labels
    src_root = os.path.join(address_book_root, "src")
    if not os.path.isdir(src_root):
        return labels
    for dirpath, _dirnames, filenames in os.walk(src_root):
        for filename in filenames:
            if not filename.endswith(".sol"):
                continue
            path = os.path.join(dirpath, filename)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except Exception:
                continue
            try:
                for library_name, const_name, addr in _parse_solidity_libraries(text):
                    labels[addr.lower()].append((library_name, const_name))
            except Exception:
                continue
    return labels


def infer_chain(diff_report_text: str):
    """The most common `AaveVx<Chain>`/`GovernanceV3<Chain>`/... namespace
    suffix appearing in the diff report's own labels -- a best-effort guess
    at which chain this payload runs on, used only to pick a same-chain
    address-book entry when one address has several."""
    if not diff_report_text:
        return None
    counts = Counter(_CHAIN_SUFFIX_RE.findall(diff_report_text))
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _describe_from_solidity_book(addr, solidity_labels, chain):
    entries = solidity_labels.get(addr.lower()) if solidity_labels else None
    if not entries:
        return None
    if chain:
        matching = [e for e in entries if _library_matches_chain(e[0], chain)]
        if not matching:
            # The chain is known but nothing in the book matches it --
            # never substitute a different chain's label for it.
            return None
        entries = matching
    elif len(entries) > 1:
        # Chain unknown and the address is ambiguous across several book
        # entries -- guessing one could pick the wrong chain, so decline.
        return None
    library_name, const_name = sorted(entries)[0]
    return f"{library_name}.{const_name}"


DUST_BIN_CONSTANT = "DUST_BIN"


def is_dust_bin(addr, solidity_labels, chain):
    """True when the address book names `addr` the DUST_BIN of `chain`'s
    instance. False for anything else, including an absent book."""
    label = _describe_from_solidity_book(addr, solidity_labels, chain) if addr else None
    return bool(label) and label.endswith(f".{DUST_BIN_CONSTANT}")


def describe_address(addr, label_map, symbol_map, solidity_labels=None, chain=None):
    """Renders a party as `` `Label` (0xFullAddress) `` when any naming
    source knows it, or the full, unshortened checksummed address
    otherwise -- an address is never dropped in favour of a label, and
    never truncated to a short `0x1234...abcd` form."""
    if not addr:
        return "unknown address"
    key = addr.lower()
    label = (
        label_map.get(key)
        or symbol_map.get(key)
        or _describe_from_solidity_book(addr, solidity_labels, chain)
    )
    if label:
        return f"`{label}` ({addr})"
    return addr


def main(argv):
    """`address_book.py pending-listing REPORT ADDRESS`: prints the
    pending-listing note for ADDRESS, or nothing when REPORT is unreadable
    or does not list it. Always exits 0 -- a lookup miss is not an error."""
    if len(argv) != 4 or argv[1] != "pending-listing":
        sys.stderr.write("usage: address_book.py pending-listing REPORT ADDRESS\n")
        return 2
    try:
        with open(argv[2], encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return 0
    message = pending_listing_message(text, argv[3])
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

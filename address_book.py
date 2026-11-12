"""Address -> plain-language name lookups built from a diff report's own text.

label_map names WHO an address is, symbol_map WHAT token it is; load_solidity_labels adds the
aave-address-book .sol sources for parties the report never labels. describe_address picks
report label > report symbol > same-chain book entry > the full address, never truncated.
Every value comes from untrusted data: sanitize_token enforces a safe charset before it enters
a map, and values render in code spans.
"""
import os
import re
import sys
from collections import Counter, defaultdict

# No brackets/parens/backtick/newline: nothing that can open a link, heading or code span.
SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.\-+ ]{1,64}$")


def sanitize_token(value):
    """`value` if it is a safe label/symbol, else None (dropped, never escaped)."""
    if not value:
        return None
    value = value.strip()
    if not value or not SAFE_TOKEN_RE.match(value):
        return None
    return value


# Section headers "#### 0xADDR (label1, label2)"; the label list allows commas, each label is re-validated.
_HEADER_RE = re.compile(
    r"^#{2,4}\s+(0x[0-9a-fA-F]{40})(?:\s*\(([A-Za-z0-9_.,\-+ ]{1,300})\))?", re.MULTILINE
)
# Shared with diff_parser.
INLINE_SYMBOL_RE = re.compile(
    r"(0x[0-9a-fA-F]{40})\s*\(symbol:\s*([A-Za-z0-9_.\-+ ]{1,64})\)", re.IGNORECASE
)
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

A_TOKEN_FIELD = "aToken"
_RESERVE_TOKEN_FIELDS = (
    (A_TOKEN_FIELD, "aTokenSymbol"),
    ("variableDebtToken", "variableDebtTokenSymbol"),
    ("stableDebtToken", "stableDebtTokenSymbol"),
)

_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_RESERVES_ADDED_SECTION_RE = re.compile(r"^### Reserves added\n(.*?)(?=^#{1,3}\s|\Z)", re.MULTILINE | re.DOTALL)
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
    # executor/payloads-controller addresses carry several role labels; prefer the one naming this execution
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
        # asset-role names (aWETH) are token names too; infra roles (POOL, EXECUTOR) are not
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


# Fenced blocks are quoted text: forged "Reserves added" blocks or labels inside must not count.
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# The V3 generator rewrites non-ASCII USD stablecoin symbols to USDT; sanitize_token rejects them.
_NON_ASCII_USDT_HEADING_RE = re.compile(r"^(####[^\n]*?)USD\u20ae0?", re.MULTILINE)


def _strip_fences(text: str) -> str:
    """Drops CommonMark fenced code blocks; an unclosed fence runs to the end."""
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
    """Yields (symbol, underlying, table fields) per reserve under "### Reserves added"."""
    text = _strip_fences(diff_report_text)
    text = _NON_ASCII_USDT_HEADING_RE.sub(r"\1USDT", text)
    for section in _RESERVES_ADDED_SECTION_RE.findall(text):
        for raw_symbol, underlying, table_text in _RESERVE_BLOCK_RE.findall(section):
            safe = sanitize_token(raw_symbol)
            if safe:
                yield safe, underlying.lower(), _table_fields(table_text)


def new_reserves(diff_report_text: str):
    """{underlying_lower: {"symbol", "a_token"}} for reserves added with an aToken row; tells listing seeds from ordinary supplies."""
    return {
        underlying: {"symbol": symbol, "a_token": fields[A_TOKEN_FIELD]}
        for symbol, underlying, fields in _added_reserves(diff_report_text)
        if _ADDR_RE.match(fields.get(A_TOKEN_FIELD, ""))
    }


# Mirrors aave-address-book generator keyToVar.
def _key_to_var(key: str) -> str:
    key = re.sub(r"^(\d)", r"_\1", key)
    key = key.replace("+", "Plus").replace(".", "")
    key = re.sub(r"[^\w ]", " ", key).strip()
    return re.sub(r" +", "_", key)


# Mirrors the V3 generator fixSymbol for a brand-new reserve.
def _v3_constant(symbol: str, role: str) -> str:
    if symbol == "fUSDT":
        symbol = "USDT"
    elif symbol == "1INCH":
        symbol = "ONE_INCH"
    else:
        symbol = symbol.replace("-", "_").replace(".", "", 1).replace(" ", "_", 1)
    return _key_to_var(f"{symbol}_{role}")


# Mirrors the V4 generator: `-` to `_`, then keyToVar.
def _v4_constant(symbol: str, role: str) -> str:
    return _key_to_var(f"{symbol.replace('-', '_')}_{role}")


_V3_POOL_LIBRARY_RE = re.compile(r"\b(AaveV3[A-Za-z0-9]*)\.POOL\b")
_V4_LIBRARY_RE = re.compile(r"\b(AaveV4[A-Za-z0-9]*)\.[A-Z]")


def _sole_library(pattern, diff_report_text: str):
    """The `<library>Assets` name when the labels name exactly one library, else None."""
    names = set(pattern.findall(diff_report_text))
    return f"{names.pop()}Assets" if len(names) == 1 else None


def pending_listing_entries(diff_report_text: str):
    """{address_lower: (symbol, role, qualified_constant)} for addresses the generator adds after this listing executes.

    V3: `<SYM>_UNDERLYING` and `<SYM>_ORACLE`; V4: `<SYM>_UNDERLYING` only. The constant is bare when the library is unknown.
    """
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
    """Reviewer note for an address this listing will add to the book, else None."""
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
# Matches `IPool internal constant POOL = IPool(0x...);` and bare `address ...`, wrapped or not; the book source is trusted.
_SOL_CONST_RE = re.compile(
    r"\b(?:address|[A-Z]\w*)\s+internal\s+constant\s+(\w+)\s*=\s*"
    r"(?:[A-Z]\w*\(\s*)?(0x[0-9a-fA-F]{40})\s*\)?\s*;",
    re.DOTALL,
)
# Library names are `<family><Chain>[<suffix>]`, e.g. AaveV3EthereumAssets.
_LIBRARY_FAMILY_RE = re.compile(r"^(AaveV[234]|GovernanceV3|Umbrella|Gho|Misc)([A-Z][A-Za-z0-9]*)$")
_LIBRARY_SUFFIXES = ("Assets", "EModes", "ExternalLibraries")
# Instance chains (EthereumLido) share Misc/GovernanceV3/Umbrella/Gho libraries with their base chain.
_INSTANCE_SUFFIXES = ("Lido", "EtherFi", "Horizon")
_CHAIN_ONLY_FAMILIES = ("Misc", "GovernanceV3", "Umbrella", "Gho")
# Used by infer_chain on label text.
_CHAIN_SUFFIX_RE = re.compile(r"\b(?:AaveV[234]|GovernanceV3|Umbrella|Gho|Misc)([A-Z][A-Za-z0-9]*)\b")


def _library_chain(library_name: str):
    """(family, chain) of a library name, e.g. "AaveV3EthereumLido" -> ("AaveV3", "EthereumLido"); (None, None) if unknown."""
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
    # An instance payload may use its base chain's chain-only libraries (MiscEthereum.AHAB_SAFE), never AaveVx.
    if family in _CHAIN_ONLY_FAMILIES:
        base = _base_chain(chain)
        if base and lib_chain == base:
            return True
    return False


def _parse_solidity_libraries(text: str):
    """Yields (library, constant, address) for each `library NAME { ... }` block."""
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
    """{address_lower: [(library, constant)]} from `<root>/src/**/*.sol` only (lib/tests/ui/scripts hold unrelated libraries); never raises."""
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
    """Most common chain suffix in the report's labels; best-effort, only picks among same-address book entries."""
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
            return None
        entries = matching
    elif len(entries) > 1:
        return None
    library_name, const_name = sorted(entries)[0]
    return f"{library_name}.{const_name}"


DUST_BIN_CONSTANT = "DUST_BIN"
POOL_CONSTANT = "POOL"


def names_book_constant(addr, solidity_labels, chain, constant):
    """True when the book names `addr` the `constant` of `chain`'s instance."""
    label = _describe_from_solidity_book(addr, solidity_labels, chain) if addr else None
    return bool(label) and label.endswith(f".{constant}")


def describe_address(addr, label_map, symbol_map, solidity_labels=None, chain=None):
    """`` `Label` (0xFull) `` when any source names it, else the full address."""
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


def book_constant(addr, solidity_labels, path_hint):
    """`Library.CONSTANT` naming `addr`, preferring the library whose longest CamelCase suffix (the chain) the path names; sorted-first otherwise."""
    entries = sorted(solidity_labels.get(addr.lower(), ()))
    if not entries:
        return None
    hint = path_hint.lower().replace("_", "")

    def score(entry):
        name = entry[0]
        return max((len(name) - i for i in range(1, len(name)) if name[i].isupper() and name[i:].lower() in hint), default=0)

    library_name, const_name = max(entries, key=score)
    return f"{library_name}.{const_name}"


def main(argv):
    """`pending-listing REPORT ADDRESS` / `book-constant BOOK_ROOT ADDRESS PATH`: print the note or name, or nothing; a miss exits 0."""
    if len(argv) == 5 and argv[1] == "book-constant":
        name = book_constant(argv[3], load_solidity_labels(argv[2]), argv[4])
        if name:
            print(name)
        return 0
    if len(argv) != 4 or argv[1] != "pending-listing":
        sys.stderr.write("usage: address_book.py pending-listing REPORT ADDRESS | book-constant BOOK_ROOT ADDRESS PATH\n")
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

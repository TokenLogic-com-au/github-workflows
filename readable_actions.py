"""Turns diff_parser payload items into plain-language findings -- what the
payload action IS, in address-book names, token and amount -- instead of
raw `amount X, recipient 0x...` lines. Recognizes the common protocol
patterns (a new-listing seed: approve -> supply on behalf of X -> aToken
mint; an approval reset to 0) and groups a seed's events into one summary
line, keeping the underlying events listed beneath it. Any event that
matches none of these still gets a readable line built from its event
name, token/contract label, and amount -- never a silent drop, except a
`ReserveDataUpdated` accounting line, which build_readable_findings omits
by design (the caller reports its count separately, see
diff_parser.count_reserve_data_updates).
"""
from address_book import describe_address

LISTING_SEED_KIND = "Listing seed"
SUPPLY_FLOW_KIND = "Supply flow"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _is_zero_address(addr):
    return bool(addr) and addr.lower() == ZERO_ADDRESS


def _token_symbol(item, symbol_map):
    if item.get("inline_symbol"):
        return item["inline_symbol"]
    section = item.get("section")
    if section:
        return symbol_map.get(section)
    return None


def _amount_text(item, symbol_map):
    amount = item.get("amount")
    symbol = _token_symbol(item, symbol_map)
    if item.get("decimals") == 0:
        # decimals: 0 on a token that is not genuinely a 0-decimal asset
        # means the diff report's decoder could not resolve the real
        # decimals (typical for a brand-new aToken in a listing) -- the
        # displayed number really is the raw, unscaled integer.
        suffix = f" `{symbol}`" if symbol else ""
        return f"{amount}{suffix} (raw, decimals unknown)"
    if symbol:
        return f"{amount} `{symbol}`"
    # decimals are known and diff_parser's own "human" group is already the
    # correctly-scaled amount -- there is nothing raw about it, it just has
    # no token name to show.
    return amount


def describe_action(item, label_map, symbol_map, solidity_labels=None, chain=None) -> str:
    """The generic-fallback-inclusive readable line for one payload item:
    event name, labelled address fields, and amount -- used directly for
    anything outside the recognized patterns, and to build each seed
    group's sub-lines. `solidity_labels`/`chain` (from
    address_book.load_solidity_labels/infer_chain) are an optional second
    naming source for a party the diff report itself never labelled (no
    `####`/`###` section of its own) -- omitting them just falls back to
    the full address, exactly like before this source existed."""
    event_name = item.get("event_name") or item.get("action")
    recipient = item.get("recipient")
    counterparty = item.get("counterparty")
    amount_text = _amount_text(item, symbol_map)

    def _addr(a):
        return describe_address(a, label_map, symbol_map, solidity_labels, chain)

    if event_name == "Approval":
        owner_label = _addr(counterparty)
        spender_label = _addr(recipient)
        if item.get("amount") == "0":
            return f"Approval: {owner_label} resets {spender_label}'s allowance to 0"
        return f"Approval: {owner_label} approves {spender_label} to spend {amount_text}"

    if event_name == "Transfer":
        to_label = _addr(recipient)
        if _is_zero_address(counterparty):
            return f"Mint: {amount_text} to {to_label}"
        from_label = _addr(counterparty)
        return f"Transfer: {amount_text} from {from_label} to {to_label}"

    if event_name == "Supply":
        beneficiary = _addr(item.get("on_behalf_of"))
        return f"Supply: {amount_text} supplied on behalf of {beneficiary}"

    recipient_label = _addr(recipient)
    return f"{event_name or 'Event'}: {amount_text}, contract {recipient_label}"


def find_seed_groups(
    items, label_map, symbol_map, new_reserves=None, solidity_labels=None, chain=None
):
    """A seed flow is: a Supply, on behalf of some beneficiary, paid for by
    a payer (the Supply's own `user` field) -- matched to:

    - an Approval emitted on the reserve's own token section, whose
      spender is the Supply's own pool (the Supply's `section`), whose
      owner is the Supply's payer, and whose amount equals the supplied
      amount;
    - a Transfer, also on the reserve's own token section, from that same
      payer to the reserve's aToken, for the same amount;
    - the aToken's own from-zero Transfer (the mint) to the Supply's
      beneficiary.

    Every field is checked explicitly so an unrelated Approval sitting in
    the same token section (a different spender, a different owner, or a
    different amount) is never swept into the group -- it stays its own
    finding.

    diff_parser's fallback address extraction happens to put the reserve's
    own address in a Supply item's `recipient` field (the first 0x address
    on a `Supply(reserve: 0x..., onBehalfOf: ..., ..., user: 0x..., ...)`
    line, since it has no `to:` label) -- that quirk is exactly the key
    used to find the Approval/Transfer on the same reserve.

    The exact same event shape also happens on an ALREADY-listed reserve
    (e.g. a funding update reinvesting swapped fees) -- only a reserve
    named under this report's own "### Reserves added" section is a real
    new-listing seed; anything else is worded as an ordinary supply flow.
    """
    groups = []
    used_ids = set()
    for supply in items:
        if supply.get("event_name") != "Supply":
            continue
        reserve_addr = (supply.get("recipient") or "").lower()
        pool_addr = (supply.get("section") or "").lower()
        beneficiary = supply.get("on_behalf_of")
        payer = supply.get("user")
        supply_amount = supply.get("amount")
        if not reserve_addr or not pool_addr or not beneficiary or not payer:
            continue
        payer_lower = payer.lower()
        listing = (new_reserves or {}).get(reserve_addr)

        approval = next(
            (
                it
                for it in items
                if id(it) not in used_ids
                and it.get("event_name") == "Approval"
                and (it.get("section") or "").lower() == reserve_addr
                and (it.get("recipient") or "").lower() == pool_addr
                and it.get("counterparty")
                and it["counterparty"].lower() == payer_lower
                and it.get("amount") == supply_amount
            ),
            None,
        )
        underlying_transfer = next(
            (
                it
                for it in items
                if id(it) not in used_ids
                and it.get("event_name") == "Transfer"
                and (it.get("section") or "").lower() == reserve_addr
                and it.get("counterparty")
                and it["counterparty"].lower() == payer_lower
                and it.get("amount") == supply_amount
                and (not listing or (it.get("recipient") or "").lower() == listing["a_token"])
            ),
            None,
        )
        if not underlying_transfer:
            continue
        atoken_addr = (underlying_transfer.get("recipient") or "").lower()
        mint = next(
            (
                it
                for it in items
                if id(it) not in used_ids
                and it.get("event_name") == "Transfer"
                and (it.get("section") or "").lower() == atoken_addr
                and _is_zero_address(it.get("counterparty"))
                and it.get("recipient") == beneficiary
                and (not listing or it.get("raw_amount") == supply.get("raw_amount"))
            ),
            None,
        )
        if not mint:
            continue

        members = [m for m in (approval, supply, underlying_transfer, mint) if m is not None]
        for member in members:
            used_ids.add(id(member))

        reserve_symbol = (
            listing["symbol"]
            if listing
            else _token_symbol(supply, symbol_map)
            or describe_address(reserve_addr, label_map, symbol_map, solidity_labels, chain)
        )
        payer_label = describe_address(payer, label_map, symbol_map, solidity_labels, chain)
        beneficiary_label = describe_address(beneficiary, label_map, symbol_map, solidity_labels, chain)
        kind = LISTING_SEED_KIND if listing else SUPPLY_FLOW_KIND
        summary = (
            f"{kind} for {reserve_symbol}: {payer_label} supplies "
            f"{_amount_text(supply, symbol_map)} on behalf of {beneficiary_label}, "
            f"minting {_amount_text(mint, symbol_map)}"
        )
        groups.append(
            {
                "line": summary,
                "sub_lines": [
                    describe_action(m, label_map, symbol_map, solidity_labels, chain) for m in members
                ],
                "members": members,
                "kind": kind,
                "asset_symbol": reserve_symbol,
                "beneficiary": beneficiary,
                "pool": pool_addr,
                "reserve": reserve_addr,
            }
        )
    return groups


def build_readable_findings(
    items, label_map, symbol_map, new_reserves=None, solidity_labels=None, chain=None
):
    """Returns [{"line": str, "sub_lines": [str, ...]}] covering every item
    in `items` except a `ReserveDataUpdated` accounting line (protocol
    bookkeeping -- a rate/liquidity index -- never a payment; the caller
    reports how many were omitted separately, counted from the raw diff
    report rather than this deduped `items` list, since the same index can
    legitimately update more than once in one execution). A seed flow (a
    new listing, or an ordinary supply into an existing reserve) collapses
    into one summary line with its underlying events as sub_lines;
    everything else (including any event outside the recognized patterns)
    gets its own single-line description."""
    seed_groups = find_seed_groups(
        items, label_map, symbol_map, new_reserves, solidity_labels, chain
    )
    grouped_ids = {id(member) for group in seed_groups for member in group["members"]}
    findings = [
        {key: g[key] for key in ("line", "sub_lines")}
        for g in seed_groups
    ]
    for item in items:
        if id(item) in grouped_ids:
            continue
        if item.get("event_name") == "ReserveDataUpdated":
            continue
        findings.append(
            {
                "line": describe_action(item, label_map, symbol_map, solidity_labels, chain),
                "sub_lines": [],
            }
        )
    return findings

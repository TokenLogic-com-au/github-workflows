"""Turns diff_parser payload items into plain-language findings -- what the
payload action IS, in address-book names, token and amount -- instead of
raw `amount X, recipient 0x...` lines. Recognizes the common protocol
patterns (a new-listing seed: approve -> supply on behalf of X -> aToken
mint; an approval reset to 0; a generic Pool/Configurator config event) and
groups a seed's events into one summary line, keeping the underlying events
listed beneath it. Any event that matches none of these still gets a
readable line built from its event name, token/contract label, and amount --
never a silent drop.
"""
from address_book import describe_address

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
        # displayed number is the raw integer, not a scaled human amount.
        suffix = f" {symbol}" if symbol else ""
        return f"{amount}{suffix} (raw, decimals unknown)"
    if symbol:
        return f"{amount} {symbol}"
    return f"{amount} (raw)"


def describe_action(item, label_map, symbol_map, solidity_labels=None, chain=None) -> str:
    """The generic-fallback-inclusive readable line for one payload item:
    event name, labelled address fields, and amount -- used directly for
    anything outside the recognized patterns, and to build each seed
    group's sub-lines. `solidity_labels`/`chain` (from
    address_book.load_solidity_labels/infer_chain) are an optional second
    naming source for a party the diff report itself never labelled (no
    `####`/`###` section of its own) -- omitting them just falls back to a
    short address, exactly like before this source existed."""
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

    if event_name and event_name.endswith("CapChanged"):
        cap_kind = event_name[: -len("CapChanged")]
        symbol = _token_symbol(item, symbol_map) or _addr(recipient)
        return f"{cap_kind} cap on {symbol} set to {item.get('amount')}"

    if event_name == "ReserveDataUpdated":
        symbol = _token_symbol(item, symbol_map) or _addr(recipient)
        return f"{symbol} rate/index update (not a payment): {amount_text}"

    recipient_label = _addr(recipient)
    return f"{event_name or 'Event'}: {amount_text}, contract {recipient_label}"


def _find_listing_seed_groups(
    items, label_map, symbol_map, new_reserve_symbols=frozenset(), solidity_labels=None, chain=None
):
    """A seed flow is: a nonzero Approval on the reserve's own token
    section -> a Supply on behalf of some beneficiary -> the payer's
    Transfer of the underlying token to the aToken -> the aToken's
    from-zero Transfer (mint) to that same beneficiary. diff_parser's
    fallback address extraction happens to put the reserve's own address in
    a Supply item's `recipient` field (the first 0x address on a `Supply(
    reserve: 0x..., onBehalfOf: ..., ...)` line, since it has no `to:`
    label) -- that quirk is exactly the key this needs to link an Approval
    (emitted on the reserve's own `####` section) and a Supply to the same
    reserve.

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
        beneficiary = supply.get("on_behalf_of")
        if not reserve_addr or not beneficiary:
            continue

        approval = next(
            (
                it
                for it in items
                if id(it) not in used_ids
                and it.get("event_name") == "Approval"
                and (it.get("section") or "") == reserve_addr
                and it.get("amount") not in (None, "0")
            ),
            None,
        )
        underlying_transfer = next(
            (
                it
                for it in items
                if id(it) not in used_ids
                and it.get("event_name") == "Transfer"
                and (it.get("section") or "") == reserve_addr
                and it.get("counterparty")
                and not _is_zero_address(it["counterparty"])
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
                and (it.get("section") or "") == atoken_addr
                and _is_zero_address(it.get("counterparty"))
                and it.get("recipient") == beneficiary
            ),
            None,
        )
        if not mint:
            continue

        members = [m for m in (approval, supply, underlying_transfer, mint) if m is not None]
        for member in members:
            used_ids.add(id(member))

        reserve_symbol = _token_symbol(supply, symbol_map) or describe_address(
            reserve_addr, label_map, symbol_map, solidity_labels, chain
        )
        payer_label = describe_address(
            underlying_transfer.get("counterparty"), label_map, symbol_map, solidity_labels, chain
        )
        beneficiary_label = describe_address(beneficiary, label_map, symbol_map, solidity_labels, chain)
        kind = "Listing seed" if reserve_symbol in new_reserve_symbols else "Supply flow"
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
            }
        )
    return groups


def build_readable_findings(
    items, label_map, symbol_map, new_reserve_symbols=frozenset(), solidity_labels=None, chain=None
):
    """Returns (findings, omitted_index_updates):

    - findings: [{"line": str, "sub_lines": [str, ...]}] covering every
      item in `items` except a `ReserveDataUpdated` accounting line, exactly
      once. A seed flow (a new listing, or an ordinary supply into an
      existing reserve) collapses into one summary line with its underlying
      events as sub_lines; everything else (including any event outside the
      recognized patterns) gets its own single-line description.
    - omitted_index_updates: how many `ReserveDataUpdated` items were left
      out -- these are the protocol accounting a rate/liquidity index, never
      a payment, so they are reported as one summary count rather than as
      findings (nothing else is ever omitted this way).
    """
    seed_groups = _find_listing_seed_groups(
        items, label_map, symbol_map, new_reserve_symbols, solidity_labels, chain
    )
    grouped_ids = {id(member) for group in seed_groups for member in group["members"]}
    findings = [{"line": g["line"], "sub_lines": g["sub_lines"]} for g in seed_groups]
    omitted_index_updates = 0
    for item in items:
        if id(item) in grouped_ids:
            continue
        if item.get("event_name") == "ReserveDataUpdated":
            omitted_index_updates += 1
            continue
        findings.append(
            {
                "line": describe_action(item, label_map, symbol_map, solidity_labels, chain),
                "sub_lines": [],
            }
        )
    return findings, omitted_index_updates

"""Turns diff_parser payload items into plain-language findings; ReserveDataUpdated lines are omitted (counted separately)."""
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
        # decimals 0 on a token that is not really 0-decimal means the diff decoder could not resolve them (new aToken): the number is raw
        suffix = f" `{symbol}`" if symbol else ""
        return f"{amount}{suffix} (raw, decimals unknown)"
    if symbol:
        return f"{amount} `{symbol}`"
    return amount


def describe_action(item, label_map, symbol_map, solidity_labels=None) -> str:
    """Readable line for one payload item; `solidity_labels` on the item's own chain name parties the diff report never labelled."""
    event_name = item.get("event_name") or item.get("action")
    recipient = item.get("recipient")
    counterparty = item.get("counterparty")
    amount_text = _amount_text(item, symbol_map)

    def _addr(a):
        return describe_address(a, label_map, symbol_map, solidity_labels, item.get("chain"))

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


def find_seed_groups(items, label_map, symbol_map, new_reserves=None, solidity_labels=None):
    """Groups a Supply with the Approval, Transfer and aToken mint that fund it (same payer, pool, reserve, amount).

    A Supply's `recipient` is the reserve address (first address on the line, no `to:`), the key used to find
    its Approval/Transfer. Only a reserve under "### Reserves added" is a listing seed; others are supply flows.
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
        chain = supply.get("chain")
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
                    describe_action(m, label_map, symbol_map, solidity_labels) for m in members
                ],
                "members": members,
                "kind": kind,
                "asset_symbol": reserve_symbol,
                "beneficiary": beneficiary,
                "pool": pool_addr,
                "reserve": reserve_addr,
                "chain": chain,
            }
        )
    return groups


def build_readable_findings(items, label_map, symbol_map, new_reserves=None, solidity_labels=None):
    """Returns [{"line", "sub_lines"}] per item, skipping ReserveDataUpdated; seed flows collapse into one line, a folded flow lists its members."""
    seed_groups = find_seed_groups(items, label_map, symbol_map, new_reserves, solidity_labels)
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
                "line": describe_action(item, label_map, symbol_map, solidity_labels),
                "sub_lines": flow_sub_lines(item, label_map, symbol_map, solidity_labels),
            }
        )
    return findings


def flow_sub_lines(unit, label_map, symbol_map, solidity_labels=None):
    return [describe_action(m, label_map, symbol_map, solidity_labels) for m in unit.get("members", ())]


def fold_flows(items, symbol_map, exclude_ids=()):
    """Folds token hops and the approvals they spend into one movement unit per flow, each unit with its `asset` symbol.

    A hop continues a flow when it moves the same raw amount of the same token in the same payload out of the address
    the previous hop paid; an approval joins when its owner sends that amount in a later hop and the flow pays its
    spender (a spender the flow never pays stays its own item, so an unproven allowance is still flagged). Members stay in
    `members`, so a folded approval is shown, never dropped. Items in `exclude_ids` (supply flows) are left alone and
    get no `asset`: spec_compare then never matches them on amount, so a supply flow is judged as one group, not piecewise.
    """
    def same_flow(a, b):
        return (a.get("payload"), a.get("section"), a.get("raw_amount")) == (
            b.get("payload"), b.get("section"), b.get("raw_amount")
        )

    def lower(addr):
        return (addr or "").lower()

    candidates = [
        (pos, it)
        for pos, it in enumerate(items)
        if id(it) not in exclude_ids and it.get("event_name") in ("Transfer", "Approval") and it.get("raw_amount") != "0"
    ]
    used = set()
    units_at = {}
    for pos, head in candidates:
        if id(head) in used or head.get("event_name") != "Transfer":
            continue
        hops = [(pos, head)]
        used.add(id(head))
        while True:
            last_pos, last = hops[-1]
            nxt = next(
                (
                    (p, it)
                    for p, it in candidates
                    if p > last_pos
                    and id(it) not in used
                    and it.get("event_name") == "Transfer"
                    and same_flow(it, head)
                    and lower(it.get("counterparty")) == lower(last.get("recipient"))
                ),
                None,
            )
            if nxt is None:
                break
            hops.append(nxt)
            used.add(id(nxt[1]))
        members = list(hops)
        flow_payees = {lower(hop.get("recipient")) for _, hop in hops}
        for hop_pos, hop in hops:
            approval = next(
                (
                    (p, it)
                    for p, it in candidates
                    if p < hop_pos
                    and id(it) not in used
                    and it.get("event_name") == "Approval"
                    and same_flow(it, head)
                    and lower(it.get("counterparty")) == lower(hop.get("counterparty"))
                    and lower(it.get("recipient")) in flow_payees
                ),
                None,
            )
            if approval:
                members.append(approval)
                used.add(id(approval[1]))
        if len(members) > 1:
            tail = hops[-1][1]
            units_at[pos] = {
                **tail,
                "counterparty": head.get("counterparty"),
                "members": [it for _, it in sorted(members, key=lambda m: m[0])],
            }
    folded = {id(m) for unit in units_at.values() for m in unit["members"]}
    units = []
    for pos, item in enumerate(items):
        if pos in units_at:
            units.append(units_at[pos])
        elif id(item) not in folded:
            units.append(item)
    return [u if id(u) in exclude_ids else {**u, "asset": _token_symbol(u, symbol_map)} for u in units]

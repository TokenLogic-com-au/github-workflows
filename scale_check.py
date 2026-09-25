#!/usr/bin/env python3
"""Deterministic sanity-bound check for #1 (decimals mistakes), run over a
ProtocolV3TestBase diff report. Independent of the AI step: it never reads
the AI's table, only the diff report's own numbers, so a wrong AI read can't
mask a real scale error.

Catches the case the diff report itself doesn't decode: raw integer amounts
(e.g. MainnetSwapSteward UpdatedTokenBudget) next to a recognizable token
symbol, where amount / 10**decimals lands far outside a plausible human
range. This is a bound, not a match against the forum figure -- it flags
`10_000_000e18` for USDC (10 septillion "USDC") but does not know the forum
said "10M".
"""
import re
import sys

DECIMALS = {
    "USDC": 6, "USDT": 6, "USDC.E": 6,
    "DAI": 18, "GHO": 18, "AAVE": 18, "WETH": 18, "USDE": 18,
    "USDS": 18, "RLUSD": 18, "PYUSD": 18, "AETHLIDOGHO": 18,
    "AETHUSDC": 6, "ABASUSDC": 6, "WBTC": 8, "AETHWBTC": 8,
}
LOW_BOUND = 1e-6
HIGH_BOUND = 1e9
RAW_LINE = re.compile(
    r"(?P<symbol>[A-Za-z][A-Za-z0-9._]*)[:\s]+(?P<raw>\d{6,})(?!\s*decimals)", re.IGNORECASE
)
DECODED_LINE = re.compile(r"\[\s*\d[\d,]*\s*,\s*\d+\s*decimals\s*\]")


def check(report_text):
    flags = []
    for line in report_text.splitlines():
        if DECODED_LINE.search(line):
            continue  # already decoded with its own decimals; not our gap case
        for m in RAW_LINE.finditer(line):
            symbol = m.group("symbol").upper()
            decimals = DECIMALS.get(symbol)
            if decimals is None:
                continue
            raw = int(m.group("raw"))
            human = raw / (10 ** decimals)
            if human < LOW_BOUND or human > HIGH_BOUND:
                flags.append(
                    f"possible decimals error: {symbol} raw={raw} -> {human:g} human units "
                    f"(outside [{LOW_BOUND:g}, {HIGH_BOUND:g}]) in line: {line.strip()}"
                )
            break
    return flags


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: scale_check.py <diff-report-file>")
    with open(sys.argv[1], encoding="utf-8") as f:
        text = f.read()
    flags = check(text)
    if flags:
        print("\n".join(flags))
        sys.exit(0)  # advisory: never fails the job, caller decides whether to comment
    print("no scale-bound flags")


if __name__ == "__main__":
    main()

"""D10 linked wallets: groups of wallets that share a signal.
  * same first funder (the first wallet that sent them value)
  * paid the same destination within a short window
  * poisoned the same victims (from D1)
Groups larger than max_group are skipped: those are usually exchanges or faucets, not a related set."""

from collections import defaultdict

import pandas as pd

from app.scam.detectors.base import NOT_WALLETS, Context, Finding, short


def first_funders(tx: pd.DataFrame) -> pd.Series:
    """wallet -> address of its first incoming value transfer (stable tie-break on tx hash)."""
    pos = tx[(tx["value"] > 0) & ~tx["from_addr"].isin(NOT_WALLETS) & ~tx["to_addr"].isin(NOT_WALLETS)]
    pos = pos.sort_values(["block_number", "tx_hash"])
    return pos.drop_duplicates("to_addr").set_index("to_addr")["from_addr"]


def _group_findings(groups: dict[str, list[str]], signal: str, reason_fn, score: int, ctx: Context,
                    min_group: int | None = None) -> list[Finding]:
    c = ctx.cfg
    lo = c.scam_linked_min_group if min_group is None else min_group
    out = []
    for key in sorted(groups):
        members = sorted(set(groups[key]))
        if not (lo <= len(members) <= c.scam_linked_max_group):
            continue
        gid = f"{signal}:{key}"
        for m in members:
            if ctx.is_service(m):
                continue
            out.append(Finding("D10", m, score, "low" if score < 40 else "medium", reason_fn(key, len(members)),
                               related=[x for x in members if x != m][:25],
                               details={"group_id": gid, "signal": signal, "key": key, "size": len(members)}))
    return out


def detect(tx: pd.DataFrame, tt: pd.DataFrame, ap: pd.DataFrame, ctx: Context) -> list[Finding]:
    c = ctx.cfg
    out: list[Finding] = []

    funders = first_funders(tx)
    by_funder: dict[str, list[str]] = defaultdict(list)
    for wallet, funder in funders.items():
        if not ctx.is_service(funder):
            by_funder[funder].append(wallet)
    out += _group_findings(by_funder, "same_first_funder",
                           lambda k, n: f"Possibly linked: one of {n} wallets whose first funds came from the same address {short(k)}.",
                           25, ctx)

    sends = tx[(tx["value"] > 0) & ~tx["to_addr"].isin(NOT_WALLETS)].sort_values(["to_addr", "block_number", "tx_hash"])
    by_dest: dict[str, list[str]] = {}
    senders_per_dest = sends.groupby("to_addr")["from_addr"].nunique()
    candidates = senders_per_dest[senders_per_dest.between(c.scam_linked_min_group, c.scam_linked_max_group)].index
    sends = sends[sends["to_addr"].isin(candidates)]
    for dest, g in sends.groupby("to_addr"):
        if ctx.is_service(dest) or g["from_addr"].nunique() > c.scam_linked_max_group:
            continue
        blocks, senders = g["block_number"].tolist(), g["from_addr"].tolist()
        start = 0
        best: set[str] = set()
        for end in range(len(blocks)):
            while blocks[end] - blocks[start] > c.scam_linked_window_blocks:
                start += 1
            window = set(senders[start:end + 1])
            if len(window) > len(best):
                best = window
        if len(best) >= c.scam_linked_min_group:
            by_dest[dest] = sorted(best)
    out += _group_findings(by_dest, "same_destination_burst",
                           lambda k, n: f"Possibly linked: one of {n} wallets that paid {short(k)} within "
                                        f"{c.scam_linked_window_blocks} blocks of each other.",
                           25, ctx)

    by_victim: dict[str, list[str]] = defaultdict(list)
    for f in ctx.prior.get("D1", []):
        by_victim[f.details.get("victim", "")].append(f.wallet)
    poison_groups = {v: w for v, w in by_victim.items() if v}
    out += _group_findings(poison_groups, "shared_poisoning_victim",
                           lambda k, n: f"Possibly linked: one of {n} look-alike senders that targeted the same victim {short(k)}.",
                           40, ctx, min_group=2)              # two poisoners sharing a victim is already a link
    return out

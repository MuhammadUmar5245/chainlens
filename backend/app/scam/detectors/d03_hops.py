"""D3 hop chain / peeling: A->B->C... where each hop forwards min_ratio..max_ratio of the previous amount,
not earlier than the previous hop. Edges need value >= min. Paths up to max_depth hops."""

from collections import defaultdict

import pandas as pd

from app.scam.detectors.base import NOT_WALLETS, Context, Finding, severity_for, short


def _edges(tx: pd.DataFrame, ctx: Context):
    e = tx[(tx["value"] >= ctx.cfg.scam_hops_min_eth) & ~tx["from_addr"].isin(NOT_WALLETS) & ~tx["to_addr"].isin(NOT_WALLETS)]
    e = e.sort_values(["block_number", "tx_hash"])
    edges = list(e[["from_addr", "to_addr", "value", "block_number", "tx_hash"]].itertuples(index=False, name=None))
    out_by = defaultdict(list)
    for edge in edges:
        out_by[edge[0]].append(edge)
    return edges, out_by


def _next(edge, out_by, ctx: Context, visited: set):
    c = ctx.cfg
    _, b, v1, blk, _ = edge
    if ctx.apply_exclusions and ctx.is_service(b):
        return []                                   # an exchange or contract is an endpoint, not a hop
    nxt = [n for n in out_by.get(b, []) if n[3] >= blk and c.scam_hops_min_ratio * v1 <= n[2] <= c.scam_hops_max_ratio * v1
           and n[1] not in visited]
    if ctx.apply_exclusions and len(nxt) > c.scam_hops_max_branch:
        return []                                   # many matching payouts = batch payer, not a single hop chain
    return nxt


def two_hop_count(tx: pd.DataFrame, ctx: Context) -> int:
    """Raw metric: number of qualifying edge pairs A->B->C (cycles included, as in the raw definition)."""
    edges, out_by = _edges(tx, ctx)
    return sum(len(_next(e, out_by, ctx, set())) for e in edges)


def hop_paths(tx: pd.DataFrame, ctx: Context) -> list[list[tuple]]:
    """Maximal paths (2+ hops) that start at an edge with no qualifying predecessor."""
    c = ctx.cfg
    edges, out_by = _edges(tx, ctx)
    has_pred = set()
    for e in edges:
        for n in _next(e, out_by, ctx, {e[0], e[1]}):
            has_pred.add(n)
    paths: list[list[tuple]] = []

    def walk(path, visited):
        if len(paths) >= c.scam_hops_max_paths:
            return
        nxt = _next(path[-1], out_by, ctx, visited) if len(path) < c.scam_hops_max_depth else []
        if not nxt:
            if len(path) >= 2:
                paths.append(list(path))
            return
        for n in nxt:
            walk(path + [n], visited | {n[1]})

    for e in edges:
        if e not in has_pred:
            walk([e], {e[0], e[1]})
    return paths


def detect(tx: pd.DataFrame, tt: pd.DataFrame, ap: pd.DataFrame, ctx: Context) -> list[Finding]:
    out = []
    for path in hop_paths(tx, ctx):
        wallets = [path[0][0]] + [e[1] for e in path]
        hops = len(path)
        score = min(85, 45 + 10 * (hops - 1))
        out.append(Finding(
            "D3", wallets[1], score, severity_for(score),
            f"Possible hop chain: {path[0][2]:.4g} moved through {hops} wallets in a row "
            f"({' → '.join(short(w) for w in wallets[:4])}{' → …' if len(wallets) > 4 else ''}), "
            f"each passing on 80–100% of what it received.",
            related=wallets, tx_hashes=[e[4] for e in path],
            details={"path": wallets, "amounts": [float(e[2]) for e in path], "blocks": [int(e[3]) for e in path], "hops": hops}))
    return out

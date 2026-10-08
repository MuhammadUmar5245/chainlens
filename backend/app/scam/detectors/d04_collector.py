"""D4 collector (fan-in): at least min_senders distinct senders to one address.
Excludes labelled exchanges / contracts and addresses that mostly receive contract calls."""

import pandas as pd

from app.scam.detectors.base import NOT_WALLETS, Context, Finding, severity_for


def collector_table(tx: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    c = ctx.cfg
    t = tx[~tx["to_addr"].isin(NOT_WALLETS)]
    g = t.groupby("to_addr").agg(senders=("from_addr", "nunique"), received=("value", "sum"),
                                 n=("tx_hash", "count"), contract_share=("is_contract_call", "mean"))
    g = g[g["senders"] >= c.scam_fanin_min_senders]
    if ctx.apply_exclusions:
        not_service = pd.Series([not ctx.is_service(a) for a in g.index], index=g.index, dtype=bool)
        g = g[(g["contract_share"] <= c.scam_fanin_max_contract_share) & not_service]
    return g.sort_index()


def detect(tx: pd.DataFrame, tt: pd.DataFrame, ap: pd.DataFrame, ctx: Context) -> list[Finding]:
    out = []
    for w, r in collector_table(tx, ctx).iterrows():
        score = int(min(70, 30 + r["senders"] / 4))
        out.append(Finding(
            "D4", w, score, severity_for(score),
            f"Possible collector wallet: received from {int(r['senders'])} different wallets "
            f"({int(r['n'])} transfers, {r['received']:.4g} in total).",
            tx_hashes=tx[tx["to_addr"] == w]["tx_hash"].head(10).tolist(),
            details={"senders": int(r["senders"]), "transfers": int(r["n"]), "received": float(r["received"]),
                     "contract_call_share": float(r["contract_share"])}))
    return out

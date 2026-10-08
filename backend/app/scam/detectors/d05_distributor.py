"""D5 distributor (fan-out): at least min_receivers distinct receivers from one address.
Excludes labelled exchanges and known contracts."""

import pandas as pd

from app.scam.detectors.base import NOT_WALLETS, Context, Finding, first_hashes, severity_for


def distributor_table(tx: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    t = tx[~tx["to_addr"].isin(NOT_WALLETS)]
    g = t.groupby("from_addr").agg(receivers=("to_addr", "nunique"), sent=("value", "sum"), n=("tx_hash", "count"))
    g = g[g["receivers"] >= ctx.cfg.scam_fanout_min_receivers]
    g = g[~g.index.isin(NOT_WALLETS)]
    if ctx.apply_exclusions:
        g = g[pd.Series([not ctx.is_service(a) for a in g.index], index=g.index, dtype=bool)]
    return g.sort_index()


def detect(tx: pd.DataFrame, tt: pd.DataFrame, ap: pd.DataFrame, ctx: Context) -> list[Finding]:
    out = []
    table = distributor_table(tx, ctx)
    hashes = first_hashes(tx[tx["from_addr"].isin(table.index)], "from_addr", 10)
    for w, r in table.iterrows():
        score = int(min(70, 30 + r["receivers"] / 4))
        out.append(Finding(
            "D5", w, score, severity_for(score),
            f"Possible distributor wallet: sent to {int(r['receivers'])} different wallets "
            f"({int(r['n'])} transfers, {r['sent']:.4g} in total).",
            tx_hashes=hashes.get(w, []),
            details={"receivers": int(r["receivers"]), "transfers": int(r["n"]), "sent": float(r["sent"])}))
    return out

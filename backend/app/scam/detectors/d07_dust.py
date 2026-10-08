"""D7 dust spam: a sender with at least min_count tiny transfers (0 < value < max) to distinct addresses,
or zero-amount token transfers to distinct addresses."""

import pandas as pd

from app.scam.detectors.base import NOT_WALLETS, Context, Finding, severity_for


def dust_txs(tx: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    return tx[(tx["value"] > 0) & (tx["value"] < ctx.cfg.scam_dust_max_eth)]


def detect(tx: pd.DataFrame, tt: pd.DataFrame, ap: pd.DataFrame, ctx: Context) -> list[Finding]:
    n_min = ctx.cfg.scam_dust_min_count
    out = []
    groups = [("native", dust_txs(tx, ctx))]
    if not tt.empty:
        groups.append(("token", tt[tt["amount"] == 0]))
    for kind, d in groups:
        g = d.groupby("from_addr").agg(recipients=("to_addr", "nunique"), n=("tx_hash", "count"))
        for w, r in g[g["recipients"] >= n_min].sort_index().iterrows():
            if w in NOT_WALLETS or ctx.is_service(w):
                continue
            score = 55 if r["recipients"] >= 5 * n_min else 35
            what = "tiny transfers" if kind == "native" else "zero-amount token transfers"
            out.append(Finding(
                "D7", w, score, severity_for(score),
                f"Possible dust spam: sent {int(r['n'])} {what} to {int(r['recipients'])} different addresses.",
                related=sorted(d[d["from_addr"] == w]["to_addr"].unique())[:20],
                tx_hashes=d[d["from_addr"] == w]["tx_hash"].head(10).tolist(),
                details={"kind": kind, "transfers": int(r["n"]), "recipients": int(r["recipients"])}))
    return out

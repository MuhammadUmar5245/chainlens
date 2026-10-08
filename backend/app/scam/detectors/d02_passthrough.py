"""D2 pass-through / mule: receives at least min_in, sends at least min_forward_ratio of it on,
and the last outgoing payment is not before the first incoming one."""

import pandas as pd

from app.scam.detectors.base import NOT_WALLETS, Context, Finding, severity_for, short


def passthrough_table(tx: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    c = ctx.cfg
    pos = tx[tx["value"] > 0]
    rin = pos.groupby("to_addr").agg(received=("value", "sum"), first_in=("block_number", "min"), n_in=("tx_hash", "count"))
    sout = pos.groupby("from_addr").agg(sent=("value", "sum"), last_out=("block_number", "max"), n_out=("tx_hash", "count"))
    j = rin.join(sout, how="inner")
    j = j[(j["received"] >= c.scam_passthrough_min_in_eth) & (j["sent"] >= c.scam_passthrough_min_forward_ratio * j["received"])
          & (j["last_out"] >= j["first_in"])]
    j = j[~j.index.isin(NOT_WALLETS)]
    if ctx.apply_exclusions:
        j = j[[not ctx.is_service(a) for a in j.index]]
    return j.sort_index()


def detect(tx: pd.DataFrame, tt: pd.DataFrame, ap: pd.DataFrame, ctx: Context) -> list[Finding]:
    out = []
    t = passthrough_table(tx, ctx)
    pos = tx[tx["value"] > 0]
    for w, r in t.iterrows():
        hold = int(r["last_out"] - r["first_in"])
        score = int(min(85, 40 + 30 * min(1.0, r["received"] / 50) + (15 if hold < 10 else 0)))
        hashes = pos[(pos["to_addr"] == w)]["tx_hash"].head(5).tolist() + pos[(pos["from_addr"] == w)]["tx_hash"].head(5).tolist()
        out.append(Finding(
            "D2", w, score, severity_for(score),
            f"Possible pass-through wallet: received {r['received']:.4g} and sent {r['sent']:.4g} "
            f"({r['sent'] / r['received']:.0%}) onward within {hold} blocks.",
            tx_hashes=hashes,
            details={"received": float(r["received"]), "sent": float(r["sent"]), "first_in_block": int(r["first_in"]),
                     "last_out_block": int(r["last_out"]), "hold_blocks": hold, "n_in": int(r["n_in"]), "n_out": int(r["n_out"])}))
    return out

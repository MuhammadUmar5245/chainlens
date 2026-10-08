"""D6 new wallet, big money: a wallet whose first transaction in the data has nonce 0 receives at least
min (native coin, or USDT/USDC in stablecoin units) and forwards most of it within a short window."""

import pandas as pd

from app.scam.detectors.base import NOT_WALLETS, Context, Finding, severity_for, short


def _check(inflow: pd.DataFrame, outflow: pd.DataFrame, wallet: str, minimum: float, ctx: Context, unit: str):
    c = ctx.cfg
    ins = inflow[inflow["to_addr"] == wallet]
    if ins.empty:
        return None
    start = int(ins["block_number"].min())
    end = start + c.scam_newwallet_window_blocks
    received = float(ins[(ins["block_number"] <= end)]["amount"].sum())
    outs = outflow[(outflow["from_addr"] == wallet) & (outflow["block_number"] >= start) & (outflow["block_number"] <= end)]
    sent = float(outs["amount"].sum())
    if received < minimum or sent < c.scam_newwallet_forward_ratio * received:
        return None
    blocks = int(outs["block_number"].max() - start) if not outs.empty else 0
    score = 75 if blocks <= 10 else 60
    return Finding(
        "D6", wallet, score, severity_for(score),
        f"Possible new wallet moving big money: a fresh wallet (first transaction nonce 0) received {received:,.4g} {unit} "
        f"and sent {sent / received:.0%} of it on within {blocks} blocks.",
        related=sorted(set(ins["from_addr"]) | set(outs["to_addr"]))[:20],
        tx_hashes=ins["tx_hash"].head(5).tolist() + outs["tx_hash"].head(5).tolist(),
        details={"unit": unit, "received": received, "sent": sent, "first_in_block": start, "forward_blocks": blocks})


def new_wallets(tx: pd.DataFrame) -> set[str]:
    return set(tx.loc[tx["nonce"] == 0, "from_addr"]) - NOT_WALLETS


def detect(tx: pd.DataFrame, tt: pd.DataFrame, ap: pd.DataFrame, ctx: Context) -> list[Finding]:
    c = ctx.cfg
    fresh = sorted(w for w in new_wallets(tx) if not ctx.is_service(w))
    native = tx[tx["value"] > 0].rename(columns={"value": "amount"})
    stable = tt[tt["token_address"].isin(ctx.known_tokens) &
                tt["token_address"].map(lambda a: ctx.known_tokens.get(a) in ("USDT", "USDC"))] if not tt.empty else tt
    out = []
    for w in fresh:
        f = _check(native, native, w, c.scam_newwallet_min_eth, ctx, "native coin")
        if f is None and not stable.empty:
            f = _check(stable, stable, w, c.scam_newwallet_min_stable, ctx, "USDT/USDC")
        if f:
            out.append(f)
    return out

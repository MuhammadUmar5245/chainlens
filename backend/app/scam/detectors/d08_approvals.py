"""D8 approval phishing: an unlimited token approval to a spender that is a plain wallet (EOA), is new in the data,
or is on a user-supplied scam list. Severity rises when the spender then pulls tokens out of the owner's wallet."""

import pandas as pd

from app.scam.detectors.base import Context, Finding, severity_for, short


def detect(tx: pd.DataFrame, tt: pd.DataFrame, ap: pd.DataFrame, ctx: Context) -> list[Finding]:
    if ap.empty:
        return []
    c = ctx.cfg
    unlimited = ap[ap["is_unlimited"].astype(bool)]
    first_seen = pd.concat([tx[["from_addr", "block_number"]].rename(columns={"from_addr": "a"}),
                            tx[["to_addr", "block_number"]].rename(columns={"to_addr": "a"})]).groupby("a")["block_number"].min()
    initiator = dict(zip(tx["tx_hash"], tx["from_addr"]))
    out = []
    for r in unlimited.sort_values(["block_number", "tx_hash"]).itertuples():
        reasons = []
        if int(r.spender_is_contract) == 0:
            reasons.append("the spender is a plain wallet, not a contract")
        if "scam_reported" in ctx.categories(r.spender):
            reasons.append("the spender is on a user-supplied scam list")
        seen = first_seen.get(r.spender)
        if int(r.spender_is_contract) != 1 and seen is not None and seen >= r.block_number - c.scam_approval_new_spender_blocks \
                and seen >= first_seen.min() + c.scam_approval_new_spender_blocks:
            reasons.append("the spender only appeared recently")
        if not reasons:
            continue
        drains = tt[(tt["from_addr"] == r.owner) & (tt["token_address"] == r.token_address) & (tt["block_number"] >= r.block_number)
                    & (tt["tx_hash"].map(initiator.get) == r.spender)] if not tt.empty else tt
        score = 90 if not drains.empty or "scam" in " ".join(reasons) else 65
        drained = f" and then moved {drains['amount'].sum():,.4g} {drains['token_symbol'].iloc[0]} out of it" if not drains.empty else ""
        out.append(Finding(
            "D8", r.spender, score, severity_for(score),
            f"Possible approval phishing: received unlimited permission to spend {short(r.owner)}'s tokens "
            f"({'; '.join(reasons)}){drained}.",
            related=[r.owner], tx_hashes=[r.tx_hash] + drains["tx_hash"].head(5).tolist(),
            details={"owner": r.owner, "spender": r.spender, "token": r.token_address, "block": int(r.block_number),
                     "signals": reasons, "drain_amount": float(drains["amount"].sum()) if not drains.empty else 0.0}))
    return out

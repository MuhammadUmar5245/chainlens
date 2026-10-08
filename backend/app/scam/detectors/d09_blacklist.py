"""D9 blacklist match: interaction with an address the user labelled sanctioned, scam_reported or mixer,
directly or through one intermediate wallet."""

import pandas as pd

from app.scam.detectors.base import BLACKLIST_CATEGORIES, NOT_WALLETS, Context, Finding, short


def _edges(tx: pd.DataFrame, tt: pd.DataFrame) -> pd.DataFrame:
    parts = [tx[["from_addr", "to_addr", "tx_hash"]]]
    if not tt.empty:
        parts.append(tt[["from_addr", "to_addr", "tx_hash"]])
    e = pd.concat(parts)
    return e[~e["from_addr"].isin(NOT_WALLETS) & ~e["to_addr"].isin(NOT_WALLETS)]


def detect(tx: pd.DataFrame, tt: pd.DataFrame, ap: pd.DataFrame, ctx: Context) -> list[Finding]:
    listed = {a for a, ls in ctx.labels.items() if {l["category"] for l in ls} & BLACKLIST_CATEGORIES}
    if not listed:
        return []
    e = _edges(tx, tt)
    present = sorted(listed & (set(e["from_addr"]) | set(e["to_addr"])))
    out: list[Finding] = []
    direct: dict[str, tuple[str, str]] = {}                      # wallet -> (listed address, tx hash)
    for bad in present:
        out.append(Finding("D9", bad, 100, "high",
                           f"On a user-supplied list: {ctx.label_text(bad)}.",
                           details={"labels": ctx.labels.get(bad, [])}))
        touching = e[(e["from_addr"] == bad) | (e["to_addr"] == bad)]
        for row in touching.itertuples():
            other = row.to_addr if row.from_addr == bad else row.from_addr
            if other != bad and other not in listed and other not in direct and not ctx.is_service(other):
                direct[other] = (bad, row.tx_hash)
    for w, (bad, h) in sorted(direct.items()):
        out.append(Finding("D9", w, 90, "high",
                           f"Transacted directly with {short(bad)}, which is on a user-supplied list ({ctx.label_text(bad)}).",
                           related=[bad], tx_hashes=[h], details={"hops": 1, "matched": bad, "labels": ctx.labels.get(bad, [])}))
    seen = set(direct) | listed
    for w, (bad, _) in sorted(direct.items()):
        touching = e[(e["from_addr"] == w) | (e["to_addr"] == w)]
        for row in touching.itertuples():
            other = row.to_addr if row.from_addr == w else row.from_addr
            if other in seen or ctx.is_service(other):
                continue
            seen.add(other)
            out.append(Finding("D9", other, 45, "medium",
                               f"Two steps from a listed address: transacted with {short(w)}, which transacted with {short(bad)} "
                               f"({ctx.label_text(bad)}).",
                               related=[w, bad], tx_hashes=[row.tx_hash], details={"hops": 2, "via": w, "matched": bad}))
    return out

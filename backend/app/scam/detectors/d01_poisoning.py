"""D1 address poisoning.

A victim V really pays R; later V receives a tiny transfer from F, an address that looks like R
(same first and last characters), hoping V copies F from its history next time.

Native coin: real V->R (value >= real_min, not a contract call), fake F->V (value < fake_max, not a contract call),
F != R, F matches R on prefix/suffix, block(fake) >= block(real).
Tokens: real V->R of a token (amount >= real_min_token); fake is a transfer between V and a look-alike F that is
either dust/zero of the same token or any amount of a counterfeit token (e.g. "U⁯S⁯DΤ" pretending to be USDT).
"""

import pandas as pd

from app.scam.detectors.base import Context, Finding, is_counterfeit, is_hex_address, short


def poisoning_matches(tx: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    """Native-coin matches, one row per (real, fake) pair. Columns: V, R, F, b_real, b_fake, h_real, h_fake, nonce."""
    c = ctx.cfg
    p, s = c.scam_poison_prefix_len, c.scam_poison_suffix_len
    plain = tx[~tx["is_contract_call"].astype(bool)]
    real = plain[plain["value"] >= c.scam_poison_real_min_eth][["from_addr", "to_addr", "block_number", "tx_hash"]]
    real = real.rename(columns={"from_addr": "V", "to_addr": "R", "block_number": "b_real", "tx_hash": "h_real"})
    fake = plain[plain["value"] < c.scam_poison_fake_max_eth][["from_addr", "to_addr", "block_number", "tx_hash", "nonce"]]
    fake = fake.rename(columns={"from_addr": "F", "to_addr": "V", "block_number": "b_fake", "tx_hash": "h_fake"})
    m = real.merge(fake, on="V")
    if m.empty:
        return m
    m = m[(m["F"] != m["R"]) & m["F"].map(is_hex_address) & m["R"].map(is_hex_address)
          & (m["F"].str[2:2 + p] == m["R"].str[2:2 + p]) & (m["F"].str[-s:] == m["R"].str[-s:])
          & (m["b_fake"] >= m["b_real"])]
    return m.sort_values(["V", "F", "h_real", "h_fake"]).reset_index(drop=True)


def token_matches(tt: pd.DataFrame, ctx: Context) -> pd.DataFrame:
    c = ctx.cfg
    p, s = c.scam_poison_prefix_len, c.scam_poison_suffix_len
    if tt.empty:
        return pd.DataFrame()
    fake_token = tt.apply(lambda r: is_counterfeit(r["token_symbol"], r["token_address"], ctx.known_tokens), axis=1)
    real = tt[(tt["amount"] >= c.scam_poison_real_min_token) & ~fake_token]
    real = real[["from_addr", "to_addr", "block_number", "tx_hash", "token_address", "token_symbol"]].rename(
        columns={"from_addr": "V", "to_addr": "R", "block_number": "b_real", "tx_hash": "h_real", "token_address": "token",
                 "token_symbol": "symbol"})
    dust = tt[(tt["amount"] <= c.scam_poison_fake_max_token) | fake_token].assign(counterfeit=fake_token)
    # the look-alike can appear on either side: F->V (sent to the victim) or V->F (spoofed zero transfer "from" V)
    a = dust.rename(columns={"from_addr": "F", "to_addr": "V"})
    b = dust.rename(columns={"to_addr": "F", "from_addr": "V"})
    cols = ["F", "V", "block_number", "tx_hash", "token_address", "token_symbol", "amount", "counterfeit"]
    fake = pd.concat([a[cols], b[cols]]).rename(columns={"block_number": "b_fake", "tx_hash": "h_fake",
                                                        "token_address": "fake_token", "token_symbol": "fake_symbol"})
    m = real.merge(fake, on="V")
    if m.empty:
        return m
    same_or_fake = (m["fake_token"] == m["token"]) | m["counterfeit"]
    m = m[same_or_fake & (m["F"] != m["R"]) & m["F"].map(is_hex_address) & m["R"].map(is_hex_address)
          & (m["F"].str[2:2 + p] == m["R"].str[2:2 + p]) & (m["F"].str[-s:] == m["R"].str[-s:])
          & (m["b_fake"] >= m["b_real"])]
    return m.drop_duplicates(["V", "R", "F", "h_real", "h_fake"]).sort_values(["V", "F", "h_real", "h_fake"]).reset_index(drop=True)


def detect(tx: pd.DataFrame, tt: pd.DataFrame, ap: pd.DataFrame, ctx: Context) -> list[Finding]:
    fast = ctx.cfg.scam_poison_fast_blocks
    out: list[Finding] = []
    for r in poisoning_matches(tx, ctx).itertuples():
        delay = int(r.b_fake - r.b_real)
        high = int(r.nonce) == 0 or delay < fast
        score = 85 if high else 65
        out.append(Finding(
            "D1", r.F, score, "high" if high else "medium",
            f"Possible address poisoning: sent a tiny amount to {short(r.V)} from a look-alike of {short(r.R)}, "
            f"an address {short(r.V)} had paid {delay} blocks earlier.",
            related=[r.V, r.R], tx_hashes=[r.h_real, r.h_fake],
            details={"kind": "native", "victim": r.V, "real_recipient": r.R, "fake": r.F, "delay_blocks": delay,
                     "fake_nonce": int(r.nonce)}))
    for r in token_matches(tt, ctx).itertuples():
        delay = int(r.b_fake - r.b_real)
        high = bool(r.counterfeit) or delay < fast
        what = f"a counterfeit token '{r.fake_symbol}'" if r.counterfeit else f"{r.amount:g} {r.symbol}"
        out.append(Finding(
            "D1", r.F, 85 if high else 65, "high" if high else "medium",
            f"Possible token address poisoning: {what} moved between {short(r.V)} and a look-alike of {short(r.R)}, "
            f"whom {short(r.V)} had paid in {r.symbol}.",
            related=[r.V, r.R], tx_hashes=[r.h_real, r.h_fake],
            details={"kind": "token", "victim": r.V, "real_recipient": r.R, "fake": r.F, "delay_blocks": delay,
                     "token": r.token, "symbol": r.symbol, "fake_token": r.fake_token, "fake_symbol": r.fake_symbol,
                     "counterfeit": bool(r.counterfeit)}))
    return out

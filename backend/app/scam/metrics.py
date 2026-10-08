"""Raw sample metrics (requirements section 9.2): the definitions before any label-based exclusions."""

import pandas as pd

from app.scam.detectors import d01_poisoning, d02_passthrough, d03_hops, d04_collector, d05_distributor, d07_dust
from app.scam.detectors.base import Context, is_hex_address, lookalike_key


def raw_metrics(tx: pd.DataFrame, ctx: Context) -> dict:
    raw = Context(chain=ctx.chain, cfg=ctx.cfg, apply_exclusions=False)
    c = ctx.cfg
    addrs = pd.unique(pd.concat([tx["from_addr"], tx["to_addr"]]))
    addrs = sorted(a for a in addrs if is_hex_address(a))
    keys = pd.Series(addrs).map(lambda a: lookalike_key(a, c.scam_poison_prefix_len, c.scam_poison_suffix_len))
    d1 = d01_poisoning.poisoning_matches(tx, raw)
    fake_first_nonce = d1.groupby("F")["nonce"].min() if len(d1) else pd.Series(dtype=int)
    return {
        "transactions": int(len(tx)),
        "blocks": int(tx["block_number"].nunique()),
        "unique_addresses": len(addrs),
        "lookalike_groups": int((keys.value_counts() >= 2).sum()),
        "d1_matches": int(len(d1)),
        "d1_victims": int(d1["V"].nunique()) if len(d1) else 0,
        "d1_fake_senders": int(d1["F"].nunique()) if len(d1) else 0,
        "d1_fake_nonce0_share": round(float((fake_first_nonce == 0).mean()), 2) if len(d1) else 0.0,
        "d1_median_delay_blocks": float((d1["b_fake"] - d1["b_real"]).median()) if len(d1) else 0.0,
        "d2_passthrough": int(len(d02_passthrough.passthrough_table(tx, raw))),
        "d3_two_hop_chains": d03_hops.two_hop_count(tx, raw),
        "d4_collectors": int(len(d04_collector.collector_table(tx, raw))),
        "d5_distributors": int(len(d05_distributor.distributor_table(tx, raw))),
        "senders_nonce0": int(tx.loc[tx["nonce"] == 0, "from_addr"].nunique()),
        "dust_transactions": int(len(d07_dust.dust_txs(tx, raw))),
        "zero_value_contract_calls": int((tx["is_contract_call"].astype(bool) & (tx["value"] == 0)).sum()),
    }

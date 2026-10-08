"""Requirements 9.1: each detector on a small synthetic fixture with known positives and negatives."""

import pandas as pd
import pytest

from app.scam.config import ScamSettings
from app.scam.detectors import (d01_poisoning, d02_passthrough, d03_hops, d04_collector, d05_distributor, d06_new_wallet,
                                d07_dust, d08_approvals, d09_blacklist, d10_linked)
from app.scam.detectors.base import Context, empty_ap, empty_tt, is_counterfeit, normalise_symbol
from app.scam.risk import wallet_risk

USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"


def addr(prefix: str, middle: str, suffix: str) -> str:
    """0x + 4 chars + 32-char middle + 4 chars."""
    return "0x" + prefix + middle * (32 // len(middle)) + suffix


def tx(rows):
    df = pd.DataFrame(rows, columns=["from_addr", "to_addr", "value", "block_number", "nonce", "is_contract_call"])
    df["tx_hash"] = [f"0x{i:064x}" for i in range(len(df))]
    df["block_time"] = pd.Timestamp("2026-10-07", tz="UTC")
    return df


def tt(rows):
    df = pd.DataFrame(rows, columns=["from_addr", "to_addr", "amount", "block_number", "token_address", "token_symbol"])
    df["tx_hash"] = [f"0xt{i:063x}" for i in range(len(df))]
    df["log_index"] = 0
    df["block_time"] = pd.Timestamp("2026-10-07", tz="UTC")
    return df


@pytest.fixture
def ctx():
    return Context(chain="eth", cfg=ScamSettings(), known_tokens={USDT: "USDT"})


V = addr("aaaa", "1", "bbbb")          # victim
R = addr("1234", "2", "5678")          # real recipient
F = addr("1234", "3", "5678")          # look-alike of R
X = addr("9999", "4", "0000")          # unrelated


# --- D1 ------------------------------------------------------------------------------------------
def test_d1_flags_lookalike_dust_after_real_payment(ctx):
    found = d01_poisoning.detect(tx([(V, R, 1.0, 100, 5, False), (F, V, 0.0, 105, 0, False)]), empty_tt(), empty_ap(), ctx)
    assert [(f.wallet, f.severity) for f in found] == [(F, "high")]
    assert found[0].related == [V, R] and len(found[0].tx_hashes) == 2


def test_d1_ignores_dust_before_payment_and_non_lookalikes(ctx):
    before = tx([(F, V, 0.0, 90, 0, False), (V, R, 1.0, 100, 5, False)])
    other = tx([(V, R, 1.0, 100, 5, False), (X, V, 0.0, 105, 0, False)])
    assert d01_poisoning.detect(before, empty_tt(), empty_ap(), ctx) == []
    assert d01_poisoning.detect(other, empty_tt(), empty_ap(), ctx) == []


def test_d1_token_counterfeit_and_zero_transfer(ctx):
    t = tt([(V, R, 500.0, 100, USDT, "USDT"), (F, V, 500.0, 101, "0x" + "e" * 40, "U⁠S⁠DΤ"),
            (V, F, 0.0, 102, USDT, "USDT")])
    found = d01_poisoning.detect(tx([]), t, empty_ap(), ctx)
    assert {f.wallet for f in found} == {F}
    assert any(f.details["counterfeit"] for f in found) and any(not f.details["counterfeit"] for f in found)


def test_counterfeit_symbols():
    assert normalise_symbol("U⁠S⁠DΤ") == "USDT"
    assert is_counterfeit("ꓴ឵ՏᎠ឵Ⲧ", "0x" + "e" * 40, {USDT: "USDT"})
    assert not is_counterfeit("USDT", USDT, {USDT: "USDT"})
    assert not is_counterfeit("PEPE", "0x" + "e" * 40, {USDT: "USDT"})


# --- D2 / D3 ----------------------------------------------------------------------------------------
def test_d2_passthrough(ctx):
    rows = [(X, V, 5.0, 100, 1, False), (V, R, 4.5, 102, 1, False),          # V forwards 90 %: flagged
            (X, R, 5.0, 100, 2, False), (R, F, 1.0, 101, 3, False)]          # R forwards 1 of 9.5: not flagged
    found = d02_passthrough.detect(tx(rows), empty_tt(), empty_ap(), ctx)
    assert [f.wallet for f in found] == [V]


def test_d2_skips_labelled_exchange(ctx):
    ctx.labels = {V: [{"label": "CEX", "category": "exchange", "source": "t"}]}
    assert d02_passthrough.detect(tx([(X, V, 5.0, 100, 1, False), (V, R, 4.5, 102, 1, False)]), empty_tt(), empty_ap(), ctx) == []


def test_d3_hop_chain(ctx):
    rows = [(X, V, 10.0, 100, 1, False), (V, R, 9.5, 101, 1, False), (R, F, 9.0, 102, 1, False),
            (F, X, 1.0, 103, 1, False)]                                         # last hop keeps only 11 %: chain ends at F
    found = d03_hops.detect(tx(rows), empty_tt(), empty_ap(), ctx)
    assert len(found) == 1 and found[0].details["path"] == [X, V, R, F]
    assert d03_hops.two_hop_count(tx(rows), Context(chain="eth", cfg=ScamSettings(), apply_exclusions=False)) == 2


# --- D4 / D5 / D7 ----------------------------------------------------------------------------------
def many(n, tag):
    return [addr(f"{i:04x}", tag, "cafe") for i in range(n)]


def test_d4_collector_and_contract_share(ctx):
    senders = many(25, "5")
    rows = [(s, V, 0.1, 100, 1, False) for s in senders] + [(s, X, 0.0, 100, 1, True) for s in senders]
    found = d04_collector.detect(tx(rows), empty_tt(), empty_ap(), ctx)
    assert [f.wallet for f in found] == [V]                                     # X only receives contract calls


def test_d5_distributor(ctx):
    rows = [(V, r, 0.1, 100, i, False) for i, r in enumerate(many(21, "6"))] + [(X, r, 0.1, 100, 1, False) for r in many(5, "7")]
    assert [f.wallet for f in d05_distributor.detect(tx(rows), empty_tt(), empty_ap(), ctx)] == [V]


def test_d7_dust(ctx):
    rows = [(V, r, 0.00001, 100, i, False) for i, r in enumerate(many(12, "8"))] + [(X, R, 0.00001, 100, 1, False)]
    assert [f.wallet for f in d07_dust.detect(tx(rows), empty_tt(), empty_ap(), ctx)] == [V]


# --- D6 / D8 / D9 / D10 ------------------------------------------------------------------------------
def test_d6_new_wallet_big_money(ctx):
    rows = [(X, V, 20.0, 100, 7, False), (V, R, 19.0, 103, 0, False),        # V: nonce 0, forwards 95 % in 3 blocks
            (X, F, 20.0, 100, 8, False), (F, R, 19.0, 103, 4, False)]        # F is not new (nonce 4)
    assert [f.wallet for f in d06_new_wallet.detect(tx(rows), empty_tt(), empty_ap(), ctx)] == [V]


def test_d8_approval_to_wallet_then_drain(ctx):
    approvals = pd.DataFrame([{"block_number": 100, "tx_hash": "0xap", "token_address": USDT, "owner": V, "spender": F,
                               "is_unlimited": True, "spender_is_contract": 0},
                              {"block_number": 100, "tx_hash": "0xok", "token_address": USDT, "owner": V, "spender": X,
                               "is_unlimited": True, "spender_is_contract": 1}])
    drain_tx = tx([(F, USDT, 0.0, 105, 3, True)])
    t = tt([(V, F, 900.0, 105, USDT, "USDT")])
    t["tx_hash"] = drain_tx["tx_hash"]
    found = d08_approvals.detect(drain_tx, t, approvals, ctx)
    assert [(f.wallet, f.severity) for f in found] == [(F, "high")]


def test_d9_blacklist_direct_and_two_hop(ctx):
    ctx.labels = {X: [{"label": "TEST", "category": "sanctioned", "source": "t"}]}
    found = d09_blacklist.detect(tx([(V, X, 1.0, 100, 1, False), (R, V, 1.0, 101, 1, False)]), empty_tt(), empty_ap(), ctx)
    hops = {f.wallet: f.details.get("hops", 0) for f in found}
    assert hops == {X: 0, V: 1, R: 2}


def test_d10_same_first_funder(ctx):
    kids = many(4, "9")
    found = d10_linked.detect(tx([(X, k, 1.0, 100 + i, 1, False) for i, k in enumerate(kids)]), empty_tt(), empty_ap(), ctx)
    assert sorted({f.wallet for f in found if f.details["signal"] == "same_first_funder"}) == sorted(kids)


# --- risk -----------------------------------------------------------------------------------------------
def test_risk_combines_and_explains(ctx):
    from app.scam.detectors.base import Finding
    fs = [Finding("D1", V, 85, "high", "poison"), Finding("D1", V, 65, "medium", "weaker poison"),
          Finding("D7", V, 35, "low", "dust"), Finding("D4", X, 30, "low", "collector")]
    risk = {r["wallet"]: r for r in wallet_risk(fs, ScamSettings().risk_weights)}
    assert risk[V]["detectors_hit"] == ["D1", "D7"] and risk[V]["top_reasons"][0] == "poison"
    assert risk[V]["risk_score"] > risk[X]["risk_score"] and 0 <= risk[V]["risk_score"] <= 100

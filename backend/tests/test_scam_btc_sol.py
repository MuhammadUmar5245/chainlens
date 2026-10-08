"""Bitcoin and Solana support for the detectors (synthetic fixtures)."""

import pandas as pd

from app.scam.config import ScamSettings
from app.scam.detectors import d01_poisoning, d02_passthrough, d04_collector, d07_dust
from app.scam.detectors.base import Context, empty_ap, empty_tt, first_hashes, lookalike_key


def tx(rows):
    df = pd.DataFrame(rows, columns=["from_addr", "to_addr", "value", "block_number", "nonce", "is_contract_call"])
    df["tx_hash"] = [f"h{i}" for i in range(len(df))]
    df["block_time"] = pd.Timestamp("2026-10-07", tz="UTC")
    return df


def ctx(chain, family):
    return Context(chain=chain, cfg=ScamSettings().for_chain(chain), family=family)


def test_lookalike_key_skips_address_prefixes():
    assert lookalike_key("bc1qab12" + "x" * 30 + "wxyz", 4, 4) == "ab12|wxyz"       # bech32: skip bc1q
    assert lookalike_key("1Ab12" + "x" * 25 + "wXyZ", 4, 4) == "Ab12|wXyZ"           # legacy: skip the 1
    assert lookalike_key("9WzD" + "x" * 36 + "AWWM", 4, 4) == "9WzD|AWWM"            # Solana: no prefix
    assert lookalike_key("0x1234" + "0" * 32 + "5678", 4, 4) == "1234|5678"          # EVM unchanged


def test_chain_overrides():
    btc, sol, eth = ScamSettings().for_chain("btc"), ScamSettings().for_chain("sol"), ScamSettings().for_chain("eth")
    assert btc.scam_passthrough_min_in_eth == 1.0 and btc.scam_passthrough_max_hold_blocks == 6
    assert sol.scam_passthrough_min_in_eth == 20 and eth.scam_passthrough_max_hold_blocks == 0
    assert eth.scam_passthrough_min_in_eth == 1.0                                    # ETH keeps the requirement defaults
    assert btc.scam_poison_fake_max_eth == 0.00002 and btc.scam_fanin_min_senders == 20


def test_btc_poisoning_with_lookalike_bech32():
    V = "bc1q" + "v" * 34 + "vict"
    R = "bc1qab12" + "r" * 30 + "wxyz"
    F = "bc1qab12" + "f" * 30 + "wxyz"
    rows = [(V, R, 0.01, 100, 0, False), (F, V, 0.00001, 110, 0, False)]
    found = d01_poisoning.detect(tx(rows), empty_tt(), empty_ap(), ctx("btc", "utxo"))
    assert [f.wallet for f in found] == [F]
    assert found[0].severity == "medium"           # 10 blocks later and no nonce on Bitcoin: not "high"


def test_sol_poisoning_and_dust():
    V = "Vict" + "1" * 36 + "AAAA"
    R = "9WzD" + "2" * 36 + "AWWM"
    F = "9WzD" + "3" * 36 + "AWWM"
    rows = [(V, R, 5.0, 1000, 0, False), (F, V, 0.000001, 1001, 0, False)]
    found = d01_poisoning.detect(tx(rows), empty_tt(), empty_ap(), ctx("sol", "solana"))
    assert [(f.wallet, f.severity) for f in found] == [(F, "high")]   # within 1,500 slots


def test_btc_thresholds_apply():
    X, M, R = "bc1q" + "a" * 38, "bc1q" + "b" * 38, "bc1q" + "c" * 38
    fast = [(X, M, 2.0, 100, 0, False), (M, R, 1.9, 103, 0, False)]          # forwarded within 3 blocks: flagged
    slow = [(X, M, 2.0, 100, 0, False), (M, R, 1.9, 120, 0, False)]          # held 20 blocks: normal spending
    small = [(X, M, 0.2, 100, 0, False), (M, R, 0.19, 101, 0, False)]        # below 1 BTC
    c = ctx("btc", "utxo")
    assert [f.wallet for f in d02_passthrough.detect(tx(fast), empty_tt(), empty_ap(), c)] == [M]
    assert d02_passthrough.detect(tx(slow), empty_tt(), empty_ap(), c) == []
    assert d02_passthrough.detect(tx(small), empty_tt(), empty_ap(), c) == []


def test_solana_collector_not_dropped_for_program_calls():
    dest = "Dest" + "9" * 40
    rows = [(f"S{i:03d}" + "x" * 40, dest, 1.0, 100, 0, True) for i in range(25)]   # all program calls
    assert [f.wallet for f in d04_collector.detect(tx(rows), empty_tt(), empty_ap(), ctx("sol", "solana"))] == [dest]
    assert d04_collector.detect(tx(rows), empty_tt(), empty_ap(), ctx("eth", "evm")) == []   # EVM rule unchanged


def test_btc_dust_threshold():
    S = "bc1q" + "s" * 38
    rows = [(S, f"bc1q{i:03d}" + "r" * 35, 0.00001, 100, 0, False) for i in range(12)]
    assert [f.wallet for f in d07_dust.detect(tx(rows), empty_tt(), empty_ap(), ctx("btc", "utxo"))] == [S]


def test_first_hashes_keeps_order():
    df = tx([("a", "x", 1, 1, 0, False), ("b", "x", 1, 2, 0, False), ("a", "y", 1, 3, 0, False)])
    assert first_hashes(df, "from_addr", 5) == {"a": ["h0", "h2"], "b": ["h1"]}


def test_skipped_detectors_are_declared():
    from app.scam.runner import SKIPPED_FOR
    assert set(SKIPPED_FOR["utxo"]) == {"D6", "D8"} and set(SKIPPED_FOR["solana"]) == {"D6", "D8"}

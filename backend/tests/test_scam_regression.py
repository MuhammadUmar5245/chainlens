"""Requirements 9.2: raw definitions on the real sample must reproduce the baseline numbers."""

import pandas as pd
import pytest

from conftest import SAMPLE_XLSX


@pytest.fixture(scope="module")
def sample_tx():
    df = pd.read_excel(SAMPLE_XLSX, sheet_name="transactions", dtype={"tx_hash": str, "from_addr": str, "to_addr": str})
    df["from_addr"] = df["from_addr"].str.lower()
    df["to_addr"] = df["to_addr"].str.lower()
    df["is_contract_call"] = df["is_contract_call"].astype(bool)
    return df.rename(columns={"value_eth": "value"})


@pytest.fixture(scope="module")
def metrics(sample_tx):
    from app.scam.config import ScamSettings
    from app.scam.detectors.base import Context
    from app.scam.metrics import raw_metrics
    return raw_metrics(sample_tx, Context(chain="eth", cfg=ScamSettings()))


EXPECTED = {
    "transactions": 14_041,
    "blocks": 50,
    "unique_addresses": 10_579,
    "lookalike_groups": 121,
    "d1_matches": 41,
    "d1_victims": 30,
    "d1_fake_senders": 37,
    "d1_median_delay_blocks": 11.0,
    "d2_passthrough": 101,
    "d3_two_hop_chains": 131,
    "d4_collectors": 40,
    "d5_distributors": 19,
    "senders_nonce0": 1_072,
    "dust_transactions": 1_369,
    "zero_value_contract_calls": 8_098,
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_raw_metric(metrics, name):
    assert metrics[name] == EXPECTED[name]


def test_fake_senders_mostly_nonce_zero(metrics):
    assert round(metrics["d1_fake_nonce0_share"], 1) == 0.8          # 29 of 37 = 0.78, "80%" in the requirements


def test_detectors_are_deterministic(sample_tx):
    from app.scam.config import ScamSettings
    from app.scam.detectors import DETECTORS
    from app.scam.detectors.base import Context, empty_ap, empty_tt

    def run():
        ctx = Context(chain="eth", cfg=ScamSettings())
        out = []
        for key, (_, fn) in DETECTORS.items():
            found = fn(sample_tx, empty_tt(), empty_ap(), ctx)
            ctx.prior[key] = found
            out += [(f.detector, f.wallet, f.score, tuple(f.tx_hashes)) for f in found]
        return out

    assert run() == run()


def test_sample_runs_fast(sample_tx):
    import time
    from app.scam.config import ScamSettings
    from app.scam.detectors import DETECTORS
    from app.scam.detectors.base import Context, empty_ap, empty_tt

    ctx = Context(chain="eth", cfg=ScamSettings())
    t0 = time.time()
    for key, (_, fn) in DETECTORS.items():
        ctx.prior[key] = fn(sample_tx, empty_tt(), empty_ap(), ctx)
    assert time.time() - t0 < 10

"""Non-regression: the existing analytics output for the sample must stay byte-for-byte identical.

The snapshots were produced from the baseline commit (before the scam tracing feature).
Regenerate only on purpose:  UPDATE_SNAPSHOTS=1 pytest tests/test_baseline_analytics.py
"""

import os

import pytest

from conftest import SAMPLE_XLSX, SNAPSHOTS, requires_db

QUERIES = {
    "wallet_features": "SELECT * FROM wallet_features WHERE run_id = 1 ORDER BY chain, wallet",
    "run_series": "SELECT run_id, chain, minute, txs, blocks, value, contract_calls, "
                  "round(quantileTDigestMerge(0.5)(gas), 6) AS median_gas FROM run_series WHERE run_id = 1 "
                  "GROUP BY run_id, chain, minute, txs, blocks, value, contract_calls ORDER BY chain, minute",
    "wallet_pairs": "SELECT * FROM wallet_pairs WHERE run_id = 1 ORDER BY chain, a, b",
}


@pytest.fixture(scope="module")
def analysed():
    from app.analytics import engine
    from sample_db import SAMPLE_DATASET, SAMPLE_RUN, reset_and_load

    loaded = reset_and_load(SAMPLE_XLSX)
    result = engine.run(engine.Scope(run_id=SAMPLE_RUN, chains=["eth"], dataset_id=SAMPLE_DATASET),
                        whale={"eth": 100.0}, k=4, anomaly_z=3.0)
    return loaded, result


@requires_db
def test_sample_totals(analysed):
    loaded, result = analysed
    assert loaded == 14_041
    assert result == {"wallets": 10_579, "transactions": 14_041}


@requires_db
@pytest.mark.parametrize("name", sorted(QUERIES))
def test_snapshot(analysed, name):
    from app.db.clickhouse import new_client

    body = new_client().raw_query(QUERIES[name], fmt="CSVWithNames")
    path = SNAPSHOTS / f"{name}.csv"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1" or not path.exists():
        path.write_bytes(body)
        pytest.skip(f"snapshot written: {path.name}")
    assert body == path.read_bytes(), f"{name} output changed compared with the baseline snapshot"


@requires_db
def test_anomaly_count(analysed):
    from app.db.clickhouse import new_client

    n = int(new_client().command("SELECT countIf(is_anomaly) FROM wallet_features WHERE run_id = 1"))
    assert n == 153

"""Phase 3: wallet trace works for addresses in the sample (test ClickHouse database)."""

import random

import pytest

from conftest import SAMPLE_XLSX, requires_db

KEYS = {"profile", "counterparties", "first_funder", "exit_points", "graph", "timeline", "findings", "truncated", "note"}


@pytest.fixture(scope="module")
def tracer():
    from app.db.clickhouse import new_client
    from app.scam.trace import Tracer
    from sample_db import reset_and_load

    reset_and_load(SAMPLE_XLSX)
    for t in ("token_transfers", "token_approvals", "risk_findings", "wallet_risk"):
        new_client().command(f"TRUNCATE TABLE IF EXISTS {t}")
    return Tracer("eth")


@requires_db
def test_trace_random_sample_addresses(tracer):
    from app.db.clickhouse import new_client

    addrs = [r[0] for r in new_client().query("SELECT DISTINCT from_addr FROM transactions ORDER BY from_addr").result_rows]
    for a in random.Random(42).sample(addrs, 40):
        t = tracer.trace(a, depth=2)
        assert KEYS <= t.keys()
        assert t["graph"]["nodes"][0]["id"] == a and t["graph"]["nodes"][0]["level"] == 0
        assert len(t["graph"]["nodes"]) <= 500
        assert t["profile"]["transactions"] >= 1
        assert "not proof" in t["note"]


@requires_db
def test_trace_limits_and_direction(tracer):
    hub = "0x687c802162e79ad95309df8eedcb8e814c7f459e"          # 1,345 distinct senders in the sample
    t = tracer.trace(hub, depth=2, direction="in")
    assert t["truncated"] and len(t["graph"]["nodes"]) == 500
    assert all(e["target"] == hub or e["source"] != hub for e in t["graph"]["edges"])
    with pytest.raises(ValueError):
        tracer.trace(hub, direction="sideways")

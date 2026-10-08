"""Non-regression: existing read endpoints keep answering with the same shape."""

import pytest

from conftest import requires_db


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@requires_db
def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert {"postgres", "clickhouse", "nownodes_key", "history_days"} <= r.json().keys()


@requires_db
def test_chains(client):
    r = client.get("/api/v1/chains")
    assert r.status_code == 200
    assert [c["key"] for c in r.json()] == ["btc", "eth", "ethw", "etc", "sol"]


@requires_db
@pytest.mark.parametrize("path", ["/api/v1/datasets", "/api/v1/jobs", "/api/v1/analytics/runs"])
def test_lists(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

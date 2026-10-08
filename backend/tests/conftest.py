"""Test setup. Database tests use a separate ClickHouse database (chainlens_test) so real data is never touched.

Run everything inside the stack:
    docker compose run --rm -v "$PWD/backend:/app" api sh -c "pip install -q -r requirements-dev.txt && pytest -q"
"""

import os
import sys
from pathlib import Path

os.environ["CLICKHOUSE_DATABASE"] = "chainlens_test"      # must be set before app.config is imported
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOTS = Path(__file__).parent / "snapshots"
SAMPLE_XLSX = FIXTURES / "nownodes_data.xlsx"


def clickhouse_available() -> bool:
    try:
        from app.db.clickhouse import new_client
        new_client(database="default").command("SELECT 1")
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(not clickhouse_available(), reason="ClickHouse not reachable (run inside docker compose)")

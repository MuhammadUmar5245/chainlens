from pathlib import Path

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from app.config import settings

SCHEMA_DIR = Path(__file__).parent / "clickhouse_schema"

TX_COLUMNS = ["chain", "dataset_id", "source", "block_number", "block_time", "tx_hash", "from_addr", "to_addr",
              "value_native", "gas_limit", "gas_price_gwei", "is_contract_call", "nonce"]

_client: Client | None = None


def new_client(database: str | None = None) -> Client:
    # no session id, so one client can serve concurrent requests
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host, port=settings.clickhouse_port,
        username=settings.clickhouse_user, password=settings.clickhouse_password,
        database=database if database is not None else settings.clickhouse_database,
        autogenerate_session_id=False,
    )


def get_ch() -> Client:
    global _client
    if _client is None:
        _client = new_client()
    return _client


def apply_schema() -> None:
    admin = new_client(database="default")
    admin.command(f"CREATE DATABASE IF NOT EXISTS {settings.clickhouse_database}")
    ch = new_client()
    for path in sorted(SCHEMA_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8").replace("{{HISTORY_DAYS}}", str(int(settings.history_days)))
        for statement in _split_sql(sql):
            ch.command(statement)


def _split_sql(sql: str) -> list[str]:
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]

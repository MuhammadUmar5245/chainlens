"""Loads the sample export into the test ClickHouse database with the project's own upload loader."""

from app.db.clickhouse import apply_schema, new_client
from app.ingest import upload as dump

SAMPLE_DATASET = 1
SAMPLE_RUN = 1
TABLES = ["transactions", "wallet_features", "run_series", "wallet_pairs"]


def reset_and_load(xlsx_path) -> int:
    apply_schema()
    ch = new_client()
    for t in TABLES:
        ch.command(f"TRUNCATE TABLE IF EXISTS {t}")
    columns, _ = dump.preview(str(xlsx_path), "xlsx")
    opts = dump.suggest_mapping(columns) | {"chain": "eth", "decimals": 18}
    loaded = 0
    for chunk in dump.read_chunks(str(xlsx_path), "xlsx"):
        clean, bad = dump.normalise(chunk, opts, SAMPLE_DATASET, {"eth"})
        assert len(bad) == 0, f"fixture rows rejected: {bad['reject_reason'].value_counts().to_dict()}"
        ch.insert_df("transactions", clean)
        loaded += len(clean)
    return loaded

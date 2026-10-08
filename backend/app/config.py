from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or .env in development)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # external APIs - keys live only on the server, never in the React app
    nownodes_api_key: str = ""
    nownodes_auth_mode: str = "header"          # "header" -> api-key header; "url" -> <rpc_url>/<key>

    # databases
    postgres_url: str = "postgresql+psycopg://chainlens:chainlens@localhost:5432/chainlens"
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "chainlens"
    clickhouse_password: str = "chainlens"
    clickhouse_database: str = "chainlens"
    redis_url: str = "redis://localhost:6379/0"

    # storage + limits
    upload_dir: str = "/data/uploads"
    max_upload_gb: float = 5.0
    history_days: int = 30                      # API data older than this is removed automatically (ClickHouse TTL)
    cors_origins: str = "http://localhost:5173"

    # ingestion
    fetch_chunk_blocks: int = 1_000             # blocks per checkpoint
    insert_batch_rows: int = 10_000             # rows per ClickHouse insert
    sync_max_blocks_per_tick: int = 2_000       # live sync: max blocks fetched per chain per minute

    # analytics defaults (copied from the prototype script)
    kmeans_k: int = 4
    anomaly_z: float = 3.0
    cluster_sample_rows: int = 1_000_000


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

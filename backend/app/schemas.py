from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ChainOut(ORM):
    key: str
    name: str
    family: str
    fee_unit: str
    fetch_latency_s: float
    rpc_url: str
    native_symbol: str
    decimals: int
    block_time_s: float
    whale_threshold: float
    rate_limit_rps: float
    workers: int
    explorer_url: str
    enabled: bool
    autosync: bool
    sort_order: int


class ChainUpdate(BaseModel):
    rpc_url: str | None = None
    explorer_url: str | None = Field(None, description="Link template; {address} is replaced by the wallet address")
    whale_threshold: float | None = Field(None, gt=0)
    rate_limit_rps: float | None = Field(None, gt=0, le=1000)
    workers: int | None = Field(None, ge=1, le=64)
    enabled: bool | None = None
    autosync: bool | None = None


class DatasetOut(ORM):
    id: int
    name: str
    source_type: str
    chains: list[str]
    params: dict
    status: str
    row_count: int
    first_block: int | None
    last_block: int | None
    time_from: datetime | None
    time_to: datetime | None
    created_at: datetime


class FetchRequest(BaseModel):
    chain: str
    mode: Literal["last_blocks", "last_hours", "range"] = "last_blocks"
    blocks: int | None = Field(None, ge=1, le=5_000_000)
    hours: int | None = Field(None, ge=1)
    from_block: int | None = Field(None, ge=0)
    to_block: int | None = Field(None, ge=0)
    name: str | None = None
    run_analytics: bool = True


class UploadOut(ORM):
    id: str
    filename: str
    size_bytes: int
    format: str
    columns: list[str]
    preview: list[dict]
    suggested: dict = {}
    estimated_rows: int = 0


class FromUploadRequest(BaseModel):
    upload_id: str
    name: str | None = None
    chain: str | None = None                 # one chain for the whole file ...
    mapping: dict[str, str]                  # ... or map a "chain" column here
    value_unit: Literal["native", "wei"] = "native"
    gas_unit: Literal["gwei", "wei"] = "gwei"
    run_analytics: bool = True


class RunRequest(BaseModel):
    chains: list[str] = Field(min_length=1)
    dataset_id: int | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None


class RunOut(ORM):
    id: int
    dataset_id: int | None
    chains: list[str]
    time_from: datetime | None
    time_to: datetime | None
    settings: dict
    status: str
    transactions: int
    wallets: int
    created_at: datetime
    finished_at: datetime | None


class JobOut(ORM):
    id: int
    type: str
    status: str
    dataset_id: int | None
    run_id: int | None
    params: dict
    progress: float
    message: str
    detail: dict
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

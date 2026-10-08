"""PostgreSQL models: the application's own records (chains, datasets, jobs, runs, uploads).
Transactions and analytics results live in ClickHouse (see clickhouse_schema/)."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base


class Chain(Base):
    __tablename__ = "chains"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    family: Mapped[str] = mapped_column(String(16), default="evm")            # evm | utxo | solana
    fee_unit: Mapped[str] = mapped_column(String(16), default="gwei")         # unit of the fee column for this chain
    fetch_latency_s: Mapped[float] = mapped_column(Float, default=0.5)        # typical seconds per block request
    rpc_url: Mapped[str] = mapped_column(String(255))
    native_symbol: Mapped[str] = mapped_column(String(16))
    decimals: Mapped[int] = mapped_column(Integer, default=18)
    block_time_s: Mapped[float] = mapped_column(Float)
    whale_threshold: Mapped[float] = mapped_column(Float)
    rate_limit_rps: Mapped[float] = mapped_column(Float, default=10.0)
    workers: Mapped[int] = mapped_column(Integer, default=6)
    explorer_url: Mapped[str] = mapped_column(String(255), default="")       # template with {address}
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    autosync: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(16))              # api | upload | sync
    chains: Mapped[list] = mapped_column(JSONB, default=list)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | loading | ready | failed
    row_count: Mapped[int] = mapped_column(BigInteger, default=0)
    first_block: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_block: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    time_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalyticsRun(Base):
    __tablename__ = "analytics_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True)
    chains: Mapped[list] = mapped_column(JSONB, default=list)
    time_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")   # queued | running | succeeded | failed
    transactions: Mapped[int] = mapped_column(BigInteger, default=0)
    wallets: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(32))                       # fetch | load_upload | analytics
    status: Mapped[str] = mapped_column(String(16), default="queued")   # queued | running | succeeded | failed | cancelling | cancelled
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("analytics_runs.id", ondelete="SET NULL"), nullable=True)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)           # checkpoints, failed blocks, reject counts
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    path: Mapped[str] = mapped_column(String(500))
    format: Mapped[str] = mapped_column(String(16))
    columns: Mapped[list] = mapped_column(JSONB, default=list)
    preview: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

"""initial tables: chains, datasets, analytics_runs, jobs, uploads

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "chains",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("rpc_url", sa.String(255), nullable=False),
        sa.Column("native_symbol", sa.String(16), nullable=False),
        sa.Column("decimals", sa.Integer, nullable=False, server_default="18"),
        sa.Column("block_time_s", sa.Float, nullable=False),
        sa.Column("whale_threshold", sa.Float, nullable=False),
        sa.Column("rate_limit_rps", sa.Float, nullable=False, server_default="10"),
        sa.Column("workers", sa.Integer, nullable=False, server_default="6"),
        sa.Column("explorer_url", sa.String(255), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("autosync", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "datasets",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("chains", JSONB, nullable=False, server_default="[]"),
        sa.Column("params", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("row_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("first_block", sa.BigInteger),
        sa.Column("last_block", sa.BigInteger),
        sa.Column("time_from", TS),
        sa.Column("time_to", TS),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "analytics_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("dataset_id", sa.BigInteger, sa.ForeignKey("datasets.id", ondelete="SET NULL")),
        sa.Column("chains", JSONB, nullable=False, server_default="[]"),
        sa.Column("time_from", TS),
        sa.Column("time_to", TS),
        sa.Column("settings", JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("transactions", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("wallets", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("dataset_id", sa.BigInteger, sa.ForeignKey("datasets.id", ondelete="SET NULL")),
        sa.Column("run_id", sa.BigInteger, sa.ForeignKey("analytics_runs.id", ondelete="SET NULL")),
        sa.Column("params", JSONB, nullable=False, server_default="{}"),
        sa.Column("progress", sa.Float, nullable=False, server_default="0"),
        sa.Column("message", sa.Text, nullable=False, server_default=""),
        sa.Column("detail", JSONB, nullable=False, server_default="{}"),
        sa.Column("error", sa.Text),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
    )
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    op.create_table(
        "uploads",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("path", sa.String(500), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("columns", JSONB, nullable=False, server_default="[]"),
        sa.Column("preview", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("uploads")
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("analytics_runs")
    op.drop_table("datasets")
    op.drop_table("chains")

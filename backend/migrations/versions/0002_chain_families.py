"""chain families: add family, fee_unit, fetch_latency_s; switch to BTC, ETH, ETHW, ETC, SOL

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chains", sa.Column("family", sa.String(16), nullable=False, server_default="evm"))
    op.add_column("chains", sa.Column("fee_unit", sa.String(16), nullable=False, server_default="gwei"))
    op.add_column("chains", sa.Column("fetch_latency_s", sa.Float, nullable=False, server_default="0.5"))
    # the chain set changed: BNB, Polygon, Arbitrum and Base are replaced (bootstrap seeds the new ones)
    op.execute("DELETE FROM chains WHERE key IN ('bsc', 'polygon', 'arbitrum', 'base')")
    # explorer links are now templates
    op.execute("UPDATE chains SET explorer_url = 'https://etherscan.io/address/{address}' WHERE key = 'eth'")


def downgrade() -> None:
    op.drop_column("chains", "fetch_latency_s")
    op.drop_column("chains", "fee_unit")
    op.drop_column("chains", "family")

"""scam tracing: address_labels, tokens, address_code (CREATE only) + built-in seeds

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)

# Well-known token contracts only. Exchange / scam / sanctions lists are supplied by the user (CSV import).
BUILTIN_LABELS = [
    ("eth", "0xdac17f958d2ee523a2206206994597c13d831ec7", "Tether USD (USDT)", "token"),
    ("eth", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "USD Coin (USDC)", "token"),
    ("eth", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "Wrapped Ether (WETH)", "token"),
    ("eth", "0x6b175474e89094c44da98b954eedeac495271d0f", "Dai Stablecoin (DAI)", "token"),
    ("btc", "bc1pfeessrawgf", "Pay-to-anchor output (fee bumping, not a wallet)", "other"),
]
BUILTIN_TOKENS = [
    ("eth", "0xdac17f958d2ee523a2206206994597c13d831ec7", "USDT", 6),
    ("eth", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "USDC", 6),
    ("eth", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "WETH", 18),
    ("eth", "0x6b175474e89094c44da98b954eedeac495271d0f", "DAI", 18),
]


def upgrade() -> None:
    labels = op.create_table(
        "address_labels",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("chain", sa.String(32), nullable=False),
        sa.Column("address", sa.String(128), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("added_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("chain", "address", "source", name="uq_address_labels_chain_address_source"),
    )
    op.create_index("ix_address_labels_address", "address_labels", ["chain", "address"])
    tokens = op.create_table(
        "tokens",
        sa.Column("chain", sa.String(32), primary_key=True),
        sa.Column("address", sa.String(128), primary_key=True),
        sa.Column("symbol", sa.String(64), nullable=False, server_default=""),
        sa.Column("decimals", sa.Integer, nullable=False, server_default="18"),
        sa.Column("source", sa.String(32), nullable=False, server_default="rpc"),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "address_code",
        sa.Column("chain", sa.String(32), primary_key=True),
        sa.Column("address", sa.String(128), primary_key=True),
        sa.Column("is_contract", sa.Boolean, nullable=False),
        sa.Column("checked_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.bulk_insert(labels, [dict(chain=c, address=a, label=lab, category=cat, source="builtin")
                            for c, a, lab, cat in BUILTIN_LABELS])
    op.bulk_insert(tokens, [dict(chain=c, address=a, symbol=s, decimals=d, source="builtin")
                            for c, a, s, d in BUILTIN_TOKENS])


def downgrade() -> None:
    op.drop_table("address_code")
    op.drop_table("tokens")
    op.drop_index("ix_address_labels_address", table_name="address_labels")
    op.drop_table("address_labels")

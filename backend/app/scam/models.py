"""PostgreSQL tables for scam tracing (small, editable reference data). Created by migration 0003."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.postgres import Base

CATEGORIES = ("exchange", "bridge", "mixer", "sanctioned", "scam_reported", "defi", "token", "other")


class AddressLabel(Base):
    __tablename__ = "address_labels"
    __table_args__ = (UniqueConstraint("chain", "address", "source", name="uq_address_labels_chain_address_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chain: Mapped[str] = mapped_column(String(32))
    address: Mapped[str] = mapped_column(String(128))
    label: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(100))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Token(Base):
    __tablename__ = "tokens"

    chain: Mapped[str] = mapped_column(String(32), primary_key=True)
    address: Mapped[str] = mapped_column(String(128), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), default="")
    decimals: Mapped[int] = mapped_column(Integer, default=18)
    source: Mapped[str] = mapped_column(String(32), default="rpc")      # builtin | rpc | guess
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AddressCode(Base):
    """Whether an address is a contract (eth_getCode), checked once and cached."""
    __tablename__ = "address_code"

    chain: Mapped[str] = mapped_column(String(32), primary_key=True)
    address: Mapped[str] = mapped_column(String(128), primary_key=True)
    is_contract: Mapped[bool] = mapped_column(Boolean)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

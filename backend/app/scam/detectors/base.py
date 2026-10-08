"""Shared types for detectors. Detectors are pure: (data, context) -> list[Finding]. No database access.

Input frames (column names):
  tx  : block_number, block_time, tx_hash, from_addr, to_addr, value, is_contract_call (bool), nonce
  tt  : block_number, block_time, tx_hash, log_index, token_address, from_addr, to_addr, amount, token_symbol
  ap  : block_number, tx_hash, token_address, owner, spender, is_unlimited (bool), spender_is_contract (-1/0/1)
"""

import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from app.scam.config import ScamSettings

EXIT_CATEGORIES = {"exchange", "bridge", "mixer"}
SERVICE_CATEGORIES = {"exchange", "bridge", "token", "defi"}          # excluded from mule / collector style detectors
BLACKLIST_CATEGORIES = {"sanctioned", "scam_reported", "mixer"}
NOT_WALLETS = {"", "contract_creation", "coinbase"}


@dataclass
class Finding:
    detector: str
    wallet: str
    score: int
    severity: str
    reason: str
    related: list[str] = field(default_factory=list)
    tx_hashes: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class Context:
    chain: str
    cfg: ScamSettings
    family: str = "evm"                                                # evm | utxo | solana
    labels: dict[str, list[dict]] = field(default_factory=dict)      # address -> [{label, category, source}]
    contracts: set[str] = field(default_factory=set)                   # known contract addresses
    known_tokens: dict[str, str] = field(default_factory=dict)         # real token address -> symbol (USDT, USDC, ...)
    apply_exclusions: bool = True                                      # False = raw definitions (regression metrics)
    prior: dict[str, list[Finding]] = field(default_factory=dict)      # findings of detectors that ran earlier

    def categories(self, address: str) -> set[str]:
        return {l["category"] for l in self.labels.get(address, [])}

    def is_service(self, address: str) -> bool:
        """Exchange, bridge, token or DeFi label, or a known contract: not a normal wallet."""
        if not self.apply_exclusions:
            return False
        return address in self.contracts or bool(self.categories(address) & SERVICE_CATEGORIES)

    def label_text(self, address: str) -> str:
        return "; ".join(f"{l['label']} ({l['category']}, {l['source']})" for l in self.labels.get(address, []))


def severity_for(score: int) -> str:
    return "high" if score >= 70 else "medium" if score >= 40 else "low"


def short(a: str) -> str:
    return f"{a[:8]}…{a[-6:]}" if len(a) > 16 else a


def is_hex_address(a: str) -> bool:
    return isinstance(a, str) and len(a) == 42 and a.startswith("0x")


def address_body_start(a: str) -> int:
    """Where the random part of an address starts: after 0x (EVM), bc1q/bc1p/tb1q (Bitcoin bech32),
    1/3 (Bitcoin legacy); Solana base58 addresses have no prefix."""
    if a.startswith("0x"):
        return 2
    if a[:3].lower() in ("bc1", "tb1"):
        return 4
    if a[:1] in ("1", "3") and 25 <= len(a) <= 35:
        return 1
    return 0


def is_wallet_address(a: str) -> bool:
    return isinstance(a, str) and a not in NOT_WALLETS and len(a) >= 25


def lookalike_parts(a: str, prefix: int, suffix: int) -> tuple[str, str]:
    start = address_body_start(a)
    return a[start:start + prefix], a[-suffix:]


def lookalike_key(a: str, prefix: int, suffix: int) -> str:
    head, tail = lookalike_parts(a, prefix, suffix)
    return head + "|" + tail


def first_hashes(df: pd.DataFrame, by: str, n: int = 10) -> dict[str, list[str]]:
    """address -> its first n tx hashes, in one pass (instead of filtering the frame per wallet)."""
    if df.empty:
        return {}
    return df.groupby(by, sort=False).head(n).groupby(by)["tx_hash"].agg(list).to_dict()


# --- counterfeit token symbols (e.g. "U⁯S⁯DΤ" pretending to be USDT) ---------------------------------
CONFUSABLES = str.maketrans({
    "Τ": "T", "Ⲧ": "T", "Т": "T", "τ": "T", "ꓔ": "T", "Ꭲ": "T",
    "Ս": "U", "ꓴ": "U", "Ü": "U", "υ": "U", "ս": "U",
    "Ѕ": "S", "Տ": "S", "ꓢ": "S", "ѕ": "S", "Ꮪ": "S",
    "Ꭰ": "D", "ꓓ": "D", "Ⅾ": "D", "ⅾ": "D",
    "С": "C", "Ϲ": "C", "ꓚ": "C", "с": "C", "Ⅽ": "C",
    "Е": "E", "Ε": "E", "ꓰ": "E", "Н": "H", "Η": "H", "ꓧ": "H",
    "О": "O", "Ο": "O", "ο": "O", "о": "O", "Α": "A", "А": "A", "Ꭺ": "A",
    "Ι": "I", "І": "I", "Ꮃ": "W", "Ԝ": "W", "Β": "B", "В": "B", "Ꮋ": "H",
})
KNOWN_SYMBOLS = {"USDT", "USDC", "ETH", "WETH", "DAI", "BUSD", "TUSD", "USDE", "PYUSD"}


def normalise_symbol(symbol: str) -> str:
    s = unicodedata.normalize("NFKC", symbol or "").translate(CONFUSABLES)
    return "".join(ch for ch in s if ch.isascii() and ch.isalnum()).upper()


def is_counterfeit(symbol: str, token_address: str, known_tokens: dict[str, str]) -> bool:
    """A token whose symbol reads as a well-known one (after removing hidden characters and look-alike letters)
    but whose contract is not the real one, e.g. "U⁯S⁯DΤ" that is not the real USDT contract."""
    if token_address in known_tokens:
        return False
    imitated = KNOWN_SYMBOLS | {s.upper() for s in known_tokens.values()}
    return normalise_symbol(symbol) in imitated


def empty_tx() -> pd.DataFrame:
    return pd.DataFrame(columns=["block_number", "block_time", "tx_hash", "from_addr", "to_addr", "value", "is_contract_call", "nonce"])


def empty_tt() -> pd.DataFrame:
    return pd.DataFrame(columns=["block_number", "block_time", "tx_hash", "log_index", "token_address", "from_addr",
                                 "to_addr", "amount", "token_symbol"])


def empty_ap() -> pd.DataFrame:
    return pd.DataFrame(columns=["block_number", "tx_hash", "token_address", "owner", "spender", "is_unlimited", "spender_is_contract"])

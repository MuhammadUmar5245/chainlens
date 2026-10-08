"""The five supported chains. These are the defaults written on first start;
after that the values live in the `chains` table and are edited from the Settings screen."""

from sqlalchemy.orm import Session

from app.db.models import Chain

# Whale thresholds are in each chain's own coin and are rough starting points (edit them in Settings).
# fetch_latency_s is the measured time for one block request on NOWNodes (7 Oct 2026); it drives the time estimates.
DEFAULT_CHAINS = [
    dict(key="btc", name="Bitcoin", family="utxo", rpc_url="https://btc.nownodes.io", native_symbol="BTC", decimals=8,
         fee_unit="sat/vB", block_time_s=600.0, whale_threshold=50.0, rate_limit_rps=10.0, workers=4,
         fetch_latency_s=75.0, explorer_url="https://mempool.space/address/{address}", sort_order=1),
    dict(key="eth", name="Ethereum", family="evm", rpc_url="https://eth.nownodes.io", native_symbol="ETH", decimals=18,
         fee_unit="gwei", block_time_s=12.0, whale_threshold=100.0, rate_limit_rps=10.0, workers=6,
         fetch_latency_s=0.5, explorer_url="https://etherscan.io/address/{address}", sort_order=2),
    dict(key="ethw", name="EthereumPoW", family="evm", rpc_url="https://ethw.nownodes.io", native_symbol="ETHW", decimals=18,
         fee_unit="gwei", block_time_s=13.0, whale_threshold=100_000.0, rate_limit_rps=10.0, workers=6,
         fetch_latency_s=0.5, explorer_url="", sort_order=3),
    dict(key="etc", name="Ethereum Classic", family="evm", rpc_url="https://etc.nownodes.io", native_symbol="ETC", decimals=18,
         fee_unit="gwei", block_time_s=13.0, whale_threshold=10_000.0, rate_limit_rps=10.0, workers=6,
         fetch_latency_s=0.5, explorer_url="https://etc.blockscout.com/address/{address}", sort_order=4),
    dict(key="sol", name="Solana", family="solana", rpc_url="https://sol.nownodes.io", native_symbol="SOL", decimals=9,
         fee_unit="lamports", block_time_s=0.4, whale_threshold=5_000.0, rate_limit_rps=10.0, workers=6,
         fetch_latency_s=35.0, explorer_url="https://solscan.io/account/{address}", sort_order=5),
]


def seed_chains(db: Session) -> None:
    """Add missing default chains and fill the family/fee fields on existing ones; user-edited values are kept."""
    existing = {c.key: c for c in db.query(Chain).all()}
    for row in DEFAULT_CHAINS:
        chain = existing.get(row["key"])
        if chain is None:
            db.add(Chain(**row))
        else:
            for field in ("family", "fee_unit", "fetch_latency_s", "sort_order", "name", "native_symbol", "decimals"):
                setattr(chain, field, row[field])
            if "{address}" not in (chain.explorer_url or ""):
                chain.explorer_url = row["explorer_url"]
    db.commit()

from app.ingest.base import Adapter
from app.ingest.btc import BtcAdapter
from app.ingest.evm import EvmAdapter
from app.ingest.solana import SolanaAdapter

FAMILIES: dict[str, type[Adapter]] = {"evm": EvmAdapter, "utxo": BtcAdapter, "solana": SolanaAdapter}


def get_adapter(chain, api_key: str, auth_mode: str) -> Adapter:
    try:
        cls = FAMILIES[chain.family]
    except KeyError:
        raise ValueError(f"no adapter for chain family '{chain.family}'") from None
    return cls(chain, api_key, auth_mode)

"""EVM chains (Ethereum, EthereumPoW, Ethereum Classic): one row per transaction."""

from datetime import datetime, timezone

from app.ingest.base import Adapter


def _h(x, default=0):
    return int(x, 16) if x else default


class EvmAdapter(Adapter):
    chunk_blocks = 1000
    timeout = 30.0

    def latest_height(self) -> int:
        return _h(self.client.rpc("eth_blockNumber"))

    def time_of(self, height: int) -> int:
        return _h(self.client.rpc("eth_getBlockByNumber", [hex(height), False])["timestamp"])

    def height_at_time(self, ts: int, tip: int) -> int:
        return self.binary_search_time(ts, tip)

    def block_rows(self, height: int, dataset_id: int, source: str) -> list[tuple] | None:
        block = self.client.rpc("eth_getBlockByNumber", [hex(height), True])
        if not block:
            return None
        return block_to_rows(block, self.chain.key, dataset_id, self.chain.decimals, source)


def block_to_rows(block: dict, chain: str, dataset_id: int, decimals: int, source: str = "api") -> list[tuple]:
    """One tuple per transaction, in the order of app.db.clickhouse.TX_COLUMNS."""
    bn, ts = _h(block["number"]), _h(block["timestamp"])
    bt = datetime.fromtimestamp(ts, tz=timezone.utc)
    scale = 10 ** decimals
    rows = []
    for tx in block.get("transactions", []):
        rows.append((
            chain, dataset_id, source, bn, bt, tx["hash"].lower(),
            (tx.get("from") or "").lower(),
            (tx.get("to") or "contract_creation").lower(),
            _h(tx.get("value")) / scale,
            _h(tx.get("gas")),
            _h(tx.get("gasPrice") or tx.get("maxFeePerGas")) / 1e9,     # fee price in gwei
            1 if len(tx.get("input") or "0x") > 2 else 0,
            _h(tx.get("nonce")),
        ))
    return rows

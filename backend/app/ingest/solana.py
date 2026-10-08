"""Solana: one row per non-vote transaction.

Solana has no from/to fields; mapping used here:
  * sender   = fee payer (first account key)
  * receiver = the other account whose SOL balance rose the most; if none rose, the first program called
  * value    = that SOL increase (in SOL); 0 when no SOL moved
  * contract/program call = the transaction invokes any program other than System and Compute Budget
  * fee column holds the fee in lamports; gas_limit holds compute units consumed
Vote transactions (about half of all transactions) are skipped. Heights are slots; skipped slots have no block.
"""

from datetime import datetime, timezone

from app.ingest.base import Adapter, RpcError

VOTE = "Vote111111111111111111111111111111111111111"
SYSTEM = "11111111111111111111111111111111"
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
SKIPPED = (-32007, -32009, -32004)    # slot skipped / missing in long-term storage / block not available


class SolanaAdapter(Adapter):
    chunk_blocks = 25
    timeout = 180.0

    def latest_height(self) -> int:
        return int(self.client.rpc("getSlot", [{"commitment": "finalized"}]))

    def time_of(self, height: int) -> int:
        for s in range(height, height + 50):           # walk forward past skipped slots
            try:
                t = self.client.rpc("getBlockTime", [s], final_codes=SKIPPED)
                if t is not None:
                    return int(t)
            except RpcError:
                continue
        raise RuntimeError(f"no block time found near slot {height}")

    def height_at_time(self, ts: int, tip: int) -> int:
        # ~0.4 s per slot; a binary search would cost dozens of calls for little gain
        tip_time = self.time_of(tip)
        return max(0, tip - int((tip_time - ts) / 0.4))

    def block_rows(self, height: int, dataset_id: int, source: str) -> list[tuple] | None:
        try:
            block = self.client.rpc("getBlock", [height, {
                "encoding": "json", "maxSupportedTransactionVersion": 1,
                "transactionDetails": "full", "rewards": False, "commitment": "finalized"}], final_codes=SKIPPED)
        except RpcError:
            return None                                    # skipped slot: no block, not an error
        if not block:
            return None
        return block_to_rows(block, height, self.chain.key, dataset_id, source)


def _keys(tx: dict) -> list[str]:
    msg = tx["transaction"]["message"]
    keys = [k if isinstance(k, str) else k["pubkey"] for k in msg["accountKeys"]]
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    return keys + loaded.get("writable", []) + loaded.get("readonly", [])


def block_to_rows(block: dict, slot: int, chain: str, dataset_id: int, source: str = "api") -> list[tuple]:
    if block.get("blockTime") is None:
        return []
    bt = datetime.fromtimestamp(int(block["blockTime"]), tz=timezone.utc)
    rows = []
    for tx in block.get("transactions", []):
        keys = _keys(tx)
        if VOTE in keys:
            continue
        meta = tx.get("meta") or {}
        pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
        fee = int(meta.get("fee") or 0)
        sender = keys[0] if keys else ""
        best_i, best_d = -1, 0
        for i in range(1, min(len(pre), len(post), len(keys))):
            d = post[i] - pre[i]
            if d > best_d:
                best_i, best_d = i, d
        programs = {keys[ins["programIdIndex"]] for ins in tx["transaction"]["message"].get("instructions", [])
                    if ins.get("programIdIndex") is not None and ins["programIdIndex"] < len(keys)}
        if best_i >= 0:
            to = keys[best_i]
        else:
            others = sorted(programs - {SYSTEM, COMPUTE_BUDGET})
            to = others[0] if others else (sorted(programs)[0] if programs else "")
        program_call = 1 if programs - {SYSTEM, COMPUTE_BUDGET} else 0
        rows.append((chain, dataset_id, source, slot, bt, tx["transaction"]["signatures"][0], sender, to,
                     best_d / 1e9, int(meta.get("computeUnitsConsumed") or 0), float(fee), program_call, 0))
    return rows

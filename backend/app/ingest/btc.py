"""Bitcoin (UTXO model) mapped onto the account-style transaction table.

A Bitcoin transaction spends inputs and creates outputs, so it has no single "from" and "to".
Mapping used here (a common heuristic, documented in the design doc):
  * sender   = the address of the largest input (prevout); "coinbase" for newly mined coins
  * one row per output to another address, value = that output in BTC
  * outputs back to the sender (change) are left out; a transaction that only pays itself keeps one row
  * row key  = "<txid>:<output index>" so outputs of one transaction stay separate rows
  * fee column holds the fee rate in sat/vB; gas_limit holds the virtual size (vbytes)
Needs Bitcoin Core 25+ (getblock verbosity 3 returns prevout); NOWNodes runs 31.x.
"""

from datetime import datetime, timezone

from app.ingest.base import Adapter


def _addr(spk: dict) -> str:
    if not spk:
        return ""
    if spk.get("address"):
        return spk["address"]
    addrs = spk.get("addresses") or []
    return addrs[0] if addrs else ""


class BtcAdapter(Adapter):
    chunk_blocks = 6             # ~13 MB per block: checkpoint often
    timeout = 300.0

    def latest_height(self) -> int:
        return int(self.client.rpc("getblockcount"))

    def time_of(self, height: int) -> int:
        h = self.client.rpc("getblockhash", [height])
        return int(self.client.rpc("getblockheader", [h])["time"])

    def height_at_time(self, ts: int, tip: int) -> int:
        # ~10 minute blocks: estimate, then tighten with a short binary search around it
        tip_time = self.time_of(tip)
        guess = max(0, tip - int((tip_time - ts) / 600) - 12)
        lo, hi = guess, tip
        while lo < hi:
            mid = (lo + hi) // 2
            if self.time_of(mid) < ts:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def block_rows(self, height: int, dataset_id: int, source: str) -> list[tuple] | None:
        h = self.client.rpc("getblockhash", [height])
        block = self.client.rpc("getblock", [h, 3])
        if not block:
            return None
        return block_to_rows(block, self.chain.key, dataset_id, source)


def block_to_rows(block: dict, chain: str, dataset_id: int, source: str = "api") -> list[tuple]:
    height = int(block["height"])
    bt = datetime.fromtimestamp(int(block["time"]), tz=timezone.utc)
    rows = []
    for tx in block.get("tx", []):
        txid = tx["txid"]
        coinbase = any("coinbase" in vin for vin in tx.get("vin", []))
        if coinbase:
            sender = "coinbase"
        else:
            inputs = [(_addr((vin.get("prevout") or {}).get("scriptPubKey")), float((vin.get("prevout") or {}).get("value") or 0))
                      for vin in tx.get("vin", [])]
            inputs = [i for i in inputs if i[0]]
            sender = max(inputs, key=lambda i: i[1])[0] if inputs else ""
        vsize = int(tx.get("vsize") or tx.get("size") or 0)
        fee_rate = (float(tx.get("fee") or 0) * 1e8 / vsize) if vsize else 0.0       # sat/vB
        outs = [(int(o.get("n", i)), _addr(o.get("scriptPubKey")), float(o.get("value") or 0))
                for i, o in enumerate(tx.get("vout", []))]
        outs = [o for o in outs if o[1]]                                              # skip OP_RETURN / non-standard
        paid = [o for o in outs if o[1] != sender] or outs[:1]                        # drop change; keep 1 row for self-sends
        for n, to, value in paid:
            rows.append((chain, dataset_id, source, height, bt, f"{txid}:{n}", sender, to, value,
                         vsize, round(fee_rate, 3), 0, 0))
    return rows

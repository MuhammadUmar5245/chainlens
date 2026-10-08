"""ERC-20 Transfer / Approval logs -> token_transfers / token_approvals.

Uses the existing chain adapter's JSON-RPC client, so the chain's rate limit, retry logic and
RpcAuthError handling apply unchanged. EVM chains only.
"""

from datetime import datetime, timezone

from app.db.clickhouse import new_client
from app.db.postgres import SessionLocal
from app.ingest.base import RpcError
from app.scam.models import AddressCode, Token

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
UNLIMITED = 2 ** 255
RANGE_ERRORS = (-32005, -32602, -32000)        # "too many results" style errors -> split the block range
CALL_ERRORS = (3, -32000, -32015)               # eth_call reverts: not retried

TRANSFER_COLUMNS = ["chain", "dataset_id", "source", "block_number", "block_time", "tx_hash", "log_index", "token_address",
                    "from_addr", "to_addr", "raw_amount", "amount", "token_symbol", "token_decimals"]
APPROVAL_COLUMNS = ["chain", "dataset_id", "source", "block_number", "block_time", "tx_hash", "log_index", "token_address",
                    "owner", "spender", "raw_amount", "is_unlimited", "spender_is_contract"]


def topic_address(topic: str) -> str:
    return "0x" + topic[-40:].lower()


def word_int(data: str) -> int:
    data = (data or "0x")[2:]
    return int(data[:64], 16) if data else 0


def decode_abi_string(result: str) -> str:
    """symbol() returns an ABI string, or bytes32 on some old tokens."""
    raw = bytes.fromhex((result or "0x")[2:])
    try:
        if len(raw) >= 64:
            offset = int.from_bytes(raw[:32], "big")
            length = int.from_bytes(raw[offset:offset + 32], "big")
            text = raw[offset + 32: offset + 32 + length]
        else:
            text = raw.rstrip(b"\x00")
        return text.decode("utf-8", errors="ignore").strip().replace("\x00", "")[:64]
    except Exception:
        return ""


def parse_logs(logs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split raw logs into ERC-20 transfers and approvals. ERC-721 (4 topics) is skipped."""
    transfers, approvals = [], []
    for log in logs:
        topics = log.get("topics") or []
        if len(topics) != 3 or log.get("removed"):
            continue
        base = {
            "block_number": int(log["blockNumber"], 16), "tx_hash": log["transactionHash"].lower(),
            "log_index": int(log["logIndex"], 16), "token_address": log["address"].lower(),
            "raw": word_int(log.get("data")),
        }
        if topics[0] == TRANSFER:
            transfers.append(base | {"from_addr": topic_address(topics[1]), "to_addr": topic_address(topics[2])})
        elif topics[0] == APPROVAL:
            approvals.append(base | {"owner": topic_address(topics[1]), "spender": topic_address(topics[2])})
    return transfers, approvals


class TokenEnricher:
    def __init__(self, adapter, chain_key: str):
        self.rpc = adapter.client.rpc
        self.chain = chain_key
        self.ch = new_client()
        with SessionLocal() as s:
            self.tokens = {t.address: (t.symbol, t.decimals) for t in s.query(Token).filter(Token.chain == chain_key)}
            self.codes = {c.address: c.is_contract for c in s.query(AddressCode).filter(AddressCode.chain == chain_key)}

    # --- RPC helpers -----------------------------------------------------------------------
    def get_logs(self, first: int, last: int) -> list[dict]:
        try:
            return self.rpc("eth_getLogs", [{"fromBlock": hex(first), "toBlock": hex(last), "topics": [[TRANSFER, APPROVAL]]}],
                            final_codes=RANGE_ERRORS)
        except RpcError:
            if first == last:
                raise
            mid = (first + last) // 2                      # too many results: split and retry
            return self.get_logs(first, mid) + self.get_logs(mid + 1, last)

    def token_meta(self, address: str) -> tuple[str, int]:
        if address in self.tokens:
            return self.tokens[address]
        symbol, decimals, source = "", 18, "guess"
        try:
            decimals = word_int(self.rpc("eth_call", [{"to": address, "data": "0x313ce567"}, "latest"], retries=2, final_codes=CALL_ERRORS))
            symbol = decode_abi_string(self.rpc("eth_call", [{"to": address, "data": "0x95d89b41"}, "latest"], retries=2, final_codes=CALL_ERRORS))
            source = "rpc"
            if decimals > 36:
                decimals, source = 18, "guess"
        except Exception:
            pass
        self.tokens[address] = (symbol, decimals)
        with SessionLocal() as s:
            s.merge(Token(chain=self.chain, address=address, symbol=symbol, decimals=decimals, source=source))
            s.commit()
        return symbol, decimals

    def is_contract(self, address: str) -> int:
        if address in self.codes:
            return int(self.codes[address])
        try:
            code = self.rpc("eth_getCode", [address, "latest"], retries=2, final_codes=CALL_ERRORS)
        except Exception:
            return -1
        flag = bool(code and code not in ("0x", "0x0"))
        self.codes[address] = flag
        with SessionLocal() as s:
            s.merge(AddressCode(chain=self.chain, address=address, is_contract=flag))
            s.commit()
        return int(flag)

    def block_times(self, first: int, last: int) -> dict[int, datetime]:
        res = self.ch.query("SELECT block_number, any(block_time) FROM transactions WHERE chain = {c:String} "
                            "AND block_number BETWEEN {a:UInt64} AND {b:UInt64} GROUP BY block_number",
                            parameters={"c": self.chain, "a": first, "b": last})
        return {int(n): t for n, t in res.result_rows}

    def block_time(self, n: int, known: dict) -> datetime:
        if n not in known:
            ts = int(self.rpc("eth_getBlockByNumber", [hex(n), False])["timestamp"], 16)
            known[n] = datetime.fromtimestamp(ts, tz=timezone.utc)
        return known[n]

    # --- one block range -------------------------------------------------------------------
    def enrich_range(self, first: int, last: int, dataset_id: int, source: str = "api") -> tuple[int, int]:
        transfers, approvals = parse_logs(self.get_logs(first, last))
        times = self.block_times(first, last)
        t_rows = []
        for t in transfers:
            symbol, decimals = self.token_meta(t["token_address"])
            t_rows.append([self.chain, dataset_id, source, t["block_number"], self.block_time(t["block_number"], times),
                           t["tx_hash"], t["log_index"], t["token_address"], t["from_addr"], t["to_addr"],
                           str(t["raw"]), t["raw"] / (10 ** decimals), symbol, decimals])
        a_rows = []
        for a in approvals:
            unlimited = a["raw"] >= UNLIMITED
            a_rows.append([self.chain, dataset_id, source, a["block_number"], self.block_time(a["block_number"], times),
                           a["tx_hash"], a["log_index"], a["token_address"], a["owner"], a["spender"], str(a["raw"]),
                           int(unlimited), self.is_contract(a["spender"]) if unlimited else -1])
        if t_rows:
            self.ch.insert("token_transfers", t_rows, column_names=TRANSFER_COLUMNS)
        if a_rows:
            self.ch.insert("token_approvals", a_rows, column_names=APPROVAL_COLUMNS)
        return len(t_rows), len(a_rows)

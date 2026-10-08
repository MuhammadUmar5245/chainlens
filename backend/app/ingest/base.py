"""Shared pieces for chain adapters: JSON-RPC transport with retries, rate limiting,
parallel block fetching, and the adapter interface every chain family implements."""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterator

import httpx

HEXLIKE = re.compile(r"(0x)?[0-9a-fA-F]+")


def norm_id(value: str | None) -> str:
    """Hex addresses/hashes are case-insensitive -> lowercase. Base58 / bech32 (Bitcoin, Solana) keep their case."""
    v = (value or "").strip()
    return v.lower() if HEXLIKE.fullmatch(v) else v


class RpcAuthError(RuntimeError):
    """The key is missing, wrong, or has no access to this chain. Never retried."""


class RpcError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(f"RPC error {code}: {message}")
        self.code = code


class RateLimiter:
    """Spaces requests evenly so a chain never exceeds its requests-per-second limit (shared by threads)."""

    def __init__(self, rps: float):
        self.interval = 1.0 / max(rps, 0.1)
        self.lock = threading.Lock()
        self.next_at = time.monotonic()

    def wait(self):
        with self.lock:
            now = time.monotonic()
            wait = self.next_at - now
            self.next_at = max(now, self.next_at) + self.interval
        if wait > 0:
            time.sleep(wait)


class JsonRpc:
    def __init__(self, rpc_url: str, api_key: str, auth_mode: str = "header", limiter: RateLimiter | None = None,
                 timeout: float = 30.0):
        headers = {"Content-Type": "application/json"}
        if auth_mode == "header":
            headers["api-key"] = api_key
            self.url = rpc_url
        else:
            self.url = f"{rpc_url.rstrip('/')}/{api_key}"
        self.http = httpx.Client(headers=headers, timeout=timeout)
        self.limiter = limiter

    def close(self):
        self.http.close()

    def rpc(self, method: str, params=None, retries: int = 5, final_codes: tuple = ()):
        """Call a method. JSON-RPC errors whose code is in `final_codes` are raised at once (e.g. skipped slots)."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params if params is not None else []}
        for attempt in range(retries):
            if self.limiter:
                self.limiter.wait()
            try:
                r = self.http.post(self.url, json=payload)
                if r.status_code in (401, 403):
                    raise RpcAuthError(f"HTTP {r.status_code}: API key rejected - check NOWNODES_API_KEY and the chain's endpoint")
                if r.status_code == 404 and "do not have access" in r.text:
                    raise RpcAuthError("Your NOWNodes key does not have access to this chain. "
                                       "Add the chain to your plan or key in the NOWNodes dashboard.")
                if r.status_code == 429:
                    raise RuntimeError("rate limited (HTTP 429)")
                if r.status_code >= 500 and r.headers.get("content-type", "").startswith("application/json"):
                    pass                                   # bitcoind reports RPC errors with HTTP 500 + JSON body
                else:
                    r.raise_for_status()
                data = r.json()
                err = data.get("error")
                if err:
                    code = err.get("code") if isinstance(err, dict) else None
                    exc = RpcError(code, err.get("message") if isinstance(err, dict) else err)
                    if code in final_codes:
                        raise exc
                    raise RuntimeError(str(exc))
                return data["result"]
            except (RpcAuthError, RpcError):
                raise
            except Exception as e:
                if attempt == retries - 1:
                    raise RuntimeError(f"{method} failed after {retries} tries: {e}") from e
                time.sleep(min(2 ** attempt, 30))


class Adapter:
    """One chain family. Heights are block numbers (EVM, Bitcoin) or slots (Solana)."""

    chunk_blocks = 1000          # blocks per checkpoint
    timeout = 30.0

    def __init__(self, chain, api_key: str, auth_mode: str):
        self.chain = chain
        self.client = JsonRpc(chain.rpc_url, api_key, auth_mode, limiter=RateLimiter(chain.rate_limit_rps), timeout=self.timeout)

    def close(self):
        self.client.close()

    def latest_height(self) -> int:
        raise NotImplementedError

    def height_at_time(self, ts: int, tip: int) -> int:
        """First height at or after unix time `ts`."""
        raise NotImplementedError

    def time_of(self, height: int) -> int:
        raise NotImplementedError

    def block_rows(self, height: int, dataset_id: int, source: str) -> list[tuple] | None:
        """Rows in TX_COLUMNS order, or None when the height has no block (e.g. a skipped Solana slot)."""
        raise NotImplementedError

    def binary_search_time(self, ts: int, tip: int) -> int:
        lo, hi = 0, tip
        while lo < hi:
            mid = (lo + hi) // 2
            if self.time_of(mid) < ts:
                lo = mid + 1
            else:
                hi = mid
        return lo


def fetch_blocks(adapter: Adapter, first: int, last: int, dataset_id: int, workers: int,
                 source: str = "api") -> Iterator[tuple[int, list[tuple] | None, Exception | None]]:
    """Fetch heights first..last in parallel; yields (height, rows | None, error | None) as each one finishes,
    so callers can write rows out immediately instead of holding a whole chunk in memory."""
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(adapter.block_rows, n, dataset_id, source): n for n in range(first, last + 1)}
        for fut in as_completed(futures):
            n = futures[fut]
            try:
                yield n, fut.result(), None
            except RpcAuthError:
                for f in futures:
                    f.cancel()
                raise
            except Exception as e:  # recorded as a failed block, the job carries on
                yield n, None, e

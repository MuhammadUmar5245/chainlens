"""Data dumps: read CSV / Parquet / JSON Lines / Excel in chunks, map columns to the
standard transaction fields, validate, and hand back clean rows plus rejected rows."""

from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from app.db.clickhouse import TX_COLUMNS

CHUNK_ROWS = 100_000

FORMATS = {".csv": "csv", ".parquet": "parquet", ".jsonl": "jsonl", ".ndjson": "jsonl", ".json": "jsonl", ".xlsx": "xlsx"}

# standard field -> column names we recognise automatically
FIELDS = {
    "tx_hash":          ["tx_hash", "hash", "transaction_hash", "txid", "tx_id", "txhash"],
    "timestamp":        ["timestamp", "block_time", "block_timestamp", "time", "ts", "event_time", "datetime", "date"],
    "from":             ["from", "from_addr", "from_address", "sender"],
    "to":               ["to", "to_addr", "to_address", "receiver", "recipient"],
    "value":            ["value", "value_eth", "value_native", "amount", "value_wei"],
    "block_number":     ["block_number", "block", "blocknumber", "block_height", "height"],
    "gas_price":        ["gas_price", "gas_price_gwei", "gasprice"],
    "gas_limit":        ["gas_limit", "gas", "gaslimit"],
    "is_contract_call": ["is_contract_call", "contract_call"],
    "input":            ["input", "input_data", "data"],
    "nonce":            ["nonce"],
    "chain":            ["chain", "network", "blockchain"],
}
REQUIRED = ["tx_hash", "timestamp", "from", "to", "value"]


def detect_format(filename: str) -> str | None:
    return FORMATS.get(Path(filename).suffix.lower())


def read_chunks(path: str, fmt: str, chunk_rows: int = CHUNK_ROWS) -> Iterator[pd.DataFrame]:
    if fmt == "csv":
        yield from pd.read_csv(path, chunksize=chunk_rows, dtype=str, keep_default_na=False)
    elif fmt == "parquet":
        import pyarrow.parquet as pq
        for batch in pq.ParquetFile(path).iter_batches(batch_size=chunk_rows):
            yield batch.to_pandas()
    elif fmt == "jsonl":
        yield from pd.read_json(path, lines=True, chunksize=chunk_rows, dtype=False)
    elif fmt == "xlsx":
        df = pd.read_excel(path, dtype=str, keep_default_na=False)    # Excel tops out at 1,048,576 rows per sheet
        for start in range(0, len(df), chunk_rows):
            yield df.iloc[start:start + chunk_rows]
    else:
        raise ValueError(f"unsupported format: {fmt}")


def preview(path: str, fmt: str, rows: int = 20) -> tuple[list[str], list[dict]]:
    first = next(read_chunks(path, fmt, chunk_rows=rows), pd.DataFrame())
    head = first.head(rows).astype(str)
    return [str(c) for c in first.columns], head.to_dict(orient="records")


def suggest_mapping(columns: list[str]) -> dict:
    lower = {c.lower().strip(): c for c in columns}
    mapping = {}
    for field, aliases in FIELDS.items():
        for alias in aliases:
            if alias in lower:
                mapping[field] = lower[alias]
                break
    value_col = (mapping.get("value") or "").lower()
    gas_col = (mapping.get("gas_price") or "").lower()
    return {
        "mapping": mapping,
        "value_unit": "wei" if "wei" in value_col else "native",
        "gas_unit": "gwei" if "gwei" in gas_col else "wei",
    }


def _num(s: pd.Series) -> pd.Series:
    """Numbers from mixed input: plain numbers, numeric strings, or 0x-hex strings (as float)."""
    if s.dtype != object:
        return pd.to_numeric(s, errors="coerce").astype(float)
    text = s.astype(str).str.strip()
    is_hex = text.str.startswith(("0x", "0X")) & (text.str.len() > 2)
    out = pd.to_numeric(text.where(~is_hex), errors="coerce").astype(float)
    if is_hex.any():
        out[is_hex] = text[is_hex].map(lambda x: float(int(x, 16)))
    return out


def _text(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip().str.lower().replace({"nan": "", "none": ""})


def _ident(s: pd.Series) -> pd.Series:
    """Addresses and hashes: hex is lowercased, base58 / bech32 (Bitcoin, Solana) keep their case."""
    raw = s.fillna("").astype(str).str.strip().replace({"nan": "", "None": "", "none": ""})
    hexlike = raw.str.fullmatch(r"(0x)?[0-9a-fA-F]+")
    return raw.where(~hexlike, raw.str.lower())


def _times(s: pd.Series) -> pd.Series:
    nums = _num(s)
    if nums.notna().mean() > 0.9:
        unit = "ms" if nums.dropna().median() > 1e11 else "s"
        return pd.to_datetime(nums, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(s.astype(str), utc=True, errors="coerce", format="mixed")


def normalise(df: pd.DataFrame, opts: dict, dataset_id: int, valid_chains: set[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Map one chunk to TX_COLUMNS. Returns (clean rows, rejected rows with a reason column)."""
    m = opts["mapping"]
    col = lambda field: df[m[field]] if m.get(field) in df.columns else None  # noqa: E731
    n = len(df)
    out = pd.DataFrame(index=df.index)
    reason = pd.Series("", index=df.index, dtype=object)

    def reject(mask, why):
        reason[mask & (reason == "")] = why

    if opts.get("chain"):
        out["chain"] = opts["chain"]
    else:
        out["chain"] = _text(col("chain")) if col("chain") is not None else ""
    reject(~out["chain"].isin(valid_chains), "unknown chain")

    out["dataset_id"] = np.uint64(dataset_id)
    out["source"] = "upload"

    out["tx_hash"] = _ident(col("tx_hash"))
    reject(out["tx_hash"] == "", "missing tx_hash")

    out["block_time"] = _times(col("timestamp"))
    reject(out["block_time"].isna(), "bad timestamp")

    out["from_addr"] = _ident(col("from"))
    reject(out["from_addr"] == "", "missing from address")
    to = _ident(col("to"))
    out["to_addr"] = to.where(to != "", "contract_creation")

    value = _num(col("value"))
    reject(value.isna(), "bad value")
    out["value_native"] = value / (10 ** int(opts.get("decimals", 18))) if opts.get("value_unit") == "wei" else value

    bn = _num(col("block_number")) if col("block_number") is not None else pd.Series(0.0, index=df.index)
    out["block_number"] = bn.fillna(0).clip(lower=0)

    gas = _num(col("gas_price")) if col("gas_price") is not None else pd.Series(0.0, index=df.index)
    out["gas_price_gwei"] = (gas / 1e9 if opts.get("gas_unit") == "wei" else gas).fillna(0)
    gl = _num(col("gas_limit")) if col("gas_limit") is not None else pd.Series(0.0, index=df.index)
    out["gas_limit"] = gl.fillna(0).clip(lower=0)
    nonce = _num(col("nonce")) if col("nonce") is not None else pd.Series(0.0, index=df.index)
    out["nonce"] = nonce.fillna(0).clip(lower=0)

    if col("is_contract_call") is not None:
        flag = _text(col("is_contract_call")).isin(["1", "true", "yes", "y", "t"])
    elif col("input") is not None:
        data = _text(col("input"))
        flag = (data.str.len() > 2) & (data != "0x")
    else:
        flag = pd.Series(False, index=df.index)
    out["is_contract_call"] = flag.astype("uint8")

    bad = reason != ""
    rejected = df[bad].copy()
    rejected["reject_reason"] = reason[bad]
    clean = out[~bad].copy()
    for c in ["block_number", "gas_limit", "nonce"]:
        clean[c] = clean[c].astype("uint64")
    clean["value_native"] = clean["value_native"].fillna(0).astype(float)
    assert len(clean) + len(rejected) == n
    return clean[TX_COLUMNS], rejected

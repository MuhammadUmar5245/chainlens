import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.common import chains_param, pick_chains, resolve_run
from app.db.clickhouse import get_ch
from app.db.models import Chain
from app.db.postgres import get_db
from app.ingest.base import norm_id

router = APIRouter(prefix="/wallets", tags=["wallets"])

SORTS = {
    "volume": "volume", "tx_out": "tx_out", "tx_in": "tx_in", "anomaly_score": "anomaly_score",
    "net_flow": "net_flow", "native_sent": "native_sent", "native_received": "native_received",
    "counterparties": "uniq_receivers + uniq_senders", "tx_per_block": "tx_per_block",
}
COLUMNS = ("chain, wallet, volume, native_sent, native_received, net_flow, tx_out, tx_in, uniq_receivers, uniq_senders, "
           "tx_per_block, contract_call_ratio, avg_gas_gwei, anomaly_score, is_anomaly, cluster, tags, first_seen, last_seen")
ADDRESS_CHARS = re.compile(r"[0-9A-Za-z]{1,100}")      # hex (0x...), base58 (Bitcoin legacy, Solana), bech32 (bc1...)


def _filters(run_id, chains, tag, q, anomalies_only, cluster):
    where = ["run_id = {r:UInt64}", "chain IN {c:Array(String)}"]
    params = {"r": run_id, "c": chains}
    if tag:
        where.append("has(tags, {tag:String})")
        params["tag"] = tag
    if q:
        q = norm_id(q)
        if not ADDRESS_CHARS.fullmatch(q):
            raise HTTPException(422, "Search takes the start of an address, like 0x28c6c0, bc1q or 9WzD.")
        where.append("startsWith(wallet, {q:String})")
        params["q"] = q
    if anomalies_only:
        where.append("is_anomaly = 1")
    if cluster is not None:
        where.append("cluster = {cl:UInt8}")
        params["cl"] = cluster
    return " AND ".join(where), params


@router.get("")
def list_wallets(run_id: int | None = None, chains: list[str] | None = Depends(chains_param),
                 tag: str | None = None, q: str | None = None, anomalies_only: bool = False, cluster: int | None = None,
                 sort: str = "volume", order: str = Query("desc", pattern="^(asc|desc)$"),
                 page: int = Query(1, ge=1, le=10_000), limit: int = Query(50, ge=1, le=500),
                 db: Session = Depends(get_db)):
    if sort not in SORTS:
        raise HTTPException(422, f"sort must be one of: {', '.join(SORTS)}")
    run = resolve_run(db, run_id)
    where, params = _filters(run.id, pick_chains(run, chains), tag, q, anomalies_only, cluster)
    ch = get_ch()
    total = int(ch.command(f"SELECT count() FROM wallet_features WHERE {where}", parameters=params))
    res = ch.query(f"SELECT {COLUMNS} FROM wallet_features WHERE {where} "
                   f"ORDER BY {SORTS[sort]} {order.upper()}, wallet LIMIT {limit} OFFSET {(page - 1) * limit}",
                   parameters=params)
    rows = [dict(zip(res.column_names, r)) for r in res.result_rows]
    return {"run_id": run.id, "total": total, "page": page, "limit": limit, "rows": rows}


@router.get("/export")
def export_wallets(run_id: int | None = None, chains: list[str] | None = Depends(chains_param),
                   tag: str | None = None, q: str | None = None, anomalies_only: bool = False, cluster: int | None = None,
                   sort: str = "volume", max_rows: int = Query(1_000_000, ge=1, le=5_000_000),
                   db: Session = Depends(get_db)):
    if sort not in SORTS:
        raise HTTPException(422, f"sort must be one of: {', '.join(SORTS)}")
    run = resolve_run(db, run_id)
    where, params = _filters(run.id, pick_chains(run, chains), tag, q, anomalies_only, cluster)
    header = [c.strip() for c in COLUMNS.split(",")]
    cols = ", ".join("arrayStringConcat(tags, ',')" if c == "tags" else c for c in header)
    sql = f"SELECT {cols} FROM wallet_features WHERE {where} ORDER BY {SORTS[sort]} DESC LIMIT {max_rows}"

    def stream():
        buf = io.StringIO()
        csv.writer(buf).writerow(header)
        yield buf.getvalue()
        with get_ch().query_row_block_stream(sql, parameters=params) as blocks:
            for block in blocks:
                buf = io.StringIO()
                csv.writer(buf).writerows(block)
                yield buf.getvalue()

    name = f"chainlens-run{run.id}-wallets.csv"
    return StreamingResponse(stream(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/{chain}/{address}")
def wallet_detail(chain: str, address: str, run_id: int | None = None, db: Session = Depends(get_db)):
    address = norm_id(address)
    if not re.fullmatch(r"[0-9A-Za-z]{20,100}", address):
        raise HTTPException(422, "That does not look like a wallet address.")
    chain_row = db.get(Chain, chain)
    if chain_row is None:
        raise HTTPException(404, f"Unknown chain: {chain}")
    run = resolve_run(db, run_id)
    ch = get_ch()
    res = ch.query(f"SELECT {COLUMNS} FROM wallet_features WHERE run_id = {{r:UInt64}} AND chain = {{c:String}} "
                   f"AND wallet = {{a:String}}", parameters={"r": run.id, "c": chain, "a": address})
    profile = dict(zip(res.column_names, res.result_rows[0])) if res.result_rows else None
    txs = ch.query("""
        SELECT tx_hash, block_number, block_time, from_addr, to_addr, value_native, gas_price_gwei, is_contract_call
        FROM transactions
        WHERE chain = {c:String} AND (from_addr = {a:String} OR to_addr = {a:String})
        ORDER BY block_number DESC LIMIT 1 BY tx_hash LIMIT 100""", parameters={"c": chain, "a": address})
    cp = ch.query("""
        SELECT if(a = {a:String}, b, a) AS wallet, txs,
               if(a = {a:String}, a_to_b, b_to_a) AS sent, if(a = {a:String}, b_to_a, a_to_b) AS received,
               if(a = {a:String}, value_a_to_b, value_b_to_a) AS value_sent, if(a = {a:String}, value_b_to_a, value_a_to_b) AS value_received,
               contract_calls, last_seen
        FROM wallet_pairs WHERE run_id = {r:UInt64} AND chain = {c:String} AND (a = {a:String} OR b = {a:String})
        ORDER BY txs DESC LIMIT 20""", parameters={"r": run.id, "c": chain, "a": address})
    return {
        "counterparties": [dict(zip(cp.column_names, r)) for r in cp.result_rows],
        "chain": chain, "address": address, "run_id": run.id, "profile": profile,
        "explorer_url": chain_row.explorer_url.replace("{address}", address) if "{address}" in (chain_row.explorer_url or "") else None,
        "native_symbol": chain_row.native_symbol,
        "fee_unit": chain_row.fee_unit,
        "family": chain_row.family,
        "transactions": [dict(zip(txs.column_names, r)) for r in txs.result_rows],
    }

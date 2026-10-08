from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.common import chains_param, pick_chains, resolve_run
from app.db.clickhouse import get_ch
from app.db.models import AnalyticsRun, Chain, Dataset
from app.db.postgres import get_db
from app.ingest.base import norm_id
from app.jobs.tasks import create_analytics_job, enqueue
from app.schemas import JobOut, RunOut, RunRequest

router = APIRouter(prefix="/analytics", tags=["analytics"])

BUCKETS = [60, 300, 900, 1800, 3600, 7200, 14400, 43200, 86400]   # 1 min ... 1 day


@router.get("/runs", response_model=list[RunOut])
def list_runs(db: Session = Depends(get_db)):
    return db.query(AnalyticsRun).order_by(AnalyticsRun.id.desc()).limit(50).all()


@router.post("/runs", response_model=JobOut, status_code=202)
def start_run(body: RunRequest, db: Session = Depends(get_db)):
    known = {c.key for c in db.query(Chain)}
    bad = [c for c in body.chains if c not in known]
    if bad:
        raise HTTPException(400, f"Unknown chains: {', '.join(bad)}")
    if body.dataset_id is not None and db.get(Dataset, body.dataset_id) is None:
        raise HTTPException(404, "Dataset not found.")
    job = create_analytics_job(db, body.chains, body.dataset_id, body.time_from, body.time_to)
    enqueue(job)
    return job


def _rows(result) -> list[dict]:
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


@router.get("/summary")
def summary(run_id: int | None = None, chains: list[str] | None = Depends(chains_param), db: Session = Depends(get_db)):
    run = resolve_run(db, run_id)
    picked = pick_chains(run, chains)
    ch = get_ch()
    p = {"r": run.id, "c": picked}
    activity = _rows(ch.query("""
        SELECT chain, sum(txs) AS transactions, sum(blocks) AS blocks, sum(value) AS value,
               sum(contract_calls) / greatest(sum(txs), 1) AS contract_share,
               quantileTDigestMerge(0.5)(gas) AS median_gas, min(minute) AS time_from, max(minute) AS time_to
        FROM run_series WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)} GROUP BY chain""", parameters=p))
    wallets = {r["chain"]: r for r in _rows(ch.query("""
        SELECT chain, count() AS wallets, countIf(is_anomaly) AS anomalies
        FROM wallet_features WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)} GROUP BY chain""", parameters=p))}
    per_chain = []
    for a in activity:
        w = wallets.get(a["chain"], {})
        per_chain.append(a | {"wallets": w.get("wallets", 0), "anomalies": w.get("anomalies", 0)})
    order = {c: i for i, c in enumerate(run.chains)}
    per_chain.sort(key=lambda r: order.get(r["chain"], 99))
    totals = {
        "transactions": sum(r["transactions"] for r in per_chain),
        "blocks": sum(r["blocks"] for r in per_chain),
        "wallets": sum(r["wallets"] for r in per_chain),
        "anomalies": sum(r["anomalies"] for r in per_chain),
        "time_from": min((r["time_from"] for r in per_chain), default=None),
        "time_to": max((r["time_to"] for r in per_chain), default=None),
    }
    return {"run": RunOut.model_validate(run), "chains": picked, "per_chain": per_chain, "totals": totals}


@router.get("/series")
def series(run_id: int | None = None, chains: list[str] | None = Depends(chains_param),
           points: int = Query(120, ge=10, le=1000), db: Session = Depends(get_db)):
    run = resolve_run(db, run_id)
    picked = pick_chains(run, chains)
    ch = get_ch()
    p = {"r": run.id, "c": picked}
    lo, hi = ch.query("SELECT min(minute), max(minute) FROM run_series WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)}",
                      parameters=p).result_rows[0]
    span = max((hi - lo).total_seconds(), 60) if lo and hi else 60
    bucket = next((b for b in BUCKETS if span / b <= points), BUCKETS[-1])
    # output aliases differ from column names: an alias like "txs" would shadow the column inside sum(txs)
    rows = _rows(ch.query("""
        SELECT chain, toStartOfInterval(minute, toIntervalSecond({b:UInt32})) AS t,
               sum(txs) AS n_txs, sum(blocks) AS n_blocks, sum(value) AS n_value,
               sum(contract_calls) / greatest(sum(txs), 1) AS contract_share,
               quantileTDigestMerge(0.5)(gas) AS median_gas
        FROM run_series WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)}
        GROUP BY chain, t ORDER BY chain, t""", parameters=p | {"b": bucket}))
    out: dict[str, list] = {c: [] for c in picked}
    for r in rows:
        out[r["chain"]].append({"t": r["t"], "txs": r["n_txs"], "blocks": r["n_blocks"], "value": r["n_value"],
                                "contract_share": r["contract_share"], "median_gas": r["median_gas"]})
    return {"bucket_seconds": bucket, "series": [{"chain": c, "points": pts} for c, pts in out.items()]}


@router.get("/tags")
def tags(run_id: int | None = None, chains: list[str] | None = Depends(chains_param), db: Session = Depends(get_db)):
    run = resolve_run(db, run_id)
    rows = _rows(get_ch().query("""
        SELECT chain, tag, count() AS wallets
        FROM wallet_features ARRAY JOIN tags AS tag
        WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)}
        GROUP BY chain, tag ORDER BY wallets DESC""", parameters={"r": run.id, "c": pick_chains(run, chains)}))
    return {"rows": rows}


@router.get("/distribution")
def distribution(run_id: int | None = None, chains: list[str] | None = Depends(chains_param),
                 bins: int = Query(30, ge=5, le=100), db: Session = Depends(get_db)):
    """Histogram of anomaly scores per chain (equal-width bins from 0 to the highest score)."""
    run = resolve_run(db, run_id)
    ch = get_ch()
    p = {"r": run.id, "c": pick_chains(run, chains)}
    top = float(ch.command("SELECT max(anomaly_score) FROM wallet_features WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)}",
                          parameters=p) or 0)
    width = max(top, 1e-9) / bins
    rows = _rows(ch.query("""
        SELECT chain, least(toUInt32(floor(anomaly_score / {w:Float64})), {last:UInt32}) AS bin, count() AS wallets
        FROM wallet_features WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)}
        GROUP BY chain, bin ORDER BY chain, bin""", parameters=p | {"w": width, "last": bins - 1}))
    return {"bin_width": width, "bins": bins, "threshold": run.settings.get("anomaly_z", 3.0), "rows": rows}


PAIR_SORTS = {
    "txs": "txs DESC",
    "value": "(value_a_to_b + value_b_to_a) DESC",
    "two_way": "least(a_to_b, b_to_a) DESC, txs DESC",
    "recent": "last_seen DESC",
}


@router.get("/pairs")
def pairs(run_id: int | None = None, chains: list[str] | None = Depends(chains_param),
          min_txs: int = Query(2, ge=2), two_way: bool = False, transfers_only: bool = False,
          q: str | None = None, sort: str = "txs", limit: int = Query(50, ge=1, le=500),
          page: int = Query(1, ge=1, le=10_000), db: Session = Depends(get_db)):
    """Wallet pairs that transacted with each other most, with direction and value."""
    if sort not in PAIR_SORTS:
        raise HTTPException(422, f"sort must be one of: {', '.join(PAIR_SORTS)}")
    run = resolve_run(db, run_id)
    ch = get_ch()
    where = ["run_id = {r:UInt64}", "chain IN {c:Array(String)}", "txs >= {m:UInt64}"]
    p = {"r": run.id, "c": pick_chains(run, chains), "m": min_txs}
    if two_way:
        where.append("a_to_b > 0 AND b_to_a > 0")
    if transfers_only:
        where.append("contract_calls < txs")
    if q:
        where.append("(startsWith(a, {q:String}) OR startsWith(b, {q:String}))")
        p["q"] = norm_id(q)
    w = " AND ".join(where)
    total = int(ch.command(f"SELECT count() FROM wallet_pairs WHERE {w}", parameters=p))
    rows = _rows(ch.query(f"SELECT chain, a, b, txs, a_to_b, b_to_a, value_a_to_b, value_b_to_a, contract_calls, blocks, "
                          f"first_seen, last_seen FROM wallet_pairs WHERE {w} ORDER BY {PAIR_SORTS[sort]}, a, b "
                          f"LIMIT {limit} OFFSET {(page - 1) * limit}", parameters=p))
    # tags of every wallet on the page, so the UI can show who is a whale, bot or hub
    wallets = sorted({r["a"] for r in rows} | {r["b"] for r in rows})
    tags = {}
    if wallets:
        for r in _rows(ch.query("SELECT chain, wallet, tags, anomaly_score FROM wallet_features "
                                "WHERE run_id = {r:UInt64} AND wallet IN {w:Array(String)}",
                                parameters={"r": run.id, "w": wallets})):
            tags[f"{r['chain']}|{r['wallet']}"] = {"tags": r["tags"], "anomaly_score": r["anomaly_score"]}
    for r in rows:
        r["a_info"] = tags.get(f"{r['chain']}|{r['a']}", {"tags": [], "anomaly_score": 0})
        r["b_info"] = tags.get(f"{r['chain']}|{r['b']}", {"tags": [], "anomaly_score": 0})
    has_pairs = total > 0 or int(ch.command("SELECT count() FROM wallet_pairs WHERE run_id = {r:UInt64}", parameters={"r": run.id})) > 0
    return {"run_id": run.id, "total": total, "page": page, "limit": limit, "rows": rows,
            "computed": has_pairs}


@router.get("/clusters")
def clusters(run_id: int | None = None, chains: list[str] | None = Depends(chains_param), db: Session = Depends(get_db)):
    run = resolve_run(db, run_id)
    rows = _rows(get_ch().query("""
        SELECT chain, cluster, count() AS wallets,
               avg(tx_out) AS avg_tx_out, avg(tx_in) AS avg_tx_in, avg(volume) AS avg_volume,
               avg(uniq_receivers) AS avg_receivers, avg(uniq_senders) AS avg_senders,
               avg(contract_call_ratio) AS avg_contract, avg(avg_gas_gwei) AS avg_gas, avg(anomaly_score) AS avg_anomaly
        FROM wallet_features WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)}
        GROUP BY chain, cluster ORDER BY chain, wallets DESC""", parameters={"r": run.id, "c": pick_chains(run, chains)}))
    return {"rows": rows}

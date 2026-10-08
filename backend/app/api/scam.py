import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.common import chains_param, pick_chains, resolve_run
from app.config import settings
from app.db.clickhouse import get_ch
from app.db.models import Chain, Dataset, Job
from app.db.postgres import get_db
from app.ingest.base import norm_id
from app.scam.detectors import DETECTORS
from app.scam.labels import TEST_SOURCE
from app.scam.models import AddressLabel
from app.scam.tasks import _evm_chains, create_job, enqueue_scam_job
from app.schemas import JobOut

router = APIRouter(prefix="/scam", tags=["scam tracing"])
NOTE = "Findings are risk indicators, not proof of wrongdoing."
SEVERITIES = ("high", "medium", "low")


def _rows(res) -> list[dict]:
    return [dict(zip(res.column_names, r)) for r in res.result_rows]


def _finding(r: dict) -> dict:
    r["details"] = json.loads(r["details"]) if r.get("details") else {}
    return r


@router.post("/runs/{run_id}/detect", response_model=JobOut, status_code=202)
def detect(run_id: int, db: Session = Depends(get_db)):
    """Re-run all detectors for an analytics run (also happens automatically after analytics)."""
    run = resolve_run(db, run_id)
    chains = _evm_chains(list(run.chains))
    if not chains:
        raise HTTPException(400, "The MVP runs scam detectors on EVM chains (Ethereum, EthereumPoW, Ethereum Classic) only.")
    job = create_job(db, "scam_detect", {"chains": chains}, dataset_id=run.dataset_id, run_id=run.id)
    enqueue_scam_job(job)
    return job


@router.get("/summary")
def summary(run_id: int | None = None, chains: list[str] | None = Depends(chains_param), db: Session = Depends(get_db)):
    run = resolve_run(db, run_id)
    picked = pick_chains(run, chains)
    ch = get_ch()
    p = {"r": run.id, "c": picked}
    by_detector = _rows(ch.query("""
        SELECT detector, severity, count() AS findings, uniqExact(wallet) AS wallets
        FROM risk_findings WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)} GROUP BY detector, severity""", parameters=p))
    risk = _rows(ch.query("""
        SELECT severity, count() AS wallets FROM wallet_risk WHERE run_id = {r:UInt64} AND chain IN {c:Array(String)}
        GROUP BY severity""", parameters=p))
    job = db.query(Job).filter(Job.type == "scam_detect", Job.run_id == run.id).order_by(Job.id.desc()).first()
    detectors = []
    for key, (name, _) in DETECTORS.items():
        rows = [r for r in by_detector if r["detector"] == key]
        detectors.append({"id": key, "name": name, "findings": sum(r["findings"] for r in rows),
                          "wallets": sum(r["wallets"] for r in rows),
                          "by_severity": {s: sum(r["findings"] for r in rows if r["severity"] == s) for s in SEVERITIES}})
    return {
        "run_id": run.id, "chains": picked, "evm_chains": _evm_chains(picked), "note": NOTE,
        "detectors": detectors,
        "wallets_by_severity": {s: next((r["wallets"] for r in risk if r["severity"] == s), 0) for s in SEVERITIES},
        "job": None if job is None else {"id": job.id, "status": job.status, "message": job.message, "detail": job.detail,
                                         "progress": job.progress, "finished_at": job.finished_at},
        "test_labels_loaded": db.query(AddressLabel).filter(AddressLabel.source == TEST_SOURCE).count(),
        "labels_total": db.query(AddressLabel).count(),
    }


@router.get("/findings")
def findings(run_id: int | None = None, chains: list[str] | None = Depends(chains_param),
             detector: str | None = None, severity: str | None = None, wallet: str | None = None,
             page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    run = resolve_run(db, run_id)
    where = ["run_id = {r:UInt64}", "chain IN {c:Array(String)}"]
    p = {"r": run.id, "c": pick_chains(run, chains)}
    if detector:
        where.append("detector = {d:String}")
        p["d"] = detector
    if severity:
        where.append("severity = {s:String}")
        p["s"] = severity
    if wallet:
        where.append("(wallet = {w:String} OR has(related_wallets, {w:String}))")
        p["w"] = norm_id(wallet)
    w = " AND ".join(where)
    ch = get_ch()
    total = int(ch.command(f"SELECT count() FROM risk_findings WHERE {w}", parameters=p))
    rows = _rows(ch.query(f"SELECT toString(id) AS id, chain, detector, wallet, related_wallets, tx_hashes, score, severity, reason, "
                          f"details, created_at FROM risk_findings WHERE {w} "
                          f"ORDER BY score DESC, detector, wallet, id LIMIT {limit} OFFSET {(page - 1) * limit}", parameters=p))
    return {"run_id": run.id, "total": total, "page": page, "limit": limit, "note": NOTE, "rows": [_finding(r) for r in rows]}


@router.get("/risk")
def risk(run_id: int | None = None, chains: list[str] | None = Depends(chains_param), severity: str | None = None,
         min_score: int = Query(0, ge=0, le=100), q: str | None = None,
         page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    run = resolve_run(db, run_id)
    where = ["run_id = {r:UInt64}", "chain IN {c:Array(String)}", "risk_score >= {m:UInt8}"]
    p = {"r": run.id, "c": pick_chains(run, chains), "m": min_score}
    if severity:
        where.append("severity = {s:String}")
        p["s"] = severity
    if q:
        where.append("startsWith(wallet, {q:String})")
        p["q"] = norm_id(q)
    w = " AND ".join(where)
    ch = get_ch()
    total = int(ch.command(f"SELECT count() FROM wallet_risk WHERE {w}", parameters=p))
    rows = _rows(ch.query(f"SELECT chain, wallet, risk_score, severity, detectors_hit, top_reasons FROM wallet_risk WHERE {w} "
                          f"ORDER BY risk_score DESC, wallet LIMIT {limit} OFFSET {(page - 1) * limit}", parameters=p))
    labels = {}
    if rows:
        for l in db.query(AddressLabel).filter(AddressLabel.address.in_([r["wallet"] for r in rows])):
            labels.setdefault(l.address, []).append({"label": l.label, "category": l.category, "source": l.source})
    for r in rows:
        r["labels"] = labels.get(r["wallet"], [])
    return {"run_id": run.id, "total": total, "page": page, "limit": limit, "note": NOTE, "rows": rows}


@router.get("/wallet/{chain}/{address}")
def wallet_risk_detail(chain: str, address: str, run_id: int | None = None, db: Session = Depends(get_db)):
    run = resolve_run(db, run_id)
    address = norm_id(address)
    ch = get_ch()
    p = {"r": run.id, "c": chain, "a": address}
    risk_rows = _rows(ch.query("SELECT risk_score, severity, detectors_hit, top_reasons FROM wallet_risk "
                               "WHERE run_id = {r:UInt64} AND chain = {c:String} AND wallet = {a:String}", parameters=p))
    rows = _rows(ch.query("SELECT toString(id) AS id, detector, wallet, related_wallets, tx_hashes, score, severity, reason, details "
                          "FROM risk_findings WHERE run_id = {r:UInt64} AND chain = {c:String} "
                          "AND (wallet = {a:String} OR has(related_wallets, {a:String})) ORDER BY score DESC, detector LIMIT 200",
                          parameters=p))
    return {"run_id": run.id, "chain": chain, "address": address, "note": NOTE,
            "risk": risk_rows[0] if risk_rows else None, "findings": [_finding(r) for r in rows]}


class EnrichRequest(BaseModel):
    chain: str = "eth"
    dataset_id: int | None = None
    from_block: int | None = Field(None, ge=0)
    to_block: int | None = Field(None, ge=0)


@router.post("/enrich", response_model=JobOut, status_code=202)
def enrich(body: EnrichRequest, db: Session = Depends(get_db)):
    """Load ERC-20 transfers and approvals for a dataset or a block range."""
    chain = db.get(Chain, body.chain)
    if chain is None or chain.family != "evm":
        raise HTTPException(400, "Token enrichment works on EVM chains only (Ethereum, EthereumPoW, Ethereum Classic).")
    if not settings.nownodes_api_key:
        raise HTTPException(400, "NOWNODES_API_KEY is not set on the server. Add it to .env and restart the stack.")
    if body.dataset_id is None and (body.from_block is None or body.to_block is None or body.to_block < body.from_block):
        raise HTTPException(422, "Give a dataset, or a valid block range.")
    if body.dataset_id is not None and db.get(Dataset, body.dataset_id) is None:
        raise HTTPException(404, "Dataset not found.")
    source = "api"
    if body.dataset_id is not None and db.get(Dataset, body.dataset_id).source_type == "upload":
        source = "upload"                         # enrichment of an uploaded dump follows the dump's retention
    job = create_job(db, "enrich_tokens", body.model_dump() | {"source": source}, dataset_id=body.dataset_id)
    enqueue_scam_job(job)
    return job

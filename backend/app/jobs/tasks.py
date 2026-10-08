"""Background jobs. Each job records status, progress and errors in the `jobs` table,
and every step is safe to re-run (checkpoints + de-duplicating storage)."""

import logging
import os
import time
import traceback
from datetime import datetime, timezone

import redis

from app.analytics import engine
from app.config import settings
from app.db.clickhouse import TX_COLUMNS, new_client
from app.db.models import AnalyticsRun, Chain, Dataset, Job, Upload
from app.db.postgres import SessionLocal
from app.ingest import upload as dump
from app.ingest.adapters import get_adapter
from app.ingest.base import fetch_blocks
from app.jobs.celery_app import celery
from app.jobs.progress import get_job, is_cancelled, now, update_dataset, update_job, update_run

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# job wrapper
# ---------------------------------------------------------------------------
def _run_job(job_id: int, work) -> None:
    job = get_job(job_id)
    if job is None or job.status in ("succeeded", "cancelled"):
        return
    if job.status == "cancelling":
        update_job(job_id, status="cancelled", finished_at=now())
        return
    update_job(job_id, status="running", started_at=job.started_at or now(), error=None)
    try:
        work(job)
        if is_cancelled(job_id):
            update_job(job_id, status="cancelled", finished_at=now(), message="Cancelled")
        else:
            update_job(job_id, status="succeeded", progress=1.0, finished_at=now())
    except Exception as e:
        log.error("job %s failed\n%s", job_id, traceback.format_exc())
        update_job(job_id, status="failed", error=f"{type(e).__name__}: {e}", finished_at=now())
        if job.dataset_id and job.type != "analytics":
            update_dataset(job.dataset_id, status="failed")
        if job.run_id:
            update_run(job.run_id, status="failed", finished_at=now())


def enqueue(job: Job) -> None:
    from app.scam.tasks import enqueue_scam_job          # scam tracing job types (registration)
    if enqueue_scam_job(job):
        return
    {"fetch": fetch_task,"load_upload": load_upload_task, "analytics": analytics_task}[job.type].delay(job.id)


def create_analytics_job(db, chains: list[str], dataset_id: int | None = None,
                         time_from: datetime | None = None, time_to: datetime | None = None) -> Job:
    run = AnalyticsRun(dataset_id=dataset_id, chains=chains, time_from=time_from, time_to=time_to,
                       settings={"kmeans_k": settings.kmeans_k, "anomaly_z": settings.anomaly_z}, status="queued")
    db.add(run)
    db.flush()
    job = Job(type="analytics", dataset_id=dataset_id, run_id=run.id, params={"chains": chains}, message="Waiting to start")
    db.add(job)
    db.commit()
    return job


def _chain(key: str) -> Chain:
    with SessionLocal() as s:
        chain = s.get(Chain, key)
    if chain is None:
        raise ValueError(f"unknown chain: {key}")
    return chain


def _insert_rows(ch, rows: list[tuple]) -> None:
    step = settings.insert_batch_rows
    for i in range(0, len(rows), step):
        ch.insert("transactions", rows[i:i + step], column_names=TX_COLUMNS)


def _finish_dataset(dataset_id: int, rows: int) -> None:
    ch = new_client()
    lo, hi = ch.query("SELECT min(block_time), max(block_time) FROM transactions WHERE dataset_id = {d:UInt64}",
                      parameters={"d": dataset_id}).result_rows[0]
    update_dataset(dataset_id, status="ready", row_count=rows,
                   time_from=lo.replace(tzinfo=timezone.utc) if rows else None,
                   time_to=hi.replace(tzinfo=timezone.utc) if rows else None)


def _queue_follow_up_analytics(dataset_id: int, chains: list[str]) -> None:
    with SessionLocal() as s:
        job = create_analytics_job(s, chains, dataset_id=dataset_id)
    enqueue(job)


# ---------------------------------------------------------------------------
# 1. fetch from NOWNodes
# ---------------------------------------------------------------------------
@celery.task(name="fetch")
def fetch_task(job_id: int) -> None:
    _run_job(job_id, _fetch)


def _fetch(job: Job) -> None:
    p, detail = job.params, dict(job.detail or {})
    chain = _chain(p["chain"])
    if not settings.nownodes_api_key:
        raise RuntimeError("NOWNODES_API_KEY is not set on the server - add it to .env and restart")
    adapter = get_adapter(chain, settings.nownodes_api_key, settings.nownodes_auth_mode)
    unit = "slots" if chain.family == "solana" else "blocks"
    ch = new_client()
    update_dataset(job.dataset_id, status="loading")
    try:
        if "range" not in detail:                       # resolve once; a resumed job keeps the same range
            update_job(job.id, message=f"Finding the {unit[:-1]} range")
            tip = adapter.latest_height()
            if p["mode"] == "last_blocks":
                first, last = max(0, tip - int(p["blocks"]) + 1), tip
            elif p["mode"] == "last_hours":
                tip_time = adapter.time_of(tip)
                first, last = adapter.height_at_time(tip_time - int(p["hours"]) * 3600, tip), tip
            else:
                first, last = int(p["from_block"]), int(p["to_block"])
            detail["range"] = [first, last]
            update_job(job.id, detail=detail)
            update_dataset(job.dataset_id, first_block=first, last_block=last)
        first, last = detail["range"]
        total = last - first + 1
        size = adapter.chunk_blocks
        chunks = [(a, min(a + size - 1, last)) for a in range(first, last + 1, size)]
        done = set(detail.get("done_chunks", []))
        rows_total = int(detail.get("rows", 0))
        failed = list(detail.get("failed_blocks", []))
        blocks_done = sum(chunks[i][1] - chunks[i][0] + 1 for i in done if i < len(chunks))

        def report(extra_blocks=0, extra_rows=0):
            msg = f"{blocks_done + extra_blocks:,} of {total:,} {unit} · {rows_total + extra_rows:,} transactions"
            if failed:
                msg += f" · {len(failed)} {unit} failed"
            update_job(job.id, detail=detail, progress=(blocks_done + extra_blocks) / total, message=msg)

        for i, (a, b) in enumerate(chunks):
            if i in done:
                continue
            if is_cancelled(job.id):
                return
            buffer, chunk_rows, chunk_blocks, last_report = [], 0, 0, time.monotonic()
            for n, rows, err in fetch_blocks(adapter, a, b, job.dataset_id, chain.workers):
                chunk_blocks += 1
                if err is not None:
                    failed = (failed + [n])[:1000]
                elif rows:
                    buffer.extend(rows)
                    chunk_rows += len(rows)
                if len(buffer) >= settings.insert_batch_rows:          # stream rows out; memory stays flat
                    _insert_rows(ch, buffer)
                    buffer = []
                if time.monotonic() - last_report > 3:
                    report(chunk_blocks, chunk_rows)
                    last_report = time.monotonic()
            _insert_rows(ch, buffer)
            rows_total += chunk_rows
            blocks_done += b - a + 1
            done.add(i)
            detail.update(done_chunks=sorted(done), rows=rows_total, failed_blocks=failed)
            report()
    finally:
        adapter.close()

    _finish_dataset(job.dataset_id, rows_total)
    if p.get("run_analytics", True) and rows_total:
        _queue_follow_up_analytics(job.dataset_id, [chain.key])
    if rows_total:
        from app.scam.tasks import queue_after_fetch      # scam tracing: token enrichment (registration)
        queue_after_fetch(job.dataset_id, chain.key)


# ---------------------------------------------------------------------------
# 2. load an uploaded data dump
# ---------------------------------------------------------------------------
@celery.task(name="load_upload")
def load_upload_task(job_id: int) -> None:
    _run_job(job_id, _load_upload)


def _load_upload(job: Job) -> None:
    p = job.params
    with SessionLocal() as s:
        up = s.get(Upload, p["upload_id"])
        valid = {c.key for c in s.query(Chain).filter(Chain.enabled.is_(True))}
        decimals = {c.key: c.decimals for c in s.query(Chain)}
    if up is None:
        raise ValueError("upload not found")
    opts = dict(p)
    opts["decimals"] = decimals.get(p.get("chain") or "", 18)
    update_dataset(job.dataset_id, status="loading")
    ch = new_client()
    rejects_path = up.path + ".rejects.csv"
    if os.path.exists(rejects_path):
        os.remove(rejects_path)
    loaded = rejected = 0
    estimated = max(int(p.get("estimated_rows") or 0), 1)
    chains_seen: set[str] = set()
    for chunk in dump.read_chunks(up.path, up.format):
        if is_cancelled(job.id):
            return
        clean, bad = dump.normalise(chunk, opts, job.dataset_id, valid)
        if len(clean):
            ch.insert_df("transactions", clean)
            chains_seen.update(clean["chain"].unique().tolist())
        if len(bad):
            bad.to_csv(rejects_path, mode="a", header=not os.path.exists(rejects_path), index=False)
        loaded += len(clean)
        rejected += len(bad)
        update_job(job.id, progress=min(0.99, (loaded + rejected) / estimated),
                   message=f"{loaded:,} rows loaded · {rejected:,} rejected",
                   detail={"loaded": loaded, "rejected": rejected, "rejects_file": rejects_path if rejected else None})
    with SessionLocal() as s:
        ds = s.get(Dataset, job.dataset_id)
        ds.chains = sorted(chains_seen)
        s.commit()
    _finish_dataset(job.dataset_id, loaded)
    if loaded == 0:
        raise ValueError(f"no valid rows - {rejected:,} rejected; check the column mapping and units")
    if p.get("run_analytics", True):
        _queue_follow_up_analytics(job.dataset_id, sorted(chains_seen))


# ---------------------------------------------------------------------------
# 3. analytics run
# ---------------------------------------------------------------------------
@celery.task(name="analytics")
def analytics_task(job_id: int) -> None:
    _run_job(job_id, _analytics)


def _analytics(job: Job) -> None:
    with SessionLocal() as s:
        run = s.get(AnalyticsRun, job.run_id)
        whale = {c.key: c.whale_threshold for c in s.query(Chain)}
    update_run(run.id, status="running")
    scope = engine.Scope(run_id=run.id, chains=list(run.chains), dataset_id=run.dataset_id,
                         time_from=run.time_from, time_to=run.time_to)
    result = engine.run(scope, whale=whale, k=int(run.settings.get("kmeans_k", settings.kmeans_k)),
                        anomaly_z=float(run.settings.get("anomaly_z", settings.anomaly_z)),
                        progress=lambda frac, msg: update_job(job.id, progress=frac, message=msg))
    update_run(run.id, status="succeeded", finished_at=now(), **result)
    update_job(job.id, message=f"{result['transactions']:,} transactions · {result['wallets']:,} wallets analysed")
    from app.scam.tasks import queue_after_analytics      # scam tracing: detectors after analytics (registration)
    queue_after_analytics(run.id, list(run.chains), run.dataset_id)


# ---------------------------------------------------------------------------
# 4. live sync (beat, every minute) - keeps chains with autosync on up to date
# ---------------------------------------------------------------------------
@celery.task(name="sync_chains")
def sync_chains() -> None:
    lock = redis.Redis.from_url(settings.redis_url).lock("chainlens:sync", timeout=600, blocking=False)
    if not lock.acquire(blocking=False):
        return                                           # previous tick still running
    try:
        with SessionLocal() as s:
            chains = s.query(Chain).filter(Chain.enabled.is_(True), Chain.autosync.is_(True)).all()
        for chain in chains:
            try:
                _sync_chain(chain)
            except Exception:
                log.error("sync %s failed\n%s", chain.key, traceback.format_exc())
    finally:
        lock.release()


def _sync_chain(chain: Chain) -> None:
    if not settings.nownodes_api_key:
        return
    with SessionLocal() as s:
        ds = s.query(Dataset).filter(Dataset.source_type == "sync", Dataset.name == f"{chain.name} live sync").first()
        if ds is None:
            ds = Dataset(name=f"{chain.name} live sync", source_type="sync", chains=[chain.key], status="loading")
            s.add(ds)
            s.commit()
        dataset_id, last_synced = ds.id, ds.last_block
    adapter = get_adapter(chain, settings.nownodes_api_key, settings.nownodes_auth_mode)
    # keep one tick to about a minute: slow chains (Bitcoin, Solana blocks take tens of seconds) fetch fewer per tick
    per_block = max(chain.fetch_latency_s / max(chain.workers, 1), 1 / max(chain.rate_limit_rps, 0.1))
    cap = max(1, min(settings.sync_max_blocks_per_tick, int(60 / per_block)))
    ch = new_client()
    count = 0
    try:
        tip = adapter.latest_height()
        first = (last_synced + 1) if last_synced else tip - min(10, cap)
        last = min(tip, first + cap - 1)
        if last < first:
            return
        buffer = []
        for _, rows, _ in fetch_blocks(adapter, first, last, dataset_id, chain.workers):
            if rows:
                buffer.extend(rows)
                count += len(rows)
            if len(buffer) >= settings.insert_batch_rows:
                _insert_rows(ch, buffer)
                buffer = []
        _insert_rows(ch, buffer)
    finally:
        adapter.close()
    with SessionLocal() as s:
        ds = s.get(Dataset, dataset_id)
        ds.first_block = ds.first_block or first
        ds.last_block = last
        ds.row_count = (ds.row_count or 0) + count
        ds.status = "ready"
        ds.time_to = datetime.now(timezone.utc)
        s.commit()

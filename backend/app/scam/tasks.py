"""Background jobs for scam tracing: enrich_tokens and scam_detect.
They reuse the existing job wrapper, so progress, cancel and retry work like every other job."""

from app.config import settings
from app.db.clickhouse import new_client
from app.db.models import Chain, Dataset, Job
from app.db.postgres import SessionLocal
from app.ingest.adapters import get_adapter
from app.jobs.celery_app import celery
from app.jobs.progress import is_cancelled, update_job
from app.jobs.tasks import _run_job
from app.scam.config import get_scam_settings

JOB_TYPES = ("enrich_tokens", "scam_detect")


def enqueue_scam_job(job: Job) -> bool:
    """Called by the existing enqueue() for the new job types. Returns False for other types."""
    task = {"enrich_tokens": enrich_tokens_task, "scam_detect": scam_detect_task}.get(job.type)
    if task is None:
        return False
    task.delay(job.id)
    return True


def create_job(db, job_type: str, params: dict, dataset_id: int | None = None, run_id: int | None = None) -> Job:
    job = Job(type=job_type, dataset_id=dataset_id, run_id=run_id, params=params, message="Waiting to start")
    db.add(job)
    db.commit()
    return job


# ---------------------------------------------------------------------------
# enrich_tokens: ERC-20 transfers + approvals for a block range (EVM chains)
# ---------------------------------------------------------------------------
@celery.task(name="enrich_tokens")
def enrich_tokens_task(job_id: int) -> None:
    _run_job(job_id, _enrich)


def dataset_block_range(dataset_id: int, chain: str) -> tuple[int, int] | None:
    lo, hi, n = new_client().query(
        "SELECT min(block_number), max(block_number), count() FROM transactions WHERE dataset_id = {d:UInt64} AND chain = {c:String}",
        parameters={"d": dataset_id, "c": chain}).result_rows[0]
    return (int(lo), int(hi)) if n else None


def _enrich(job: Job) -> None:
    from app.scam.tokens import TokenEnricher

    p, detail = job.params, dict(job.detail or {})
    with SessionLocal() as s:
        chain = s.get(Chain, p["chain"])
    if chain is None or chain.family != "evm":
        raise ValueError("Token enrichment works on EVM chains only (Ethereum, EthereumPoW, Ethereum Classic).")
    if not settings.nownodes_api_key:
        raise RuntimeError("NOWNODES_API_KEY is not set on the server - add it to .env and restart")
    if "range" not in detail:
        if p.get("dataset_id"):
            rng = dataset_block_range(int(p["dataset_id"]), chain.key)
            if rng is None:
                raise ValueError("The dataset has no transactions for this chain.")
        else:
            rng = (int(p["from_block"]), int(p["to_block"]))
        detail["range"] = list(rng)
        update_job(job.id, detail=detail)
    first, last = detail["range"]
    size = get_scam_settings().enrich_chunk_blocks
    chunks = [(a, min(a + size - 1, last)) for a in range(first, last + 1, size)]
    done = set(detail.get("done_chunks", []))
    totals = detail.get("totals", {"transfers": 0, "approvals": 0})
    adapter = get_adapter(chain, settings.nownodes_api_key, settings.nownodes_auth_mode)
    try:
        enricher = TokenEnricher(adapter, chain.key)
        source = p.get("source", "api")
        for i, (a, b) in enumerate(chunks):
            if i in done:
                continue
            if is_cancelled(job.id):
                return
            t, ap = enricher.enrich_range(a, b, int(p.get("dataset_id") or 0), source)
            totals["transfers"] += t
            totals["approvals"] += ap
            done.add(i)
            detail.update(done_chunks=sorted(done), totals=totals)
            update_job(job.id, detail=detail, progress=len(done) / len(chunks),
                       message=f"{min(len(done) * size, last - first + 1):,} of {last - first + 1:,} blocks · "
                               f"{totals['transfers']:,} token transfers · {totals['approvals']:,} approvals")
    finally:
        adapter.close()


# ---------------------------------------------------------------------------
# scam_detect: detectors D1-D10 + wallet risk for one analytics run
# ---------------------------------------------------------------------------
WAIT_SECONDS, MAX_WAITS = 20, 90                  # wait up to 30 minutes for token enrichment to finish


@celery.task(name="scam_detect")
def scam_detect_task(job_id: int) -> None:
    # token-based detectors need the enrichment of the same chain to be finished first
    with SessionLocal() as s:
        job = s.get(Job, job_id)
        if job is not None and job.status == "queued":
            waits = int((job.detail or {}).get("waits", 0))
            if waits < MAX_WAITS and enrichment_pending(s, list(job.params.get("chains") or [])):
                update_job(job_id, detail={"waits": waits + 1}, message="Waiting for token enrichment to finish")
                scam_detect_task.apply_async((job_id,), countdown=WAIT_SECONDS)
                return
    _run_job(job_id, _detect)


def _detect(job: Job) -> None:
    from app.scam.runner import run_detection

    run_detection(job)


def enrichment_pending(db, chains: list[str]) -> bool:
    return db.query(Job).filter(Job.type == "enrich_tokens", Job.status.in_(("queued", "running"))).filter(
        Job.params["chain"].astext.in_(chains)).count() > 0


def queue_after_analytics(run_id: int, chains: list[str], dataset_id: int | None) -> None:
    """Hook called when an analytics run succeeds: queue scam detection for its chains."""
    supported = _scam_chains(chains)
    if not supported:
        return
    with SessionLocal() as s:
        job = create_job(s, "scam_detect", {"chains": supported}, dataset_id=dataset_id, run_id=run_id)
    enqueue_scam_job(job)


def queue_after_fetch(dataset_id: int, chain_key: str) -> None:
    """Hook called when a fetch finishes: queue token enrichment for that dataset on EVM chains."""
    if not _evm_chains([chain_key]):
        return
    with SessionLocal() as s:
        job = create_job(s, "enrich_tokens", {"chain": chain_key, "dataset_id": dataset_id}, dataset_id=dataset_id)
    enqueue_scam_job(job)


DETECT_FAMILIES = ("evm", "utxo", "solana")


def _scam_chains(chains: list[str]) -> list[str]:
    """Chains the detectors support (all three families; D6/D8 are skipped where they cannot apply)."""
    with SessionLocal() as s:
        families = {c.key: c.family for c in s.query(Chain)}
    return [c for c in chains if families.get(c) in DETECT_FAMILIES]


def _evm_chains(chains: list[str]) -> list[str]:
    with SessionLocal() as s:
        families = {c.key: c.family for c in s.query(Chain)}
    return [c for c in chains if families.get(c) == "evm"]


def dataset_of(job: Job) -> Dataset | None:
    if not job.dataset_id:
        return None
    with SessionLocal() as s:
        return s.get(Dataset, job.dataset_id)

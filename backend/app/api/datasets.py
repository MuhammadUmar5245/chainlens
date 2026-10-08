from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.uploads import estimate_rows
from app.config import settings
from app.db.clickhouse import get_ch
from app.db.models import Chain, Dataset, Job, Upload
from app.db.postgres import get_db
from app.ingest.upload import REQUIRED
from app.jobs.tasks import enqueue
from app.schemas import DatasetOut, FetchRequest, FromUploadRequest, JobOut

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("", response_model=list[DatasetOut])
def list_datasets(db: Session = Depends(get_db)):
    return db.query(Dataset).order_by(Dataset.id.desc()).limit(200).all()


@router.post("/fetch", response_model=JobOut, status_code=202)
def fetch(body: FetchRequest, db: Session = Depends(get_db)):
    chain = db.get(Chain, body.chain)
    if chain is None or not chain.enabled:
        raise HTTPException(400, f"Chain '{body.chain}' is unknown or disabled.")
    if not settings.nownodes_api_key:
        raise HTTPException(400, "NOWNODES_API_KEY is not set on the server. Add it to .env and restart the stack.")
    if body.mode == "last_blocks" and not body.blocks:
        raise HTTPException(422, "Give the number of blocks.")
    if body.mode == "last_hours":
        if not body.hours:
            raise HTTPException(422, "Give the number of hours.")
        if body.hours > settings.history_days * 24:
            raise HTTPException(422, f"History is kept for {settings.history_days} days, so at most {settings.history_days * 24} hours.")
    if body.mode == "range" and (body.from_block is None or body.to_block is None or body.to_block < body.from_block):
        raise HTTPException(422, "Give a valid block range (to_block must be at or after from_block).")

    label = {"last_blocks": f"last {body.blocks:,} blocks" if body.blocks else "",
             "last_hours": f"last {body.hours} hours" if body.hours else "",
             "range": f"blocks {body.from_block}-{body.to_block}"}[body.mode]
    ds = Dataset(name=body.name or f"{chain.name} · {label}", source_type="api", chains=[chain.key],
                 params=body.model_dump(), status="pending")
    db.add(ds)
    db.flush()
    job = Job(type="fetch", dataset_id=ds.id, params=body.model_dump(), message="Waiting to start")
    db.add(job)
    db.commit()
    enqueue(job)
    return job


@router.post("/from-upload", response_model=JobOut, status_code=202)
def from_upload(body: FromUploadRequest, db: Session = Depends(get_db)):
    up = db.get(Upload, body.upload_id)
    if up is None:
        raise HTTPException(404, "Upload not found. Upload the file again.")
    missing = [f for f in REQUIRED if not body.mapping.get(f)]
    if missing:
        raise HTTPException(422, f"Map these required fields: {', '.join(missing)}.")
    unknown = [c for c in body.mapping.values() if c and c not in up.columns]
    if unknown:
        raise HTTPException(422, f"These columns are not in the file: {', '.join(unknown)}.")
    if body.chain:
        chain = db.get(Chain, body.chain)
        if chain is None or not chain.enabled:
            raise HTTPException(400, f"Chain '{body.chain}' is unknown or disabled.")
    elif not body.mapping.get("chain"):
        raise HTTPException(422, "Pick one chain for the whole file, or map a column that holds the chain.")

    ds = Dataset(name=body.name or up.filename, source_type="upload", chains=[body.chain] if body.chain else [],
                 params={"upload_id": up.id, "filename": up.filename}, status="pending")
    db.add(ds)
    db.flush()
    params = body.model_dump() | {"estimated_rows": estimate_rows(up)}
    job = Job(type="load_upload", dataset_id=ds.id, params=params, message="Waiting to start")
    db.add(job)
    db.commit()
    enqueue(job)
    return job


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, db: Session = Depends(get_db)):
    ds = db.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "Dataset not found.")
    get_ch().command("ALTER TABLE transactions DELETE WHERE dataset_id = {d:UInt64}", parameters={"d": dataset_id})
    db.delete(ds)
    db.commit()

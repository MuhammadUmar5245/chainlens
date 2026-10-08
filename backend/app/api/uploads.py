import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Upload
from app.db.postgres import get_db
from app.ingest import upload as dump
from app.schemas import UploadOut

router = APIRouter(prefix="/uploads", tags=["uploads"])


def estimate_rows(up: Upload) -> int:
    """Rough row count from file size and the preview rows (used only for the progress bar)."""
    if not up.preview:
        return 0
    sample_bytes = sum(len(",".join(str(v) for v in row.values())) + 1 for row in up.preview)
    per_row = max(sample_bytes / len(up.preview), 1)
    return int(up.size_bytes / per_row)


@router.post("", response_model=UploadOut, status_code=201)
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    fmt = dump.detect_format(file.filename or "")
    if fmt is None:
        raise HTTPException(415, "Use CSV, Parquet, JSON Lines (.jsonl) or Excel (.xlsx).")
    os.makedirs(settings.upload_dir, exist_ok=True)
    uid = uuid.uuid4().hex
    path = os.path.join(settings.upload_dir, f"{uid}{os.path.splitext(file.filename)[1].lower()}")
    limit = int(settings.max_upload_gb * 1024 ** 3)
    size = 0
    with open(path, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                out.close()
                os.remove(path)
                raise HTTPException(413, f"File is larger than {settings.max_upload_gb:g} GB.")
            out.write(chunk)
    try:
        columns, rows = dump.preview(path, fmt)
    except Exception as e:
        os.remove(path)
        raise HTTPException(422, f"Could not read the file as {fmt}: {e}") from e
    if not columns:
        os.remove(path)
        raise HTTPException(422, "The file has no columns.")
    up = Upload(id=uid, filename=file.filename, size_bytes=size, path=path, format=fmt, columns=columns, preview=rows)
    db.add(up)
    db.commit()
    out = UploadOut.model_validate(up)
    out.suggested = dump.suggest_mapping(columns)
    out.estimated_rows = estimate_rows(up)
    return out

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.ingest.base import norm_id
from app.scam import labels as L
from app.scam.models import CATEGORIES, AddressLabel

router = APIRouter(prefix="/labels", tags=["scam tracing"])


@router.get("")
def list_labels(chain: str | None = None, category: str | None = None, source: str | None = None,
                q: str | None = None, page: int = Query(1, ge=1), limit: int = Query(100, ge=1, le=500),
                db: Session = Depends(get_db)):
    query = db.query(AddressLabel)
    if chain:
        query = query.filter(AddressLabel.chain == chain)
    if category:
        query = query.filter(AddressLabel.category == category)
    if source:
        query = query.filter(AddressLabel.source == source)
    if q:
        query = query.filter(AddressLabel.address.startswith(norm_id(q)) | AddressLabel.label.ilike(f"%{q}%"))
    total = query.count()
    rows = query.order_by(AddressLabel.chain, AddressLabel.category, AddressLabel.address).offset((page - 1) * limit).limit(limit).all()
    sources = [{"source": s, "count": n} for s, n in
               db.query(AddressLabel.source, func.count()).group_by(AddressLabel.source).order_by(AddressLabel.source)]
    return {
        "total": total, "categories": list(CATEGORIES), "sources": sources,
        "rows": [{"id": r.id, "chain": r.chain, "address": r.address, "label": r.label, "category": r.category,
                  "source": r.source, "added_at": r.added_at} for r in rows],
    }


@router.post("/import")
async def import_labels(file: UploadFile = File(...), source: str = Form(""), chain: str = Form("eth"),
                        db: Session = Depends(get_db)):
    text = (await file.read()).decode("utf-8", errors="replace")
    try:
        return L.import_csv(db, text, default_source=source or (file.filename or "upload"), default_chain=chain)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/test-set")
def load_test_set(db: Session = Depends(get_db)):
    """MVP only: loads a few clearly marked TEST labels taken from the sample data."""
    return L.load_test_labels(db) | {"source": L.TEST_SOURCE}


@router.delete("")
def remove_by_source(source: str, db: Session = Depends(get_db)):
    if source == "builtin":
        raise HTTPException(400, "Built-in token labels cannot be removed here.")
    return {"removed": L.remove_source(db, source)}

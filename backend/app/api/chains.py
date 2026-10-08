from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Chain
from app.db.postgres import get_db
from app.schemas import ChainOut, ChainUpdate

router = APIRouter(prefix="/chains", tags=["chains"])


@router.get("", response_model=list[ChainOut])
def list_chains(db: Session = Depends(get_db)):
    return db.query(Chain).order_by(Chain.sort_order).all()


@router.patch("/{key}", response_model=ChainOut)
def update_chain(key: str, body: ChainUpdate, db: Session = Depends(get_db)):
    chain = db.get(Chain, key)
    if chain is None:
        raise HTTPException(404, f"Unknown chain: {key}")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(chain, field, value)
    db.commit()
    return chain

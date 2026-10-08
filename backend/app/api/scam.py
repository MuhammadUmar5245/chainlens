from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Chain, Dataset
from app.db.postgres import get_db
from app.scam.tasks import create_job, enqueue_scam_job
from app.schemas import JobOut

router = APIRouter(prefix="/scam", tags=["scam tracing"])


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

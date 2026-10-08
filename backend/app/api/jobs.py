from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import Job
from app.db.postgres import get_db
from app.jobs.tasks import enqueue
from app.schemas import JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    return db.query(Job).order_by(Job.id.desc()).limit(limit).all()


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    if job.status == "queued":
        job.status = "cancelled"
    elif job.status == "running":
        job.status = "cancelling"          # the worker stops at its next checkpoint
    else:
        raise HTTPException(409, f"Job is already {job.status}.")
    db.commit()
    return job


@router.post("/{job_id}/retry", response_model=JobOut)
def retry(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(409, f"Only failed or cancelled jobs can be retried; this one is {job.status}.")
    job.status, job.error, job.finished_at, job.message = "queued", None, None, "Retrying from the last checkpoint"
    db.commit()
    enqueue(job)
    return job

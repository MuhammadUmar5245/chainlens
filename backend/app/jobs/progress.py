"""Small helpers so workers can report job state to PostgreSQL from anywhere."""

from datetime import datetime, timezone

from sqlalchemy import update

from app.db.models import AnalyticsRun, Dataset, Job
from app.db.postgres import SessionLocal


def now():
    return datetime.now(timezone.utc)


def get_job(job_id: int) -> Job | None:
    with SessionLocal() as s:
        return s.get(Job, job_id)


def update_job(job_id: int, **values) -> None:
    with SessionLocal() as s:
        s.execute(update(Job).where(Job.id == job_id).values(**values))
        s.commit()


def update_dataset(dataset_id: int, **values) -> None:
    with SessionLocal() as s:
        s.execute(update(Dataset).where(Dataset.id == dataset_id).values(**values))
        s.commit()


def update_run(run_id: int, **values) -> None:
    with SessionLocal() as s:
        s.execute(update(AnalyticsRun).where(AnalyticsRun.id == run_id).values(**values))
        s.commit()


def is_cancelled(job_id: int) -> bool:
    job = get_job(job_id)
    return job is None or job.status in ("cancelling", "cancelled")

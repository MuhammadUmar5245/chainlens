from celery import Celery

from app.config import settings

celery = Celery("chainlens", broker=settings.redis_url, backend=settings.redis_url, include=["app.jobs.tasks", "app.scam.tasks"])
celery.conf.update(
    task_acks_late=True,                 # a job interrupted by a worker restart is picked up again
    worker_prefetch_multiplier=1,        # long jobs: take one at a time
    task_track_started=True,
    timezone="UTC",
    beat_schedule={
        "sync-chains": {"task": "sync_chains", "schedule": 60.0},   # only chains with autosync on
    },
)

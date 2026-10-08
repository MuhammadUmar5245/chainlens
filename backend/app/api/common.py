"""Shared filter handling for the analytics and wallet endpoints."""

from fastapi import HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import AnalyticsRun


def resolve_run(db: Session, run_id: int | None) -> AnalyticsRun:
    run = db.get(AnalyticsRun, run_id) if run_id else (
        db.query(AnalyticsRun).filter(AnalyticsRun.status == "succeeded").order_by(AnalyticsRun.id.desc()).first())
    if run is None:
        raise HTTPException(404, "No analytics results yet. Fetch data or upload a file, and analytics runs automatically.")
    if run.status != "succeeded":
        raise HTTPException(409, f"Analytics run {run.id} is {run.status}.")
    return run


def chains_param(chains: str | None = Query(None, description="Comma-separated chain keys, e.g. eth,bsc")) -> list[str] | None:
    if not chains:
        return None
    return [c.strip() for c in chains.split(",") if c.strip()]


def pick_chains(run: AnalyticsRun, requested: list[str] | None) -> list[str]:
    """Requested chains that the run covers; all of the run's chains when none are requested.
    May be empty when the filter and the run do not overlap - endpoints then return no rows."""
    if not requested:
        return list(run.chains)
    return [c for c in requested if c in run.chains]

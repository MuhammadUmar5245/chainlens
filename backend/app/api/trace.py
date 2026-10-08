from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.scam.config import get_scam_settings
from app.scam.trace import Tracer

router = APIRouter(prefix="/trace", tags=["scam tracing"])


def _run_trace(chain, address, depth, direction, time_from, time_to, run_id):
    cfg = get_scam_settings()
    if depth is not None and not (1 <= depth <= cfg.trace_max_depth):
        raise HTTPException(422, f"depth must be between 1 and {cfg.trace_max_depth}")
    try:
        return Tracer(chain, run_id).trace(address, depth, direction, time_from, time_to)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/{chain}/{address}")
def trace(chain: str, address: str, depth: int | None = Query(None), direction: str = "both",
          time_from: datetime | None = None, time_to: datetime | None = None, run_id: int | None = None):
    """Profile, counterparties, first funder, exit points, money-flow graph, timeline and findings for one wallet."""
    return _run_trace(chain, address, depth, direction, time_from, time_to, run_id)


@router.get("/{chain}/{address}/export.xlsx")
def trace_export(chain: str, address: str, depth: int | None = Query(None), direction: str = "both",
                 time_from: datetime | None = None, time_to: datetime | None = None, run_id: int | None = None):
    from app.scam.export import trace_workbook
    t = _run_trace(chain, address, depth, direction, time_from, time_to, run_id)
    return Response(trace_workbook(t), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="trace_{t["address"][:12]}.xlsx"'})

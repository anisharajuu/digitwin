"""Risk-ranked work orders, and executing the work."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..domain.models import MaintenanceRequest, WorkOrder
from ..simulation.engine import TwinEngine
from .deps import get_engine

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("/work-orders", response_model=list[WorkOrder], summary="Work-order queue")
def work_orders(engine: TwinEngine = Depends(get_engine)) -> list[WorkOrder]:
    """Pending interventions, ranked by risk rather than by due date.

    A low-criticality asset failing next week can legitimately rank below a
    critical one failing next month; sorting by date alone hides that.
    """
    return engine.work_orders()


@router.post("/perform", summary="Perform maintenance")
def perform(
    request: MaintenanceRequest, engine: TwinEngine = Depends(get_engine)
) -> dict[str, Any]:
    """Restore one wear mode (or every mode) on an asset to as-new.

    The asset is held in a MAINTENANCE state for the work's duration, so the
    availability cost lands in OEE instead of being free.
    """
    try:
        return engine.perform_maintenance(request.asset_id, request.mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

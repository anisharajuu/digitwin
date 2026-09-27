"""Alert feed and acknowledgement."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..domain.models import Alert
from ..simulation.engine import TwinEngine
from .deps import get_engine

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=list[Alert], summary="Alert feed")
def list_alerts(
    include_cleared: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    engine: TwinEngine = Depends(get_engine),
) -> list[Alert]:
    return engine.alerts(limit=limit, include_cleared=include_cleared)


@router.post("/alerts/{alert_id}/acknowledge", response_model=Alert, summary="Acknowledge")
def acknowledge(alert_id: str, engine: TwinEngine = Depends(get_engine)) -> Alert:
    alert = engine.anomaly.acknowledge(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"no alert '{alert_id}'")
    return alert

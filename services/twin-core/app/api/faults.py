"""Fault injection: drive a named failure mode and watch the twin react."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..domain.models import FaultRequest
from ..simulation.engine import TwinEngine
from ..simulation.faults import CATALOGUE
from .deps import get_engine

router = APIRouter(prefix="/faults", tags=["faults"])


@router.get("/catalogue", summary="Injectable fault catalogue")
def catalogue() -> list[dict[str, Any]]:
    return [
        {
            "id": spec.id,
            "label": spec.label,
            "mode": spec.mode,
            "kinds": list(spec.kinds),
            "description": spec.description,
            "symptom": spec.symptom,
        }
        for spec in CATALOGUE
    ]


@router.get("", summary="Active faults")
def active(engine: TwinEngine = Depends(get_engine)) -> list[dict[str, Any]]:
    return [f.as_dict() for f in engine.faults.active.values()]


@router.post("", summary="Inject a fault")
def inject(request: FaultRequest, engine: TwinEngine = Depends(get_engine)) -> dict[str, Any]:
    """Begin driving a failure mechanism into an asset.

    The fault raises a degradation *rate*, ramped in over ``ramp_hours``. It
    never writes a sensor value directly, so every symptom that follows is
    produced by the physics rather than asserted.
    """
    try:
        fault = engine.inject_fault(
            request.asset_id, request.mode, request.severity, request.ramp_hours
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return fault.as_dict()


@router.delete("/{fault_id}", summary="Clear a fault")
def clear(fault_id: str, engine: TwinEngine = Depends(get_engine)) -> dict[str, Any]:
    """Stop driving the fault. Wear already accumulated is not undone -
    that is what maintenance is for."""
    if not engine.clear_fault(fault_id):
        raise HTTPException(status_code=404, detail=f"no active fault '{fault_id}'")
    return {"cleared": fault_id}

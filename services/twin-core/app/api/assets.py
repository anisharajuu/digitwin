"""Plant topology and per-asset state."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..domain.models import AssetInfo, Frame, Plant
from ..simulation.engine import TwinEngine
from ..simulation.faults import catalogue_for
from .deps import get_engine

router = APIRouter(tags=["plant"])


@router.get("/plant", response_model=Plant, summary="As-designed plant registry")
def get_plant(engine: TwinEngine = Depends(get_engine)) -> Plant:
    """Topology, areas and nameplate data. Static - fetch once and cache."""
    return engine.plant()


@router.get("/frame", response_model=Frame, summary="Current plant state")
def get_frame(engine: TwinEngine = Depends(get_engine)) -> Frame:
    """The latest tick. Identical to what the WebSocket stream pushes."""
    return engine.frame()


@router.get("/assets", response_model=list[AssetInfo], summary="List assets")
def list_assets(engine: TwinEngine = Depends(get_engine)) -> list[AssetInfo]:
    return [rt.info for rt in engine.assets.values()]


@router.get("/assets/{asset_id}", summary="Asset detail")
def get_asset(asset_id: str, engine: TwinEngine = Depends(get_engine)) -> dict[str, Any]:
    """Everything about one asset: nameplate, live state, wear, and the fault
    modes that can be injected into it."""
    rt = engine.assets.get(asset_id)
    if rt is None:
        raise HTTPException(status_code=404, detail=f"no asset '{asset_id}'")

    frame = engine.frame()
    return {
        "info": rt.info,
        "snapshot": frame.assets.get(asset_id),
        "degradation_detail": [
            {
                "name": name,
                "label": mode.spec.label,
                "level": round(mode.level, 5),
                "threshold": mode.spec.threshold,
                "action": mode.spec.action,
                "effect": mode.spec.effect,
                "downtime_h": mode.spec.downtime_h,
                "cost_eur": mode.spec.cost_eur,
            }
            for name, mode in rt.degradation.modes.items()
        ],
        "injectable_faults": [
            {
                "id": spec.id,
                "label": spec.label,
                "mode": spec.mode,
                "description": spec.description,
                "symptom": spec.symptom,
            }
            for spec in catalogue_for(rt.info.kind)
        ],
        "active_faults": [f.as_dict() for f in engine.faults.for_asset(asset_id)],
    }

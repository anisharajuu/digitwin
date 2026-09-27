"""Historical tag data, with the model's prediction alongside every sample."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..domain.models import TelemetryPoint, TelemetrySeries
from ..simulation.engine import TwinEngine
from .deps import get_engine

router = APIRouter(tags=["telemetry"])


@router.get(
    "/assets/{asset_id}/telemetry",
    response_model=list[TelemetrySeries],
    summary="Tag history with model prediction",
)
def get_telemetry(
    asset_id: str,
    tags: str | None = Query(
        default=None, description="Comma-separated tag names. Omit for every tag."
    ),
    points: int = Query(default=360, ge=2, le=3600, description="Samples to return."),
    engine: TwinEngine = Depends(get_engine),
) -> list[TelemetrySeries]:
    """Return recent samples for one or more tags.

    Each series carries the observed values *and* what the as-new model
    predicted at the same instants, so a chart can draw both without a second
    round trip. That overlay is the single most useful view in the console:
    the gap between the two lines is the fault, visible long before either
    line crosses an alarm limit.
    """
    rt = engine.assets.get(asset_id)
    if rt is None:
        raise HTTPException(status_code=404, detail=f"no asset '{asset_id}'")

    wanted = (
        [t.strip() for t in tags.split(",") if t.strip()]
        if tags
        else [tag.name for tag in rt.tags.values()]
    )

    out: list[TelemetrySeries] = []
    for name in wanted:
        tag = rt.tags.get(name)
        if tag is None:
            raise HTTPException(status_code=404, detail=f"{asset_id} has no tag '{name}'")
        series = engine.store.get(asset_id, name)
        if series is None:
            continue
        times, values, expected = series.tail(points)
        out.append(
            TelemetrySeries(
                asset_id=asset_id,
                tag=name,
                spec=tag.spec(),
                points=[
                    TelemetryPoint(t=t, v=round(v, 5))
                    # tail() returns equal-length rings by construction.
                    for t, v in zip(times, values, strict=False)
                ],
                expected=[
                    TelemetryPoint(t=t, v=round(v, 5))
                    for t, v in zip(times, expected, strict=False)
                ],
            )
        )
    return out

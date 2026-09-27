"""Engine wiring. One twin per process, created during application startup."""

from __future__ import annotations

from fastapi import HTTPException, Request

from ..simulation.engine import TwinEngine
from ..simulation.scenarios import ScenarioRunner


def get_engine(request: Request) -> TwinEngine:
    engine: TwinEngine | None = getattr(request.app.state, "engine", None)
    if engine is None:  # pragma: no cover - only reachable if startup failed
        raise HTTPException(status_code=503, detail="twin is still starting")
    return engine


def get_runner(request: Request) -> ScenarioRunner:
    return ScenarioRunner(get_engine(request))

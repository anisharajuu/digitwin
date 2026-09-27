"""twin-core application entry point."""

from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import alerts, assets, faults, maintenance, scenarios, stream, telemetry
from .config import settings
from .simulation.engine import TwinEngine

API_PREFIX = "/api/v1"

DESCRIPTION = """
Physics-backed digital twin of an industrial process line.

Every asset is modelled from first principles and solved twice per tick: once
carrying its accumulated wear, and once as-new under identical operating
conditions. The gap between those two runs - the **residual** - is what drives
health scores, remaining-useful-life estimates and alerts. No symptom in this
service is hard-coded; they all emerge from the models.

* `GET /api/v1/plant` - as-designed registry, fetch once
* `WS  /api/v1/stream` - live frames, one per tick
* `GET /api/v1/assets/{id}/telemetry` - history with the model overlay
* `GET /api/v1/maintenance/work-orders` - risk-ranked intervention queue
* `POST /api/v1/faults` - drive a failure mode and watch it propagate
* `POST /api/v1/scenarios/simulate` - project a change forward in euros
"""


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = TwinEngine(
        plant_file=settings.plant_file,
        dt=settings.sim_dt,
        history_points=settings.history_points,
        warmup_ticks=settings.warmup_ticks,
    )
    # Settle, then warm the detectors, before anything is served. The twin
    # answers its very first request with real history and a live detector.
    started = time.perf_counter()
    engine.prime()
    print(
        f"twin-core: primed in {(time.perf_counter() - started) * 1000:.0f} ms "
        f"({engine.tick_count} ticks, {engine.store.size()} points, "
        f"detectors ready: {engine.anomaly.ready})"
    )
    app.state.engine = engine
    app.state.started_at = time.time()
    engine.start(interval=settings.tick_seconds)
    try:
        yield
    finally:
        await engine.stop()


app = FastAPI(
    title="DigiTwin twin-core",
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    assets.router,
    telemetry.router,
    alerts.router,
    maintenance.router,
    faults.router,
    scenarios.router,
    stream.router,
):
    app.include_router(router, prefix=API_PREFIX)


@app.get("/healthz", tags=["ops"], summary="Liveness and twin vitals")
def healthz() -> dict[str, Any]:
    engine: TwinEngine | None = getattr(app.state, "engine", None)
    if engine is None:
        return {"status": "starting"}
    return {
        "status": "ok",
        "tick": engine.tick_count,
        "sim_hours": round(engine.sim_time / 3600.0, 2),
        "uptime_s": round(time.time() - getattr(app.state, "started_at", time.time()), 1),
        "assets": len(engine.assets),
        "series": engine.store.series_count(),
        "points": engine.store.size(),
        "open_alerts": len(engine.anomaly.open_alerts()),
        "active_faults": len(engine.faults.active),
        "detectors_ready": engine.anomaly.ready,
    }


@app.get(f"{API_PREFIX}/meta", tags=["ops"], summary="Runtime configuration")
def meta() -> dict[str, Any]:
    return {
        "tick_seconds": settings.tick_seconds,
        "sim_speed": settings.sim_speed,
        "sim_dt": settings.sim_dt,
        "history_points": settings.history_points,
        "warmup_ticks": settings.warmup_ticks,
    }


# Serve the built console from the same origin when it is present. Keeps the
# container single-process in production while `npm run dev` still proxies in
# development.
_CONSOLE_DIST = Path(__file__).resolve().parents[3] / "apps" / "console" / "dist"
if _CONSOLE_DIST.is_dir():  # pragma: no cover - deployment-only path
    app.mount("/assets", StaticFiles(directory=_CONSOLE_DIST / "assets"), name="console-assets")

    @app.get("/", include_in_schema=False)
    def console_index() -> FileResponse:
        return FileResponse(_CONSOLE_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def console_spa(full_path: str) -> FileResponse:
        # Client-side routing: anything that is not an API route falls
        # through to the SPA shell.
        return FileResponse(_CONSOLE_DIST / "index.html")

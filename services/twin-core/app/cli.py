"""`twin-core` console script: run the service without remembering uvicorn flags."""

from __future__ import annotations

import argparse

import uvicorn

from .config import settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="twin-core", description="Run the DigiTwin twin-core API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(
        f"twin-core: {settings.plant_file.name} @ {settings.sim_speed:g}x "
        f"({settings.sim_dt:g} simulated seconds per {settings.tick_seconds:g}s tick)"
    )
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":  # pragma: no cover
    main()

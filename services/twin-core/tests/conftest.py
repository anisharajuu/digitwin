from __future__ import annotations

from pathlib import Path

import pytest

from app.simulation.engine import TwinEngine

PLANT_FILE = Path(__file__).resolve().parents[1] / "app" / "plant" / "aurora_works.yaml"


@pytest.fixture(scope="module")
def engine() -> TwinEngine:
    """A primed twin with a short detector warm-up, shared across a module."""
    eng = TwinEngine(PLANT_FILE, dt=60.0, history_points=600, warmup_ticks=40)
    eng.prime(settle_ticks=300)
    for _ in range(120):
        eng.tick()
    return eng


@pytest.fixture
def fresh_engine() -> TwinEngine:
    """A primed twin nobody else has poked at, for tests that mutate state."""
    eng = TwinEngine(PLANT_FILE, dt=60.0, history_points=600, warmup_ticks=40)
    eng.prime(settle_ticks=300)
    for _ in range(80):
        eng.tick()
    return eng

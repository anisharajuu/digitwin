"""What-if projections."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..domain.models import ScenarioRequest, ScenarioResult
from ..simulation.scenarios import ScenarioRunner
from .deps import get_runner

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.post("/simulate", response_model=ScenarioResult, summary="Run a what-if")
def simulate(
    request: ScenarioRequest, runner: ScenarioRunner = Depends(get_runner)
) -> ScenarioResult:
    """Fork the live twin and sweep it forward under a proposed change.

    Returns the proposed case and a do-nothing baseline over the same horizon,
    plus the delta in euros, tonnes and CO2. Runs synchronously - a 30-day
    projection over ten assets lands in a few hundred milliseconds.
    """
    return runner.run(request)

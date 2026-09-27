"""What-if projections have to be fast, bounded and directionally honest."""

from __future__ import annotations

import pytest

from app.domain.models import ScenarioChange, ScenarioRequest
from app.simulation.scenarios import ScenarioRunner


def test_projection_returns_a_comparable_baseline(engine):
    result = ScenarioRunner(engine).run(
        ScenarioRequest(
            name="Do the gearbox",
            horizon_days=30,
            changes=[ScenarioChange(asset_id="AGT-301", parameter="maintain")],
        )
    )
    assert result.baseline.label == "Do nothing"
    assert result.proposed.label == "Do the gearbox"
    assert len(result.baseline.series) == len(result.proposed.series)
    assert result.baseline.series[-1].day == pytest.approx(30.0, abs=0.5)


def test_projection_is_fast_enough_to_be_interactive(engine):
    result = ScenarioRunner(engine).run(ScenarioRequest(horizon_days=60))
    assert result.compute_ms < 5_000


def test_doing_nothing_twice_gives_the_same_answer(engine):
    """A projection must not depend on hidden live state; forks are isolated."""
    runner = ScenarioRunner(engine)
    a = runner.run(ScenarioRequest(horizon_days=20))
    b = runner.run(ScenarioRequest(horizon_days=20))
    assert a.baseline.total_cost_eur == pytest.approx(b.baseline.total_cost_eur)
    assert a.baseline.total_production_t == pytest.approx(b.baseline.total_production_t)


def test_a_projection_does_not_disturb_the_live_twin(engine):
    before = {aid: dict(rt.degradation.levels()) for aid, rt in engine.assets.items()}
    ScenarioRunner(engine).run(
        ScenarioRequest(
            horizon_days=45, changes=[ScenarioChange(asset_id="P-101A", parameter="maintain")]
        )
    )
    after = {aid: dict(rt.degradation.levels()) for aid, rt in engine.assets.items()}
    assert before == after


def test_maintaining_a_degraded_asset_avoids_unplanned_outages(fresh_engine):
    engine = fresh_engine
    engine.inject_fault("AGT-301", "gear_wear", severity=0.55, ramp_hours=3.0)
    for _ in range(420):
        engine.tick()

    result = ScenarioRunner(engine).run(
        ScenarioRequest(
            name="Overhaul AGT-301",
            horizon_days=60,
            changes=[ScenarioChange(asset_id="AGT-301", parameter="maintain")],
        )
    )
    assert result.baseline.unplanned_events > result.proposed.unplanned_events
    assert result.proposed.end_health > result.baseline.end_health
    assert result.verdict.startswith("Proceed")
    assert result.delta_cost_eur > 0


def test_a_higher_reactor_setpoint_raises_yield(engine):
    """Conversion feeds the quality term, so setpoint is a real business lever."""
    runner = ScenarioRunner(engine)
    base = runner.run(ScenarioRequest(horizon_days=20))
    hotter = runner.run(
        ScenarioRequest(
            horizon_days=20,
            changes=[ScenarioChange(asset_id="RX-301", parameter="setpoint_c", value=101.0)],
        )
    )
    assert hotter.proposed.total_production_t > base.baseline.total_production_t


def test_the_verdict_declines_work_that_does_not_pay(engine):
    """Maintaining a healthy asset buys downtime and nothing else."""
    result = ScenarioRunner(engine).run(
        ScenarioRequest(
            name="Overhaul a healthy separator",
            horizon_days=15,
            changes=[ScenarioChange(asset_id="SEP-401", parameter="maintain")],
        )
    )
    assert result.delta_cost_eur < 0
    assert result.verdict.startswith("Do not proceed")


def test_series_is_downsampled_for_plotting(engine):
    result = ScenarioRunner(engine).run(ScenarioRequest(horizon_days=120, step_seconds=900))
    assert len(result.baseline.series) <= 200

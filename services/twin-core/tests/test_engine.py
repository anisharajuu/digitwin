"""End-to-end behaviour of the twin: fault in, alert out, maintenance closes it."""

from __future__ import annotations

import pytest

from app.domain.models import AssetState, Severity


def test_a_primed_plant_raises_no_false_alarms(engine):
    """The headline claim. If this ever fails, nobody will trust the feed."""
    for _ in range(300):
        frame = engine.tick()
    assert frame.alerts == []


def test_frame_is_internally_consistent(engine):
    frame = engine.frame()
    assert len(frame.assets) == len(engine.assets)
    for asset_id, snapshot in frame.assets.items():
        assert snapshot.id == asset_id
        assert 0.0 <= snapshot.health <= 100.0
        assert snapshot.values
        assert all(0.0 <= v <= 1.0 for v in snapshot.degradation.values())


def test_kpis_are_in_a_plausible_operating_envelope(engine):
    k = engine.frame().kpis
    assert 0.0 < k.oee <= 1.0
    assert 0.0 <= k.availability <= 1.0
    assert 90.0 < k.throughput_tph < 130.0
    assert 250.0 < k.power_kw < 700.0
    assert 2.0 < k.energy_intensity_kwh_t < 8.0


def test_the_reference_model_stays_pinned_to_as_new(engine):
    """Residual only means something if the reference never degrades."""
    series = engine.store.get("P-101A", "flow_m3h")
    _, _, expected = series.tail(50)
    assert expected == pytest.approx([expected[0]] * len(expected), abs=1e-6)


def test_history_is_recorded_for_every_tag(engine):
    for tag in engine.assets["P-101A"].tags:
        assert engine.store.get("P-101A", tag) is not None


def test_history_is_bounded(engine):
    series = engine.store.get("P-101A", "flow_m3h")
    assert len(series) <= engine.store.capacity


def test_fault_injection_propagates_to_alerts_and_rul(fresh_engine):
    """The full chain, which is the thing actually worth testing."""
    engine = fresh_engine
    before = engine.frame().assets["P-101A"]
    assert before.open_alerts == 0

    engine.inject_fault("P-101A", "impeller_erosion", severity=0.8, ramp_hours=3.0)
    for _ in range(420):
        frame = engine.tick()

    after = frame.assets["P-101A"]
    assert after.open_alerts > 0
    assert after.health < before.health
    assert after.values["flow_m3h"] < before.values["flow_m3h"]
    assert after.values["efficiency_pct"] < before.values["efficiency_pct"]

    wear = [r for r in after.rul if r.mode == "impeller_wear"][0]
    assert wear.hours_remaining is not None
    assert wear.hours_remaining < 24 * 30

    raised = [a for a in frame.alerts if a.asset_id == "P-101A"]
    assert any(a.severity == Severity.CRITICAL for a in raised)
    assert any(a.tag == "efficiency_pct" for a in raised)


def test_a_condition_only_fault_never_disturbs_the_process(fresh_engine):
    """A failing gearbox must show up in vibration and nowhere else."""
    engine = fresh_engine
    baseline = engine.frame().kpis.throughput_tph

    engine.inject_fault("AGT-301", "bearing_spall", severity=0.9, ramp_hours=2.0)
    for _ in range(300):
        frame = engine.tick()

    agitator = frame.assets["AGT-301"]
    assert agitator.open_alerts > 0
    assert frame.kpis.throughput_tph == pytest.approx(baseline, rel=0.02)


def test_maintenance_restores_the_asset_and_closes_its_alerts(fresh_engine):
    engine = fresh_engine
    engine.inject_fault("P-101A", "bearing_spall", severity=0.9, ramp_hours=2.0)
    for _ in range(360):
        engine.tick()
    assert engine.frame().assets["P-101A"].open_alerts > 0

    result = engine.perform_maintenance("P-101A", "bearing_wear")
    assert result["restored"] == ["bearing_wear"]
    assert result["cost_eur"] > 0

    frame = engine.tick()
    asset = frame.assets["P-101A"]
    assert asset.degradation["bearing_wear"] == 0.0
    assert asset.state == AssetState.MAINTENANCE  # downtime is not free
    assert asset.open_alerts == 0


def test_maintenance_downtime_costs_availability(fresh_engine):
    engine = fresh_engine
    before = engine.frame().kpis.availability
    engine.perform_maintenance("RX-301")
    after = engine.tick().kpis.availability
    assert after < before


def test_clearing_a_fault_does_not_undo_accumulated_wear(fresh_engine):
    engine = fresh_engine
    fault = engine.inject_fault("P-101A", "impeller_erosion", severity=0.9, ramp_hours=1.0)
    for _ in range(240):
        engine.tick()
    worn = engine.frame().assets["P-101A"].degradation["impeller_wear"]

    assert engine.clear_fault(fault.id) is True
    engine.tick()
    assert engine.frame().assets["P-101A"].degradation["impeller_wear"] >= worn


def test_work_orders_rank_by_risk_not_by_date(fresh_engine):
    engine = fresh_engine
    engine.inject_fault("RX-301", "jacket_fouling", severity=0.9, ramp_hours=2.0)
    for _ in range(400):
        engine.tick()

    orders = engine.work_orders()
    assert orders
    assert orders == sorted(orders, key=lambda o: o.risk_score, reverse=True)
    top = orders[0]
    assert top.asset_id == "RX-301"
    assert top.severity in (Severity.WARNING, Severity.CRITICAL)
    assert top.action and top.rationale


def test_unknown_asset_and_mode_are_rejected(fresh_engine):
    with pytest.raises(KeyError):
        fresh_engine.inject_fault("NOPE-1", "bearing_spall", 0.5, 1.0)
    with pytest.raises(KeyError):
        fresh_engine.perform_maintenance("P-101A", "not_a_real_mode")


def test_standby_asset_does_not_age_on_the_shelf(fresh_engine):
    engine = fresh_engine
    before = dict(engine.frame().assets["P-101B"].degradation)
    for _ in range(200):
        engine.tick()
    assert engine.frame().assets["P-101B"].degradation == before

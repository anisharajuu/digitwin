"""The detector has to be quiet on a healthy plant before it is useful on a sick one."""

from __future__ import annotations

import random

import pytest

from app.analytics.anomaly import AnomalyEngine
from app.analytics.kpis import compute
from app.analytics.rul import RulEngine
from app.domain.models import AssetState, Criticality, Severity

LABELS = {"vibration_mms": "Vibration RMS"}
UNITS = {"vibration_mms": "mm/s"}


def _run(engine: AnomalyEngine, ticks: int, *, offset=lambda i: 0.0, seed: int = 11):
    rng = random.Random(seed)
    for i in range(ticks):
        observed = 1.55 + offset(i) + rng.gauss(0.0, 0.055)
        engine.evaluate(
            "P-101A",
            "Feed Pump A",
            {"vibration_mms": observed},
            {"vibration_mms": 1.55},
            float(i),
            LABELS,
            UNITS,
        )


def test_detector_is_silent_on_healthy_noise():
    """Eight hundred samples of pure noise must not produce a single alert."""
    eng = AnomalyEngine(warmup=120)
    eng.register("P-101A", "vibration_mms", 0.055)
    _run(eng, 800)
    assert eng.open_alerts() == []


def test_detector_absorbs_a_constant_offset_during_warmup():
    """Existing wear is the baseline, not a fault. Only *changes* alarm."""
    eng = AnomalyEngine(warmup=120)
    eng.register("P-101A", "vibration_mms", 0.055)
    _run(eng, 600, offset=lambda i: 0.9)  # persistently off-model from tick zero
    assert eng.open_alerts() == []


def test_detector_catches_a_drift_below_any_alarm_threshold():
    """0.9 mm/s is far under the ISO 10816 limit, and still gets caught."""
    eng = AnomalyEngine(warmup=120)
    eng.register("P-101A", "vibration_mms", 0.055)
    _run(eng, 300)
    assert eng.open_alerts() == []
    _run(eng, 120, offset=lambda i: min(0.9, i / 60.0 * 0.9), seed=12)

    alerts = eng.open_alerts()
    assert len(alerts) == 1
    assert alerts[0].severity in (Severity.WARNING, Severity.CRITICAL)
    assert alerts[0].tag == "vibration_mms"
    assert "sigma" in alerts[0].detail


def test_a_single_spike_does_not_raise_an_alert():
    """Persistence plus EWMA smoothing is what keeps the feed survivable."""
    eng = AnomalyEngine(warmup=120)
    eng.register("P-101A", "vibration_mms", 0.055)
    _run(eng, 300)
    eng.evaluate(
        "P-101A",
        "Feed Pump A",
        {"vibration_mms": 9.9},
        {"vibration_mms": 1.55},
        301.0,
        LABELS,
        UNITS,
    )
    assert eng.open_alerts() == []


def test_alerts_clear_when_the_asset_recovers():
    eng = AnomalyEngine(warmup=120)
    eng.register("P-101A", "vibration_mms", 0.055)
    _run(eng, 300)
    _run(eng, 120, offset=lambda i: 1.2, seed=13)
    assert len(eng.open_alerts()) == 1

    _run(eng, 200, seed=14)  # back on model
    assert eng.open_alerts() == []


def test_unregistered_tags_are_never_scored():
    eng = AnomalyEngine(warmup=10)
    residuals = eng.evaluate(
        "P-101A",
        "Feed Pump A",
        {"unwatched": 1.0},
        {"unwatched": 99.0},
        1.0,
        {},
        {},
    )
    assert residuals == {}


# --------------------------------------------------------------------- RUL


def _feed(rul: RulEngine, rate_per_day: float, steps: int = 200, start: float = 0.0):
    rng = random.Random(3)
    level = start
    for i in range(steps):
        level = min(1.0, level + rate_per_day * (900.0 / 86_400.0))
        rul.observe(
            "P-101A", "bearing_wear", 1.0, max(0.0, level + rng.gauss(0, 0.0002)), i * 900.0
        )


def test_rul_recovers_a_known_wear_rate():
    rul = RulEngine(sample_every_seconds=900)
    _feed(rul, 0.0014)
    estimate = rul.estimates_for("P-101A")[0]
    assert estimate.trend_per_day == pytest.approx(0.0014, rel=0.1)
    assert estimate.hours_remaining == pytest.approx((1.0 - estimate.level) / 0.0014 * 24, rel=0.1)
    assert estimate.confidence > 0.5


def test_rul_collapses_when_wear_accelerates():
    slow = RulEngine(sample_every_seconds=900)
    _feed(slow, 0.0014)
    fast = RulEngine(sample_every_seconds=900)
    _feed(fast, 2.4, steps=60, start=0.05)

    assert fast.estimates_for("P-101A")[0].hours_remaining < (
        slow.estimates_for("P-101A")[0].hours_remaining / 100
    )


def test_rul_publishes_nothing_until_it_has_evidence():
    rul = RulEngine(sample_every_seconds=900)
    rul.observe("P-101A", "bearing_wear", 1.0, 0.1, 0.0)
    estimate = rul.estimates_for("P-101A")[0]
    assert estimate.hours_remaining is None
    assert estimate.confidence == 0.0


def test_a_stable_mode_is_not_projected_to_fail():
    rul = RulEngine(sample_every_seconds=900)
    _feed(rul, 0.0)
    assert rul.estimates_for("P-101A")[0].hours_remaining is None


def test_rul_reset_discards_history():
    rul = RulEngine(sample_every_seconds=900)
    _feed(rul, 0.0014)
    rul.reset("P-101A")
    assert rul.estimates_for("P-101A") == []


# --------------------------------------------------------------------- KPIs


def _kpis(**overrides):
    args = dict(
        states={"P-101A": AssetState.RUNNING, "RX-301": AssetState.RUNNING},
        healths={"P-101A": 91.0, "RX-301": 97.0},
        criticalities={"P-101A": Criticality.HIGH, "RX-301": Criticality.CRITICAL},
        throughput_tph=115.0,
        quality=0.92,
        power_kw=420.0,
        design_rate_tph=115.0,
        tariff_eur_kwh=0.142,
        grid_intensity=0.268,
    )
    args.update(overrides)
    return compute(**args)


def test_oee_is_the_product_of_its_three_terms():
    k = _kpis()
    assert k.oee == pytest.approx(k.availability * k.performance * k.quality, rel=1e-6)


def test_a_critical_asset_down_hurts_availability_more_than_a_high_one():
    critical_down = _kpis(states={"P-101A": AssetState.RUNNING, "RX-301": AssetState.FAULT})
    high_down = _kpis(states={"P-101A": AssetState.FAULT, "RX-301": AssetState.RUNNING})
    assert critical_down.availability < high_down.availability


def test_energy_intensity_is_guarded_against_a_stopped_line():
    assert _kpis(throughput_tph=0.0).energy_intensity_kwh_t == 0.0


def test_cost_and_carbon_track_power():
    k = _kpis(power_kw=1000.0)
    assert k.energy_cost_eur_h == pytest.approx(142.0)
    assert k.co2_kg_h == pytest.approx(268.0)

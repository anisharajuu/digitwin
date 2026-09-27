"""The models have to be right before anything built on them can be."""

from __future__ import annotations

import pytest

from app.simulation.physics import (
    Bus,
    CentrifugalPump,
    Chiller,
    Gearbox,
    HeatExchanger,
    Reactor,
    SimContext,
    build_model,
)

PUMP_DESIGN = {
    "bep_flow_m3h": 118.0,
    "shutoff_head_m": 112.0,
    "bep_efficiency": 0.79,
    "fluid_density": 985.0,
    "suction_pressure_bar": 1.35,
    "npsh_required_m": 4.2,
    "motor_rated_kw": 45.0,
}

HX_DESIGN = {
    "ua_clean_kw_k": 120.0,
    "hot_flow_kgs": 26.0,
    "cold_flow_kgs": 20.0,
    "cp_hot_kj_kgk": 2.18,
    "cp_cold_kj_kgk": 3.42,
    "hot_inlet_c": 148.0,
    "cold_inlet_c": 24.0,
    "design_dp_kpa": 62.0,
}

REACTOR_DESIGN = {
    "volume_m3": 16.0,
    "setpoint_c": 96.0,
    "jacket_ua_kw_k": 22.0,
    "coolant_temp_c": 18.0,
    "pre_exponential": 12_900_000.0,
    "activation_energy_kj_mol": 62.5,
    "heat_of_reaction_kj_mol": -78.0,
    "feed_conc_mol_m3": 320.0,
}


@pytest.fixture
def ctx() -> SimContext:
    return SimContext(dt=60.0, sim_time=0.0)


def test_as_new_pump_lands_on_its_best_efficiency_point(ctx):
    """The system curve is fitted so a clean pump sits exactly on BEP."""
    pump = CentrifugalPump("P-101A", PUMP_DESIGN)
    r = pump.solve({}, {}, ctx, Bus())
    assert r["flow_m3h"] == pytest.approx(118.0, rel=1e-3)
    assert r["efficiency_pct"] == pytest.approx(79.0, rel=1e-3)
    assert r["power_kw"] > 0


def test_impeller_wear_pulls_the_duty_point_back(ctx):
    """Flow, head and efficiency all fall together - the classic signature."""
    pump = CentrifugalPump("P-101A", PUMP_DESIGN)
    clean = pump.solve({}, {}, ctx, Bus())
    worn = pump.solve({}, {"impeller_wear": 0.6}, ctx, Bus())

    assert worn["flow_m3h"] < clean["flow_m3h"]
    assert worn["head_m"] < clean["head_m"]
    assert worn["efficiency_pct"] < clean["efficiency_pct"]
    # Efficiency falls faster than hydraulic power does, which is exactly why
    # shaft power does not drop proportionally and the loss hides on the bill.
    assert worn["power_kw"] / clean["power_kw"] > worn["flow_m3h"] / clean["flow_m3h"]


def test_bearing_wear_is_invisible_to_the_process(ctx):
    """A failing bearing changes condition signals only. No process tag moves."""
    pump = CentrifugalPump("P-101A", PUMP_DESIGN)
    clean = pump.solve({}, {}, ctx, Bus())
    worn = pump.solve({}, {"bearing_wear": 0.7}, ctx, Bus())

    assert worn["vibration_mms"] > clean["vibration_mms"] * 2
    assert worn["bearing_temp_c"] > clean["bearing_temp_c"] + 20
    assert worn["flow_m3h"] == pytest.approx(clean["flow_m3h"], rel=1e-9)


def test_standby_pump_reports_zero_flow_and_does_not_age(ctx):
    pump = CentrifugalPump("P-101B", PUMP_DESIGN, standby=True)
    r = pump.solve({}, {}, ctx, Bus())
    assert r["flow_m3h"] == 0.0
    assert r["power_kw"] == 0.0
    assert all(v == 0.0 for v in pump.stress(r).values())


def test_exchanger_effectiveness_stays_physical(ctx):
    """Effectiveness is bounded by definition; duty must respect both streams."""
    hx = HeatExchanger("HX-201", HX_DESIGN)
    bus = Bus()
    bus.set("feed_flow_m3h", 118.0)
    r = hx.solve({}, {}, ctx, bus)

    assert 0.0 < r["effectiveness_pct"] < 100.0
    assert r["cold_outlet_c"] < r["hot_inlet_c"]  # cannot exceed the hot source
    assert r["hot_outlet_c"] > r["cold_inlet_c"]  # counter-flow, not a crossover
    assert r["duty_kw"] > 0


def test_fouling_widens_approach_and_raises_pressure_drop(ctx):
    hx = HeatExchanger("HX-201", HX_DESIGN)
    bus = Bus()
    bus.set("feed_flow_m3h", 118.0)
    clean = hx.solve({}, {}, ctx, bus)
    fouled = hx.solve({}, {"fouling": 0.8}, ctx, bus)

    assert fouled["duty_kw"] < clean["duty_kw"]
    assert fouled["approach_k"] > clean["approach_k"]
    assert fouled["dp_shell_kpa"] > clean["dp_shell_kpa"]
    assert fouled["ua_kw_k"] < clean["ua_kw_k"]


def test_reactor_controller_holds_setpoint(ctx):
    """Closed loop, so the reactor must settle on setpoint, not near it."""
    rx = Reactor("RX-301", REACTOR_DESIGN)
    bus = Bus()
    bus.set("feed_flow_m3h", 118.0)
    bus.set("reactor_feed_temp_c", 97.8)
    state = rx.initial_state()
    for _ in range(400):
        r = rx.solve(state, {}, ctx, bus)

    assert r["temp_c"] == pytest.approx(96.0, abs=0.3)
    assert 0.0 < r["jacket_valve_pct"] < 100.0  # controller has headroom both ways
    assert 80.0 < r["conversion_pct"] < 99.0


def test_jacket_fouling_erodes_control_margin_before_it_moves_temperature(ctx):
    """The valve saturates first; that is the early warning worth having."""
    rx = Reactor("RX-301", REACTOR_DESIGN)
    bus = Bus()
    bus.set("feed_flow_m3h", 118.0)
    bus.set("reactor_feed_temp_c", 97.8)

    clean_state, fouled_state = rx.initial_state(), rx.initial_state()
    for _ in range(400):
        clean = rx.solve(clean_state, {}, ctx, bus)
        fouled = rx.solve(fouled_state, {"jacket_fouling": 0.85}, ctx, bus)

    assert fouled["jacket_valve_pct"] > clean["jacket_valve_pct"] + 20
    assert fouled["temp_c"] == pytest.approx(clean["temp_c"], abs=1.0)


def test_catalyst_deactivation_costs_conversion(ctx):
    rx = Reactor("RX-301", REACTOR_DESIGN)
    bus = Bus()
    bus.set("feed_flow_m3h", 118.0)
    bus.set("reactor_feed_temp_c", 97.8)

    good, poor = rx.initial_state(), rx.initial_state()
    for _ in range(400):
        healthy = rx.solve(good, {}, ctx, bus)
        deactivated = rx.solve(poor, {"catalyst_activity": 0.8}, ctx, bus)

    assert deactivated["conversion_pct"] < healthy["conversion_pct"] - 5


def test_gearbox_symptoms_are_condition_only(ctx):
    gb = Gearbox("AGT-301", {"rated_power_kw": 37.0, "input_speed_rpm": 1475.0, "ratio": 12.3})
    clean = gb.solve({}, {}, ctx, Bus())
    worn = gb.solve({}, {"gear_wear": 0.8, "bearing_wear": 0.5}, ctx, Bus())

    assert worn["vibration_mms"] > clean["vibration_mms"] * 3
    assert worn["oil_particle_ppm"] > clean["oil_particle_ppm"]
    assert worn["output_speed_rpm"] == pytest.approx(clean["output_speed_rpm"])


def test_chiller_cop_falls_and_power_rises_with_condenser_fouling(ctx):
    chiller = Chiller("CHL-202", {"rated_cooling_kw": 1200.0, "rated_cop": 4.6})
    bus = Bus()
    bus.set("jacket_duty_kw", 860.0)
    clean = chiller.solve({}, {}, ctx, bus)
    fouled = chiller.solve({}, {"condenser_fouling": 0.85}, ctx, bus)

    assert fouled["cop"] < clean["cop"]
    assert fouled["power_kw"] > clean["power_kw"]
    assert fouled["condenser_approach_k"] > clean["condenser_approach_k"]


def test_bus_accumulators_reset_between_ticks():
    """Two pumps on one header must sum within a tick, never across ticks."""
    bus = Bus()
    for _ in range(3):
        bus.begin_tick()
        bus.set("feed_flow_m3h", bus.get("feed_flow_m3h") + 60.0)
        bus.set("feed_flow_m3h", bus.get("feed_flow_m3h") + 58.0)
    assert bus.get("feed_flow_m3h") == pytest.approx(118.0)


def test_lagged_signals_survive_the_tick_boundary():
    """Non-accumulator signals carry forward, modelling transport lag."""
    bus = Bus()
    bus.set("jacket_duty_kw", 860.0)
    bus.begin_tick()
    assert bus.get("jacket_duty_kw") == pytest.approx(860.0)


def test_unknown_asset_kind_is_rejected_loudly():
    with pytest.raises(KeyError, match="no physics model registered"):
        build_model("flux_capacitor", "FC-001", {})

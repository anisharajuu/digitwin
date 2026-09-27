"""First-principles asset models.

Each model exposes one pure-ish entry point::

    solve(state, levels, ctx, bus) -> dict[tag, value]

``levels`` is the asset's degradation state. The engine calls ``solve`` twice
per tick against two independent copies of the dynamic state: once with the
real wear levels (producing what the sensors would read) and once with every
level pinned to zero (producing what an as-new machine would do under exactly
the same conditions). The difference between those two runs is the residual,
and the residual is what the analytics layer reasons about.

Because of that, nothing in this module is allowed to fabricate a symptom. If
a worn impeller is supposed to pull the duty point back, that has to fall out
of the head curve, not out of an ``if faulted:`` branch.

Units are SI-ish and stated on every tag: bar (absolute unless noted), degC,
kW, m3/h, mm/s RMS, K.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..domain.models import TagSpec
from .degradation import ModeSpec

G = 9.80665
R_GAS = 8.314  # J/mol.K


# --------------------------------------------------------------------------- utils


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * clamp(t, 0.0, 1.0)


@dataclass(frozen=True)
class Tag:
    """A sensor channel, with the noise the instrument would actually show."""

    name: str
    label: str
    unit: str
    tag_class: str = "process"
    lo: float | None = None
    hi: float | None = None
    precision: int = 2
    #: Standard deviation of the measurement noise, in the tag's own unit.
    sigma: float = 0.0
    monitored: bool = True

    def spec(self) -> TagSpec:
        return TagSpec(
            name=self.name,
            label=self.label,
            unit=self.unit,
            tag_class=self.tag_class,  # type: ignore[arg-type]
            lo=self.lo,
            hi=self.hi,
            precision=self.precision,
            monitored=self.monitored,
        )


@dataclass
class SimContext:
    """Per-tick context handed to every model."""

    dt: float  # simulated seconds this tick
    sim_time: float  # simulated seconds since start
    ambient_c: float = 14.0
    #: Largest internal integration step a stiff model may take. The live loop
    #: keeps this tight; what-if projections relax it, trading a little
    #: transient fidelity for the speed to sweep a month in a few hundred ms.
    max_substep: float = 5.0


class Bus:
    """Process signals shared between assets within a single solve pass.

    The bus persists between ticks on purpose: an asset solved earlier in the
    ordering than its upstream source (the chiller reads the reactor's jacket
    duty) then sees last tick's value, which is a fair model of transport lag.
    Signals that several assets *sum into* - parallel pumps on one header -
    must not persist, so they are declared as accumulators and zeroed each tick.
    """

    #: Keys written with ``+=`` semantics by one or more assets per pass.
    ACCUMULATORS: tuple[str, ...] = ("feed_flow_m3h",)

    def __init__(self) -> None:
        self._values: dict[str, float] = {}
        self._previous: dict[str, float] = {}

    def begin_tick(self) -> None:
        for key in self.ACCUMULATORS:
            # Keep last tick's total before zeroing. An asset solved *before*
            # the ones that sum into a header - the surge tank sits upstream
            # of the pumps that draw from it - has to read the previous
            # total, or it reads the zero we just wrote.
            self._previous[key] = self._values.get(key, 0.0)
            self._values[key] = 0.0

    def previous(self, key: str, default: float = 0.0) -> float:
        """Last tick's value of an accumulator, for upstream consumers."""
        value = self._previous.get(key)
        return default if value is None or value == 0.0 else value

    def get(self, key: str, default: float = 0.0) -> float:
        return self._values.get(key, default)

    def set(self, key: str, value: float) -> None:
        self._values[key] = value

    def as_dict(self) -> dict[str, float]:
        return dict(self._values)


class ObserverBus(Bus):
    """Read-through view of the real plant, used for the reference pass.

    This exists because of a real diagnostic failure. The reference pass used
    to run on its own free-standing bus, so a worn pump starved the *real*
    exchanger while the *reference* exchanger still saw design flow. Every
    asset downstream of the fault then showed a large residual, and the
    console duly raised alerts on the reactor and the chiller when the thing
    that had actually failed was the pump. Worse, the reactor's jacket valve -
    a controller output, whose entire job is to absorb upstream disturbance -
    produced the loudest residual of all.

    The fix is the one a real plant observer uses: each reference asset is fed
    the *measured* conditions its real counterpart actually saw, and only its
    own degradation is zeroed. Reads therefore come from the real bus; writes
    go to a scratch dict and are discarded. The residual that survives is
    local to the asset, so an alert names the machine that is at fault rather
    than the first machine downstream of it.
    """

    def __init__(self, real: Bus) -> None:
        super().__init__()
        self._real = real

    def get(self, key: str, default: float = 0.0) -> float:
        return self._real.get(key, default)

    def previous(self, key: str, default: float = 0.0) -> float:
        return self._real.previous(key, default)

    def set(self, key: str, value: float) -> None:
        # Scratch only - a reference asset must never steer its neighbours.
        self._values[key] = value

    def begin_tick(self) -> None:
        self._values.clear()


# --------------------------------------------------------------------------- base


class AssetModel:
    """Base class for every modelled asset."""

    kind: str = "generic"

    def __init__(self, asset_id: str, design: dict[str, Any], standby: bool = False) -> None:
        self.asset_id = asset_id
        self.d = design
        self.standby = standby

    # -- static description ------------------------------------------------
    def tags(self) -> list[Tag]:
        raise NotImplementedError

    def mode_specs(self) -> list[ModeSpec]:
        return []

    def initial_state(self) -> dict[str, float]:
        return {}

    # -- behaviour ---------------------------------------------------------
    def solve(
        self, state: dict[str, float], levels: dict[str, float], ctx: SimContext, bus: Bus
    ) -> dict[str, float]:
        raise NotImplementedError

    def stress(self, readings: dict[str, float]) -> dict[str, float]:
        """Per-mode multipliers on the base wear rate, derived from duty.

        Returning ``{}`` means every mode wears at its nominal rate. An idle
        standby machine should return zeros so it does not age on the shelf.
        """
        return {}

    def anchor_reference(self, state: dict[str, float], ref_state: dict[str, float]) -> None:
        """Re-anchor integrating reference states to the real plant.

        Most models are self-correcting: perturb a reactor temperature and the
        energy balance pulls it back, so the real and reference copies stay
        comparable indefinitely. Pure integrators are not. A vessel level is
        the integral of a flow difference, so *any* mismatch between the two
        copies - however small, however legitimate - accumulates without bound
        until the residual is enormous and means nothing.

        Assets carrying an integrating state override this to re-anchor the
        reference copy each tick, which is what a state observer on a real
        plant does. The residual then isolates the thing we actually want to
        detect (an instrument diverging from the inventory) instead of being
        swamped by integrated drift.
        """
        return None

    def power_kw(self, readings: dict[str, float]) -> float:
        return readings.get("power_kw", 0.0)


# --------------------------------------------------------------------------- pump


class CentrifugalPump(AssetModel):
    """Centrifugal pump on a fixed system curve.

    Head follows ``H = H0 - a.Q^2`` against a system curve
    ``H = Hs + b.Q^2``; the duty point is where they meet. Impeller wear drops
    ``H0`` and steepens ``a``, which walks the duty point back down the system
    curve - flow and head fall together while shaft power stays stubbornly
    high, because efficiency falls faster than hydraulic power does. That is
    the classic signature the residual detector should pick up long before a
    flow alarm would.
    """

    kind = "centrifugal_pump"

    def tags(self) -> list[Tag]:
        return [
            Tag("flow_m3h", "Flow", "m3/h", "process", 0, 200, 1, sigma=0.65),
            Tag("head_m", "Head", "m", "process", 0, 130, 1, sigma=0.35),
            Tag("suction_pressure_bar", "Suction pressure", "bar", "process", 0, 4, 3, sigma=0.006),
            Tag(
                "discharge_pressure_bar",
                "Discharge pressure",
                "bar",
                "process",
                0,
                12,
                3,
                sigma=0.012,
            ),
            Tag("power_kw", "Shaft power", "kW", "electrical", 0, 55, 2, sigma=0.22),
            Tag("motor_current_a", "Motor current", "A", "electrical", 0, 95, 1, sigma=0.35),
            Tag("efficiency_pct", "Hydraulic efficiency", "%", "derived", 0, 100, 1, sigma=0.30),
            Tag("vibration_mms", "Vibration RMS", "mm/s", "condition", 0, 18, 2, sigma=0.055),
            Tag(
                "bearing_temp_c", "Bearing temperature", "degC", "condition", 0, 110, 1, sigma=0.28
            ),
            Tag("npsh_margin_m", "NPSH margin", "m", "process", -2, 20, 2, sigma=0.05),
        ]

    def mode_specs(self) -> list[ModeSpec]:
        return [
            ModeSpec(
                "impeller_wear",
                "Impeller wear",
                base_rate_per_day=0.00085,
                action="Strip pump, replace impeller and wear rings",
                effect="Head curve flattens; flow and efficiency fall at constant power.",
                downtime_h=14.0,
                cost_eur=8_900.0,
            ),
            ModeSpec(
                "bearing_wear",
                "Bearing wear",
                base_rate_per_day=0.00140,
                action="Replace drive-end and non-drive-end bearings",
                effect="Vibration RMS and bearing temperature rise with no process change.",
                downtime_h=6.0,
                cost_eur=3_200.0,
            ),
        ]

    def solve(self, state, levels, ctx, bus):
        d = self.d
        iw = levels.get("impeller_wear", 0.0)
        bw = levels.get("bearing_wear", 0.0)

        if self.standby:
            # A standby machine still reports a live suction pressure and an
            # ambient-soaked bearing. Everything else is genuinely zero.
            suction = bus.get("header_suction_bar", d.get("suction_pressure_bar", 1.35))
            readings = {t.name: 0.0 for t in self.tags()}
            readings["suction_pressure_bar"] = suction
            readings["discharge_pressure_bar"] = suction
            readings["bearing_temp_c"] = ctx.ambient_c + 2.5
            readings["npsh_margin_m"] = self._npsh_margin(suction)
            return readings

        rho = float(d.get("fluid_density", 985.0))
        q_bep = float(d.get("bep_flow_m3h", 118.0))
        h0_clean = float(d.get("shutoff_head_m", 112.0))
        eta_bep = float(d.get("bep_efficiency", 0.79))

        q_runout = 1.45 * q_bep
        a_clean = h0_clean / (q_runout**2)
        h_static = 0.45 * h0_clean
        # Pick the system curve so an as-new pump lands exactly on its BEP.
        b_sys = (h0_clean - h_static) / (q_bep**2) - a_clean

        # Wear: shutoff head falls, curve steepens.
        h0 = h0_clean * (1.0 - 0.30 * iw)
        a = a_clean * (1.0 + 0.25 * iw)

        speed_scale = float(bus.get("pump_speed_scale", 1.0))
        h0 *= speed_scale**2
        a /= max(0.25, speed_scale**2)

        head_available = h0 - h_static
        q = 0.0 if head_available <= 0 else math.sqrt(head_available / max(1e-9, a + b_sys))
        head = h_static + b_sys * q * q

        # Efficiency: parabolic penalty away from BEP, plus a wear term.
        dev = (q - q_bep) / max(1e-6, q_bep)
        eta = eta_bep * (1.0 - 0.60 * dev * dev) * (1.0 - 0.32 * iw)
        eta = clamp(eta, 0.12, 0.92)

        hydraulic_kw = rho * G * (q / 3600.0) * head / 1000.0
        shaft_kw = hydraulic_kw / eta

        suction = bus.get("header_suction_bar", float(d.get("suction_pressure_bar", 1.35)))
        discharge = suction + rho * G * head / 1e5

        npsh_margin = self._npsh_margin(suction)
        cavitating = npsh_margin < 1.0
        # Cavitation is a vibration event first and a performance event second.
        cav_vib = 0.0 if not cavitating else 4.5 * (1.0 - clamp(npsh_margin, 0.0, 1.0))
        if cavitating:
            q *= 1.0 - 0.06 * (1.0 - clamp(npsh_margin, 0.0, 1.0))

        rated_kw = max(1.0, float(d.get("motor_rated_kw", 45.0)))
        motor_eff = 0.93 - 0.05 * max(0.0, 0.5 - shaft_kw / rated_kw)
        current = shaft_kw / max(0.5, motor_eff) * 1000.0 / (math.sqrt(3) * 400.0 * 0.87)

        vibration = 1.55 + 7.6 * bw**1.8 + 3.1 * iw**1.5 + cav_vib
        bearing_temp = ctx.ambient_c + 24.0 + 44.0 * bw + 0.085 * shaft_kw

        bus.set("feed_flow_m3h", bus.get("feed_flow_m3h", 0.0) + q)
        bus.set("feed_pressure_bar", discharge)

        return {
            "flow_m3h": q,
            "head_m": head,
            "suction_pressure_bar": suction,
            "discharge_pressure_bar": discharge,
            "power_kw": shaft_kw,
            "motor_current_a": current,
            "efficiency_pct": eta * 100.0,
            "vibration_mms": vibration,
            "bearing_temp_c": bearing_temp,
            "npsh_margin_m": npsh_margin,
        }

    def _npsh_margin(self, suction_bar: float) -> float:
        rho = float(self.d.get("fluid_density", 985.0))
        vapour_bar = 0.06
        npsh_a = max(0.0, (suction_bar - vapour_bar)) * 1e5 / (rho * G)
        return npsh_a - float(self.d.get("npsh_required_m", 4.2))

    def stress(self, readings):
        if self.standby:
            return {"impeller_wear": 0.0, "bearing_wear": 0.0}
        # Cavitation chews impellers; running hot shortens bearing life
        # roughly in line with the usual 10 K halving rule of thumb.
        cav = 1.0 if readings.get("npsh_margin_m", 5.0) > 1.0 else 3.4
        temp = readings.get("bearing_temp_c", 45.0)
        thermal = 2.0 ** ((temp - 70.0) / 12.0) if temp > 70.0 else 1.0
        return {"impeller_wear": cav, "bearing_wear": clamp(thermal, 1.0, 6.0)}


# ----------------------------------------------------------------- heat exchanger


class HeatExchanger(AssetModel):
    """Counter-flow shell-and-tube exchanger, solved effectiveness-NTU.

    Fouling adds a thermal resistance in series with the clean UA and narrows
    the flow area, so duty falls and pressure drop rises at the same time.
    Approach temperature is the tag that moves first, which is why it is the
    one plant engineers actually trend.
    """

    kind = "heat_exchanger"

    def tags(self) -> list[Tag]:
        return [
            Tag("hot_inlet_c", "Hot inlet", "degC", "process", 0, 200, 1, sigma=0.22),
            Tag("hot_outlet_c", "Hot outlet", "degC", "process", 0, 200, 1, sigma=0.22),
            Tag("cold_inlet_c", "Cold inlet", "degC", "process", 0, 200, 1, sigma=0.20),
            Tag("cold_outlet_c", "Cold outlet", "degC", "process", 0, 200, 1, sigma=0.24),
            Tag("duty_kw", "Thermal duty", "kW", "derived", 0, 7000, 0, sigma=14.0),
            Tag("effectiveness_pct", "Effectiveness", "%", "derived", 0, 100, 1, sigma=0.30),
            Tag("approach_k", "Approach temperature", "K", "derived", 0, 90, 2, sigma=0.20),
            Tag("dp_shell_kpa", "Shell-side dP", "kPa", "process", 0, 260, 1, sigma=0.55),
            Tag(
                "ua_kw_k", "Effective UA", "kW/K", "derived", 0, 160, 1, sigma=0.0, monitored=False
            ),
        ]

    def mode_specs(self) -> list[ModeSpec]:
        return [
            ModeSpec(
                "fouling",
                "Tube-side fouling",
                base_rate_per_day=0.00210,
                action="Chemical clean-in-place of the tube bundle",
                effect="Approach temperature widens, duty falls, shell dP rises.",
                downtime_h=10.0,
                cost_eur=6_400.0,
            )
        ]

    def solve(self, state, levels, ctx, bus):
        d = self.d
        fouling = levels.get("fouling", 0.0)

        ua_clean = float(d.get("ua_clean_kw_k", 120.0))
        # Resistance chosen so a fully fouled bundle retains half its clean UA.
        r_max = 1.0 / (0.5 * ua_clean) - 1.0 / ua_clean
        ua = 1.0 / (1.0 / ua_clean + fouling * r_max)

        c_hot = float(d.get("hot_flow_kgs", 26.0)) * float(d.get("cp_hot_kj_kgk", 2.18))
        cold_flow_frac = clamp(bus.get("feed_flow_m3h", 118.0) / 118.0, 0.05, 1.6)
        c_cold = float(d.get("cold_flow_kgs", 20.0)) * float(d.get("cp_cold_kj_kgk", 3.42))
        c_cold *= cold_flow_frac

        c_min, c_max = min(c_hot, c_cold), max(c_hot, c_cold)
        cr = c_min / c_max if c_max > 0 else 0.0
        ntu = ua / c_min if c_min > 0 else 0.0

        if abs(1.0 - cr) < 1e-6:
            eff = ntu / (1.0 + ntu)
        else:
            ex = math.exp(-ntu * (1.0 - cr))
            eff = (1.0 - ex) / (1.0 - cr * ex)
        eff = clamp(eff, 0.0, 0.999)

        t_hot_in = float(d.get("hot_inlet_c", 148.0))
        t_cold_in = float(d.get("cold_inlet_c", 24.0))
        duty = eff * c_min * (t_hot_in - t_cold_in)

        t_hot_out = t_hot_in - duty / c_hot if c_hot > 0 else t_hot_in
        t_cold_out = t_cold_in + duty / c_cold if c_cold > 0 else t_cold_in

        dp = float(d.get("design_dp_kpa", 62.0)) * (1.0 + 1.8 * fouling) * cold_flow_frac**1.85

        bus.set("reactor_feed_temp_c", t_cold_out)

        return {
            "hot_inlet_c": t_hot_in,
            "hot_outlet_c": t_hot_out,
            "cold_inlet_c": t_cold_in,
            "cold_outlet_c": t_cold_out,
            "duty_kw": duty,
            "effectiveness_pct": eff * 100.0,
            "approach_k": t_hot_out - t_cold_in,
            "dp_shell_kpa": dp,
            "ua_kw_k": ua,
        }

    def stress(self, readings):
        # Fouling lays down faster on a hot, slow-moving surface.
        return {"fouling": clamp(readings.get("hot_outlet_c", 60.0) / 60.0, 0.5, 2.2)}


# ------------------------------------------------------------------------ chiller


class Chiller(AssetModel):
    """Water-cooled chiller serving the reactor jacket.

    Condenser fouling raises the condensing temperature, which costs COP
    roughly linearly over the range that matters. Once the machine runs out of
    capacity the supply temperature walks off setpoint - that is the point at
    which a reliability problem becomes a production problem.
    """

    kind = "chiller"

    def tags(self) -> list[Tag]:
        return [
            Tag("cooling_kw", "Cooling duty", "kW", "process", 0, 1500, 0, sigma=6.0),
            Tag("power_kw", "Compressor power", "kW", "electrical", 0, 400, 1, sigma=1.1),
            Tag("cop", "Coefficient of performance", "-", "derived", 0, 7, 2, sigma=0.018),
            Tag("supply_temp_c", "Chilled water supply", "degC", "process", 0, 25, 2, sigma=0.07),
            Tag("return_temp_c", "Chilled water return", "degC", "process", 0, 35, 2, sigma=0.09),
            Tag(
                "condenser_approach_k", "Condenser approach", "K", "condition", 0, 25, 2, sigma=0.08
            ),
            Tag("load_pct", "Load", "%", "derived", 0, 120, 1, sigma=0.5),
        ]

    def mode_specs(self) -> list[ModeSpec]:
        return [
            ModeSpec(
                "condenser_fouling",
                "Condenser fouling",
                base_rate_per_day=0.00165,
                action="Clean condenser coils and dose the cooling circuit",
                effect="COP falls, power rises, supply temperature drifts off setpoint.",
                downtime_h=5.0,
                cost_eur=2_900.0,
            )
        ]

    def solve(self, state, levels, ctx, bus):
        d = self.d
        fouling = levels.get("condenser_fouling", 0.0)

        rated = float(d.get("rated_cooling_kw", 1200.0))
        demand = bus.get("jacket_duty_kw", 0.0)
        # Capacity degrades as the condenser blinds, so the ceiling drops just
        # as the machine is being asked to work harder.
        capacity = rated * (1.0 - 0.22 * fouling)
        cooling = min(demand, capacity)

        setpoint = float(d.get("supply_setpoint_c", 7.0))
        shortfall = max(0.0, demand - capacity)
        supply = setpoint + 6.0 * (shortfall / max(1.0, rated)) ** 0.6 * 10.0
        supply = clamp(supply, setpoint, setpoint + 12.0)

        approach = 4.2 + 11.0 * fouling
        cop_rated = float(d.get("rated_cop", 4.6))
        load_frac = cooling / max(1.0, rated)
        # Part-load bonus on a VSD machine, condenser penalty on top.
        part_load = 1.0 + 0.18 * (1.0 - load_frac) - 0.25 * max(0.0, load_frac - 0.9)
        cop = cop_rated * part_load * (1.0 - 0.42 * fouling)
        cop = clamp(cop, 1.2, 8.0)

        power = cooling / cop if cop > 0 else 0.0
        delta_t = 5.0
        return_temp = supply + delta_t * clamp(load_frac / 0.75, 0.2, 1.6)

        bus.set("chilled_supply_c", supply)

        return {
            "cooling_kw": cooling,
            "power_kw": power,
            "cop": cop,
            "supply_temp_c": supply,
            "return_temp_c": return_temp,
            "condenser_approach_k": approach,
            "load_pct": load_frac * 100.0,
        }

    def stress(self, readings):
        return {"condenser_fouling": clamp(readings.get("load_pct", 70.0) / 70.0, 0.4, 1.8)}


# ------------------------------------------------------------------------ reactor


class Reactor(AssetModel):
    """Jacketed CSTR running a first-order exothermic reaction.

    Integrated properly rather than assumed at steady state, because the
    interesting behaviour is transient: when the jacket fouls, the controller
    opens up to compensate, and only once the valve saturates does the reactor
    temperature actually run away from setpoint. A twin that solved this at
    steady state would miss the whole margin-erosion story.

    Species balance:  dC/dt = (C_in - C)/tau - k.C
    Energy balance:   dT/dt = (T_in - T)/tau + (-dH).k.C/(rho.cp)
                              - UA_eff.(T - T_cool)/(V.rho.cp)
    with k = A.exp(-Ea/RT) and UA_eff set by a PI controller on temperature.
    """

    kind = "reactor"

    def tags(self) -> list[Tag]:
        return [
            Tag("temp_c", "Reactor temperature", "degC", "process", 0, 140, 2, sigma=0.09),
            Tag("pressure_barg", "Pressure", "barg", "process", 0, 8, 3, sigma=0.008),
            Tag("level_pct", "Level", "%", "process", 0, 100, 1, sigma=0.20),
            Tag("conversion_pct", "Conversion", "%", "derived", 0, 100, 2, sigma=0.12),
            Tag("feed_temp_c", "Feed temperature", "degC", "process", 0, 150, 1, sigma=0.20),
            Tag("feed_flow_m3h", "Feed flow", "m3/h", "process", 0, 200, 1, sigma=0.60),
            Tag("jacket_duty_kw", "Jacket duty", "kW", "derived", 0, 1600, 0, sigma=5.0),
            Tag("jacket_valve_pct", "Jacket valve", "%", "process", 0, 100, 1, sigma=0.25),
            Tag("product_tph", "Product rate", "t/h", "derived", 0, 160, 2, sigma=0.35),
        ]

    def mode_specs(self) -> list[ModeSpec]:
        return [
            ModeSpec(
                "jacket_fouling",
                "Jacket fouling",
                base_rate_per_day=0.00120,
                action="Descale the cooling jacket",
                effect="Control valve saturates; reactor drifts above setpoint.",
                downtime_h=18.0,
                cost_eur=14_500.0,
            ),
            ModeSpec(
                "catalyst_activity",
                "Catalyst deactivation",
                base_rate_per_day=0.00240,
                action="Change out catalyst charge",
                effect="Conversion falls at unchanged temperature and residence time.",
                downtime_h=22.0,
                cost_eur=41_000.0,
            ),
        ]

    def initial_state(self) -> dict[str, float]:
        return {
            "T": float(self.d.get("setpoint_c", 96.0)),
            "C": float(self.d.get("feed_conc_mol_m3", 320.0)) * 0.1,
            "integral": 0.0,
        }

    def solve(self, state, levels, ctx, bus):
        d = self.d
        jacket_fouling = levels.get("jacket_fouling", 0.0)
        deactivation = levels.get("catalyst_activity", 0.0)

        volume = float(d.get("volume_m3", 16.0))
        setpoint = float(bus.get("reactor_setpoint_c", d.get("setpoint_c", 96.0)))
        rho, cp = 985.0, 3.42  # kg/m3, kJ/kg.K

        q_m3h = max(1.0, bus.get("feed_flow_m3h", 118.0))
        t_feed = bus.get("reactor_feed_temp_c", float(d.get("feed_temp_c", 97.0)))
        c_in = float(d.get("feed_conc_mol_m3", 320.0))
        tau = volume / (q_m3h / 3600.0)

        pre_exp = float(d.get("pre_exponential", 1.29e7)) * (1.0 - 0.75 * deactivation)
        ea = float(d.get("activation_energy_kj_mol", 62.5)) * 1000.0
        dh = -float(d.get("heat_of_reaction_kj_mol", -78.0))  # positive = exothermic
        ua_jacket = float(d.get("jacket_ua_kw_k", 22.0)) * (1.0 - 0.55 * jacket_fouling)
        t_cool = bus.get("chilled_supply_c", float(d.get("coolant_temp_c", 18.0)))

        t = state.get("T", setpoint)
        c = state.get("C", c_in * 0.1)
        integral = state.get("integral", 0.0)

        # Sub-step so a 60 s tick stays stable against a ~490 s residence time.
        remaining = ctx.dt
        sub = min(ctx.max_substep, ctx.dt)
        thermal_mass = volume * rho * cp  # kJ/K
        valve = 0.0
        while remaining > 1e-9:
            h = min(sub, remaining)
            remaining -= h

            error = t - setpoint
            integral = clamp(integral + error * h, -4_000.0, 4_000.0)
            valve = clamp(0.06 * error + 0.00035 * integral, 0.0, 1.0)

            k = pre_exp * math.exp(-ea / (R_GAS * (t + 273.15)))
            rate = k * c  # mol/m3.s

            dc = (c_in - c) / tau - rate
            q_reaction = dh * rate * volume  # kJ/s
            q_jacket = ua_jacket * valve * (t - t_cool)  # kW
            dt_dt = (t_feed - t) / tau + (q_reaction - q_jacket) / thermal_mass

            c = clamp(c + dc * h, 0.0, c_in * 1.5)
            t = clamp(t + dt_dt * h, 0.0, 250.0)

        state["T"], state["C"], state["integral"] = t, c, integral

        conversion = clamp(1.0 - c / c_in, 0.0, 1.0) if c_in > 0 else 0.0
        jacket_duty = ua_jacket * valve * max(0.0, t - t_cool)
        pressure = 1.8 * math.exp((t - 96.0) / 26.0)
        product_tph = q_m3h * rho / 1000.0
        level = clamp(72.0 + 0.04 * (q_m3h - 118.0) * 10.0, 20.0, 95.0)

        bus.set("jacket_duty_kw", jacket_duty)
        bus.set("reactor_product_tph", product_tph)
        bus.set("reactor_conversion", conversion)
        bus.set("agitator_load_frac", clamp(q_m3h / 118.0, 0.2, 1.3))

        return {
            "temp_c": t,
            "pressure_barg": pressure,
            "level_pct": level,
            "conversion_pct": conversion * 100.0,
            "feed_temp_c": t_feed,
            "feed_flow_m3h": q_m3h,
            "jacket_duty_kw": jacket_duty,
            "jacket_valve_pct": valve * 100.0,
            "product_tph": product_tph,
        }

    def power_kw(self, readings):
        return 0.0  # thermal asset; its electrical load sits with the chiller

    def stress(self, readings):
        # Deposits lay down faster on a hot wall; catalyst poisons faster hot too.
        thermal = clamp(1.0 + (readings.get("temp_c", 96.0) - 96.0) / 12.0, 0.6, 3.0)
        return {"jacket_fouling": thermal, "catalyst_activity": thermal}


# ------------------------------------------------------------------------ gearbox


class Gearbox(AssetModel):
    """Agitator drive: the classic condition-monitoring asset.

    Nothing here touches the process. Every symptom is a condition signal -
    vibration velocity against ISO 10816, bearing temperature, oil particle
    count - which is exactly why it is the asset where residual analytics
    earns its keep: there is no production number that would ever warn you.
    """

    kind = "gearbox"

    def tags(self) -> list[Tag]:
        return [
            Tag("vibration_mms", "Vibration RMS", "mm/s", "condition", 0, 20, 2, sigma=0.06),
            Tag(
                "bearing_temp_c", "Bearing temperature", "degC", "condition", 0, 120, 1, sigma=0.30
            ),
            Tag("oil_particle_ppm", "Oil particle count", "ppm", "condition", 0, 900, 0, sigma=3.5),
            Tag("output_speed_rpm", "Output speed", "rpm", "process", 0, 200, 1, sigma=0.22),
            Tag("torque_nm", "Output torque", "Nm", "derived", 0, 4500, 0, sigma=6.0),
            Tag("power_kw", "Absorbed power", "kW", "electrical", 0, 45, 2, sigma=0.15),
        ]

    def mode_specs(self) -> list[ModeSpec]:
        return [
            ModeSpec(
                "gear_wear",
                "Gear tooth wear",
                base_rate_per_day=0.00095,
                action="Replace gear set, re-shim the mesh",
                effect="Gear-mesh vibration and oil particle count rise together.",
                downtime_h=26.0,
                cost_eur=22_000.0,
            ),
            ModeSpec(
                "bearing_wear",
                "Bearing wear",
                base_rate_per_day=0.00135,
                action="Replace input and output shaft bearings",
                effect="Broadband vibration and bearing temperature rise.",
                downtime_h=12.0,
                cost_eur=6_800.0,
            ),
            ModeSpec(
                "lubricant_degradation",
                "Lubricant degradation",
                base_rate_per_day=0.00520,
                action="Drain, flush and recharge with fresh oil",
                effect="Oil particle count climbs; accelerates every other wear mode.",
                downtime_h=3.0,
                cost_eur=900.0,
            ),
        ]

    def solve(self, state, levels, ctx, bus):
        d = self.d
        gear = levels.get("gear_wear", 0.0)
        bearing = levels.get("bearing_wear", 0.0)
        lube = levels.get("lubricant_degradation", 0.0)

        load = clamp(bus.get("agitator_load_frac", 1.0), 0.0, 1.4)
        rated_kw = float(d.get("rated_power_kw", 37.0))
        ratio = float(d.get("ratio", 12.3))
        input_rpm = float(d.get("input_speed_rpm", 1475.0))
        output_rpm = input_rpm / ratio

        # Wear costs mechanical efficiency, so absorbed power creeps up for
        # the same shaft work.
        efficiency = 0.965 - 0.10 * gear - 0.05 * bearing
        power = rated_kw * (0.62 + 0.30 * load) / max(0.5, efficiency)
        torque = power * 1000.0 / (2.0 * math.pi * output_rpm / 60.0)

        base_vib = float(d.get("baseline_vibration_mms", 1.8))
        vibration = (
            base_vib * (0.85 + 0.25 * load) + 9.2 * gear**1.7 + 6.4 * bearing**2.0 + 1.1 * lube
        )
        temp = ctx.ambient_c + 26.0 + 34.0 * bearing + 16.0 * lube + 9.0 * load
        particles = 11.0 + 360.0 * lube + 165.0 * gear + 70.0 * bearing

        return {
            "vibration_mms": vibration,
            "bearing_temp_c": temp,
            "oil_particle_ppm": particles,
            "output_speed_rpm": output_rpm,
            "torque_nm": torque,
            "power_kw": power,
        }

    def stress(self, readings):
        # Degraded oil is the upstream cause of most of the rest, so it
        # multiplies the mechanical modes rather than acting alone.
        temp = readings.get("bearing_temp_c", 55.0)
        thermal = clamp(2.0 ** ((temp - 75.0) / 12.0), 1.0, 5.0)
        particles = readings.get("oil_particle_ppm", 15.0)
        abrasive = clamp(1.0 + particles / 400.0, 1.0, 3.0)
        return {
            "gear_wear": thermal * abrasive,
            "bearing_wear": thermal * abrasive,
            "lubricant_degradation": thermal,
        }


# --------------------------------------------------------------------- compressor


class Compressor(AssetModel):
    """Oil-injected screw compressor on the instrument-air header.

    Modelled empirically rather than polytropically: on an oil-flooded screw
    the injected oil absorbs most of the heat of compression, so a textbook
    adiabatic discharge temperature would be wildly wrong. The correlations
    below are fitted to the shape of a VSD screw's published performance map,
    which is the honest way to model a machine whose internals you do not see.
    """

    kind = "compressor"

    def tags(self) -> list[Tag]:
        return [
            Tag("flow_nm3h", "Delivered flow", "Nm3/h", "process", 0, 2000, 0, sigma=6.0),
            Tag(
                "discharge_pressure_bar",
                "Discharge pressure",
                "bar",
                "process",
                0,
                11,
                3,
                sigma=0.010,
            ),
            Tag(
                "discharge_temp_c",
                "Discharge temperature",
                "degC",
                "condition",
                0,
                140,
                1,
                sigma=0.30,
            ),
            Tag("power_kw", "Absorbed power", "kW", "electrical", 0, 220, 1, sigma=0.65),
            Tag(
                "specific_power", "Specific power", "kW/(m3/min)", "derived", 0, 14, 2, sigma=0.035
            ),
            Tag("inlet_dp_mbar", "Inlet filter dP", "mbar", "condition", 0, 160, 1, sigma=0.45),
            Tag(
                "volumetric_eff_pct", "Volumetric efficiency", "%", "derived", 0, 100, 1, sigma=0.22
            ),
        ]

    def mode_specs(self) -> list[ModeSpec]:
        return [
            ModeSpec(
                "valve_leakage",
                "Discharge valve leakage",
                base_rate_per_day=0.00130,
                action="Overhaul the air end, replace valve plates",
                effect="Volumetric efficiency and delivered flow fall; specific power rises.",
                downtime_h=16.0,
                cost_eur=18_500.0,
            ),
            ModeSpec(
                "filter_blockage",
                "Inlet filter blockage",
                base_rate_per_day=0.00760,
                action="Replace inlet filter element",
                effect="Inlet dP rises, mass flow falls, discharge temperature climbs.",
                downtime_h=1.5,
                cost_eur=420.0,
            ),
        ]

    def solve(self, state, levels, ctx, bus):
        d = self.d
        leakage = levels.get("valve_leakage", 0.0)
        blockage = levels.get("filter_blockage", 0.0)

        rated_flow = float(d.get("rated_flow_nm3h", 1550.0))
        rated_power = float(d.get("rated_power_kw", 160.0))
        inlet_t = float(d.get("inlet_temp_c", 22.0))

        # Header demand wanders on a slow cycle - plants are never steady.
        demand = (
            0.78 + 0.10 * math.sin(ctx.sim_time / 5400.0) + 0.05 * math.sin(ctx.sim_time / 1300.0)
        )
        demand = clamp(demand, 0.45, 1.0)

        inlet_dp_mbar = 11.0 + 96.0 * blockage
        p_inlet = 1.013 - inlet_dp_mbar / 1000.0
        vol_eff = 0.94 * (1.0 - 0.38 * leakage)

        flow = rated_flow * demand * (vol_eff / 0.94) * (p_inlet / 1.013)
        power = rated_power * demand * (1.0 + 0.28 * leakage + 0.22 * blockage)
        specific = power / max(0.1, flow / 60.0)
        discharge_t = inlet_t + 58.0 + 26.0 * leakage + 19.0 * blockage
        discharge_p = float(d.get("discharge_pressure_bar", 7.5)) - 0.35 * leakage

        return {
            "flow_nm3h": flow,
            "discharge_pressure_bar": discharge_p,
            "discharge_temp_c": discharge_t,
            "power_kw": power,
            "specific_power": specific,
            "inlet_dp_mbar": inlet_dp_mbar,
            "volumetric_eff_pct": vol_eff * 100.0,
        }

    def stress(self, readings):
        hot = clamp(1.0 + (readings.get("discharge_temp_c", 80.0) - 80.0) / 25.0, 0.7, 2.6)
        return {"valve_leakage": hot, "filter_blockage": 1.0}


# ---------------------------------------------------------------------- separator


class Separator(AssetModel):
    """Coalescing separator. Its split efficiency is the plant's quality term."""

    kind = "separator"

    def tags(self) -> list[Tag]:
        return [
            Tag("throughput_tph", "Throughput", "t/h", "process", 0, 160, 2, sigma=0.32),
            Tag("split_efficiency_pct", "Split efficiency", "%", "derived", 0, 100, 2, sigma=0.09),
            Tag("dp_kpa", "Differential pressure", "kPa", "process", 0, 200, 1, sigma=0.42),
            Tag("interface_level_pct", "Interface level", "%", "process", 0, 100, 1, sigma=0.30),
            Tag("power_kw", "Absorbed power", "kW", "electrical", 0, 40, 2, sigma=0.12),
        ]

    def mode_specs(self) -> list[ModeSpec]:
        return [
            ModeSpec(
                "mesh_fouling",
                "Coalescer mesh fouling",
                base_rate_per_day=0.00185,
                action="Remove and clean the coalescer pack",
                effect="Split efficiency falls and dP rises - product quality suffers.",
                downtime_h=9.0,
                cost_eur=5_100.0,
            )
        ]

    def solve(self, state, levels, ctx, bus):
        d = self.d
        fouling = levels.get("mesh_fouling", 0.0)

        rated = float(d.get("rated_throughput_tph", 120.0))
        throughput = bus.get("reactor_product_tph", rated * 0.96)
        load = clamp(throughput / rated, 0.0, 1.4)

        split = float(d.get("design_split_efficiency", 0.962)) * (1.0 - 0.18 * fouling)
        # Overloading the pack degrades the split too, not just fouling.
        split *= 1.0 - 0.06 * max(0.0, load - 1.0) * 10.0
        split = clamp(split, 0.40, 0.999)

        dp = 44.0 * (1.0 + 1.45 * fouling) * max(0.05, load) ** 1.8
        power = float(d.get("rated_power_kw", 28.0)) * (0.35 + 0.65 * load)
        interface = clamp(48.0 + 22.0 * fouling + 6.0 * (load - 1.0), 5.0, 95.0)

        # On-spec yield is the whole chain, not just this vessel: feed that
        # never reacted is as unsaleable as product the pack failed to split.
        # Folding conversion in here is what makes reactor setpoint a lever
        # the business case can actually see.
        conversion = clamp(bus.get("reactor_conversion", 1.0), 0.0, 1.0)
        yield_fraction = split * conversion
        bus.set("product_quality", yield_fraction)
        bus.set("product_out_tph", throughput * yield_fraction)

        return {
            "throughput_tph": throughput,
            "split_efficiency_pct": split * 100.0,
            "dp_kpa": dp,
            "interface_level_pct": interface,
            "power_kw": power,
        }

    def stress(self, readings):
        return {"mesh_fouling": clamp(readings.get("throughput_tph", 110.0) / 110.0, 0.3, 2.0)}


# --------------------------------------------------------------------------- tank


class Tank(AssetModel):
    """Buffer vessel with a level controller and a drifting transmitter.

    ``volume_m3`` is the twin's own integrated mass balance; ``level_pct`` is
    what the transmitter reports. A ``sensor_drift`` fault separates the two
    without touching a drop of liquid, which is the cheapest possible
    demonstration that the residual detector is reasoning about the model and
    not just watching thresholds.
    """

    kind = "tank"

    def tags(self) -> list[Tag]:
        capacity = float(self.d.get("volume_m3", 40.0))
        flow_hi = max(260.0, float(self.d.get("export_rate_m3h", 0.0)) * 1.2)
        return [
            Tag("level_pct", "Level (transmitter)", "%", "process", 0, 100, 2, sigma=0.16),
            Tag(
                "volume_m3",
                "Volume (mass balance)",
                "m3",
                "derived",
                0,
                capacity,
                2,
                sigma=0.0,
                monitored=False,
            ),
            Tag("inflow_m3h", "Inflow", "m3/h", "process", 0, flow_hi, 1, sigma=0.45),
            Tag("outflow_m3h", "Outflow", "m3/h", "process", 0, flow_hi, 1, sigma=0.45),
            Tag("temperature_c", "Contents temperature", "degC", "process", 0, 80, 1, sigma=0.12),
        ]

    def mode_specs(self) -> list[ModeSpec]:
        return [
            ModeSpec(
                "sensor_drift",
                "Level transmitter drift",
                base_rate_per_day=0.00090,
                threshold=0.70,
                action="Re-calibrate the level transmitter",
                effect="Reported level diverges from the mass balance. No physical fault.",
                downtime_h=1.0,
                cost_eur=350.0,
            )
        ]

    def initial_state(self) -> dict[str, float]:
        volume = float(self.d.get("volume_m3", 40.0))
        return {"volume": volume * float(self.d.get("initial_level_pct", 60.0)) / 100.0}

    def solve(self, state, levels, ctx, bus):
        d = self.d
        drift = levels.get("sensor_drift", 0.0)
        capacity = float(d.get("volume_m3", 40.0))
        volume = state.get("volume", capacity * 0.6)
        true_level = 100.0 * volume / capacity

        is_product = self.asset_id.startswith("TK-6")
        if is_product:
            # Product tank: fills continuously, exports in scheduled batches.
            #
            # The export window is a pure function of time, not of this copy's
            # own level. That matters: a road-tanker slot is an exogenous
            # commercial input, so the real and reference tanks must open the
            # export valve at the same instants. Switching on each copy's own
            # level instead would let the two sawtooths drift out of phase and
            # manufacture a 400 m3/h "residual" that means nothing at all.
            rho = 985.0
            inflow = bus.get("product_out_tph", 110.0) * 1000.0 / rho
            cycle = float(d.get("export_cycle_h", 6.0)) * 3600.0
            window = float(d.get("export_window_h", 1.5)) * 3600.0
            phase = ctx.sim_time % cycle
            exporting = phase >= (cycle - window)
            outflow = float(d.get("export_rate_m3h", 427.0)) if exporting else 0.0
            temperature = 38.0
        else:
            # Feed surge tank: make-up trims to hold the level setpoint.
            # Lagged read - the pumps that empty this vessel are solved after
            # it, so the live accumulator is still zero at this point.
            outflow = bus.previous("feed_flow_m3h", 118.0)
            setpoint = float(d.get("initial_level_pct", 68.0))
            trim = clamp((setpoint - true_level) * 1.8, -35.0, 35.0)
            inflow = clamp(outflow + trim, 0.0, 260.0)
            temperature = 24.0
            bus.set("header_suction_bar", clamp(1.02 + 0.0042 * true_level, 1.0, 1.75))

        volume = clamp(volume + (inflow - outflow) / 3600.0 * ctx.dt, 0.0, capacity)
        state["volume"] = volume
        true_level = 100.0 * volume / capacity

        # The transmitter, not the tank, is what goes wrong here.
        reported_level = clamp(true_level + 18.0 * drift, 0.0, 100.0)

        return {
            "level_pct": reported_level,
            "volume_m3": volume,
            "inflow_m3h": inflow,
            "outflow_m3h": outflow,
            "temperature_c": temperature,
        }

    def power_kw(self, readings):
        return 0.0

    def anchor_reference(self, state, ref_state):
        # Level is a pure integrator, so the reference copy is re-anchored to
        # the real inventory every tick. What survives in the residual is the
        # transmitter's own error - which is exactly the fault worth catching.
        ref_state["volume"] = state.get("volume", ref_state.get("volume", 0.0))


# ----------------------------------------------------------------------- registry


MODEL_REGISTRY: dict[str, type[AssetModel]] = {
    cls.kind: cls
    for cls in (
        CentrifugalPump,
        HeatExchanger,
        Chiller,
        Reactor,
        Gearbox,
        Compressor,
        Separator,
        Tank,
    )
}


def build_model(kind: str, asset_id: str, design: dict[str, Any], standby: bool = False):
    try:
        cls = MODEL_REGISTRY[kind]
    except KeyError as exc:  # pragma: no cover - configuration error
        raise KeyError(
            f"no physics model registered for kind '{kind}' "
            f"(known: {', '.join(sorted(MODEL_REGISTRY))})"
        ) from exc
    return cls(asset_id=asset_id, design=design, standby=standby)

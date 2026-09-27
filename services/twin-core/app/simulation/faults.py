"""Fault injection.

A digital twin that only ever shows a healthy plant proves nothing. The fault
catalogue lets an operator (or a demo script, or a test) drive a named failure
mechanism on a named asset and watch it propagate: wear rises, the physics
response shifts, residuals open up, the detector raises an alert, and the
remaining-useful-life estimate collapses towards the intervention date.

Faults act on degradation *rates*, never on sensor values directly. Nothing
here writes a fake reading - the symptoms emerge from the models.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

#: Level/day added at severity 1.0. Chosen so a full-severity fault walks a
#: mode from as-new to threshold in roughly six simulated hours, which is a
#: watchable few minutes at the default 60x speed-up.
MAX_FAULT_RATE_PER_DAY = 4.0


@dataclass(frozen=True)
class FaultSpec:
    """A failure mechanism that can be injected on a class of asset."""

    id: str
    label: str
    mode: str
    kinds: tuple[str, ...]
    description: str
    symptom: str


CATALOGUE: tuple[FaultSpec, ...] = (
    FaultSpec(
        id="bearing_spall",
        label="Bearing spalling",
        mode="bearing_wear",
        kinds=("centrifugal_pump", "gearbox"),
        description=(
            "Sub-surface fatigue on the bearing race, shedding material into the lubricant."
        ),
        symptom="Vibration RMS climbs, bearing temperature drifts up, no change in process output.",
    ),
    FaultSpec(
        id="impeller_erosion",
        label="Impeller erosion",
        mode="impeller_wear",
        kinds=("centrifugal_pump",),
        description="Vane tips eroding, flattening the head curve and pulling the duty point back.",
        symptom="Discharge head and flow fall while shaft power stays high - efficiency collapses.",
    ),
    FaultSpec(
        id="hx_fouling",
        label="Exchanger fouling",
        mode="fouling",
        kinds=("heat_exchanger",),
        description="Deposit build-up on the tube side adding thermal resistance.",
        symptom="Approach temperature widens, duty falls, shell-side pressure drop rises.",
    ),
    FaultSpec(
        id="condenser_fouling",
        label="Condenser fouling",
        mode="condenser_fouling",
        kinds=("chiller",),
        description="Air-side fouling raising condensing pressure and the work per kW of cooling.",
        symptom="COP falls, compressor power rises, supply temperature drifts off setpoint.",
    ),
    FaultSpec(
        id="jacket_fouling",
        label="Jacket fouling",
        mode="jacket_fouling",
        kinds=("reactor",),
        description="Reduced jacket heat-transfer coefficient, weakening temperature control.",
        symptom="Reactor runs hot against setpoint, cooling duty saturates, pressure rises.",
    ),
    FaultSpec(
        id="catalyst_deactivation",
        label="Catalyst deactivation",
        mode="catalyst_activity",
        kinds=("reactor",),
        description="Active-site poisoning reducing the effective rate constant.",
        symptom="Conversion drops at unchanged temperature and residence time.",
    ),
    FaultSpec(
        id="valve_leakage",
        label="Valve plate leakage",
        mode="valve_leakage",
        kinds=("compressor",),
        description="Discharge valve plates no longer sealing, re-expanding gas into the cylinder.",
        symptom="Volumetric efficiency and delivered flow fall, specific power rises.",
    ),
    FaultSpec(
        id="filter_blockage",
        label="Inlet filter blockage",
        mode="filter_blockage",
        kinds=("compressor",),
        description="Particulate loading on the inlet filter throttling the suction.",
        symptom="Inlet pressure drop rises, mass flow falls, discharge temperature climbs.",
    ),
    FaultSpec(
        id="gear_wear",
        label="Gear tooth wear",
        mode="gear_wear",
        kinds=("gearbox",),
        description="Progressive pitting on the mesh, raising gear-mesh-frequency energy.",
        symptom="Vibration rises with a clear harmonic signature, oil particle count climbs.",
    ),
    FaultSpec(
        id="lubricant_degradation",
        label="Lubricant degradation",
        mode="lubricant_degradation",
        kinds=("gearbox",),
        description="Oxidised oil losing film strength, accelerating every other wear mode.",
        symptom="Oil particle count and operating temperature rise together.",
    ),
    FaultSpec(
        id="mesh_fouling",
        label="Coalescer mesh fouling",
        mode="mesh_fouling",
        kinds=("separator",),
        description="Coalescer pack blinding, degrading the phase split.",
        symptom="Split efficiency falls and differential pressure rises - product quality suffers.",
    ),
    FaultSpec(
        id="level_sensor_drift",
        label="Level transmitter drift",
        mode="sensor_drift",
        kinds=("tank",),
        description=(
            "Calibration drift on the level transmitter. The vessel is fine; the reading is not."
        ),
        symptom=(
            "Reported level diverges from the mass balance the twin computes. No physical symptom."
        ),
    ),
)

BY_ID: dict[str, FaultSpec] = {spec.id: spec for spec in CATALOGUE}


def catalogue_for(kind: str) -> list[FaultSpec]:
    return [spec for spec in CATALOGUE if kind in spec.kinds]


@dataclass
class ActiveFault:
    """A fault currently being driven into an asset."""

    id: str
    asset_id: str
    spec: FaultSpec
    severity: float
    ramp_hours: float
    injected_at_sim: float
    elapsed_s: float = 0.0

    def current_rate(self) -> float:
        """Rate/day contributed right now, ramped in over ``ramp_hours``."""
        ramp_s = max(1.0, self.ramp_hours * 3600.0)
        progress = min(1.0, self.elapsed_s / ramp_s)
        # Smoothstep: faults arrive gradually rather than as a step change,
        # which is what makes them a fair test of the detector.
        eased = progress * progress * (3.0 - 2.0 * progress)
        return self.severity * MAX_FAULT_RATE_PER_DAY * eased

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "asset_id": self.asset_id,
            "fault": self.spec.id,
            "label": self.spec.label,
            "mode": self.spec.mode,
            "severity": round(self.severity, 3),
            "ramp_hours": self.ramp_hours,
            "progress": round(min(1.0, self.elapsed_s / max(1.0, self.ramp_hours * 3600.0)), 3),
            "symptom": self.spec.symptom,
        }


@dataclass
class FaultManager:
    """Owns every injected fault and pushes their rates onto degradation state."""

    active: dict[str, ActiveFault] = field(default_factory=dict)

    def inject(
        self, asset_id: str, fault_id: str, severity: float, ramp_hours: float, sim_time: float
    ) -> ActiveFault:
        spec = BY_ID.get(fault_id)
        if spec is None:
            raise KeyError(f"unknown fault '{fault_id}'")
        fault = ActiveFault(
            id=f"flt_{uuid.uuid4().hex[:10]}",
            asset_id=asset_id,
            spec=spec,
            severity=max(0.0, min(1.0, severity)),
            ramp_hours=max(0.05, ramp_hours),
            injected_at_sim=sim_time,
        )
        self.active[fault.id] = fault
        return fault

    def clear(self, fault_id: str) -> ActiveFault | None:
        return self.active.pop(fault_id, None)

    def clear_for_asset(self, asset_id: str, mode: str | None = None) -> list[str]:
        removed = [
            fid
            for fid, f in self.active.items()
            if f.asset_id == asset_id and (mode is None or f.spec.mode == mode)
        ]
        for fid in removed:
            self.active.pop(fid, None)
        return removed

    def for_asset(self, asset_id: str) -> list[ActiveFault]:
        return [f for f in self.active.values() if f.asset_id == asset_id]

    def advance(self, dt_seconds: float) -> None:
        for fault in self.active.values():
            fault.elapsed_s += dt_seconds

    def rates_for(self, asset_id: str) -> dict[str, float]:
        """Aggregate rate/day per degradation mode for one asset."""
        rates: dict[str, float] = {}
        for fault in self.active.values():
            if fault.asset_id != asset_id:
                continue
            rates[fault.spec.mode] = rates.get(fault.spec.mode, 0.0) + fault.current_rate()
        return rates

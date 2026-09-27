"""Typed surface shared by the simulation core and the HTTP/WS API.

Everything the console renders comes through one of these shapes. Keeping them
in one module means the OpenAPI schema and the TypeScript client stay honest
about what the twin actually publishes.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AssetState(StrEnum):
    RUNNING = "running"
    STANDBY = "standby"
    DEGRADED = "degraded"
    FAULT = "fault"
    MAINTENANCE = "maintenance"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Criticality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


TagClass = Literal["process", "condition", "electrical", "derived"]


class TagSpec(BaseModel):
    """Static description of one sensor channel."""

    name: str
    label: str
    unit: str
    tag_class: TagClass = "process"
    lo: float | None = None
    hi: float | None = None
    precision: int = 2
    #: Tags the residual detector watches. Purely-informational channels
    #: (a setpoint echo, say) are excluded so they cannot raise alerts.
    monitored: bool = True


class Area(BaseModel):
    id: str
    name: str
    colour: str = "#64748b"


class PlantInfo(BaseModel):
    id: str
    name: str
    line: str
    location: str
    timezone: str = "UTC"
    product: str
    design_rate_tph: float
    energy_tariff_eur_kwh: float
    grid_intensity_kg_co2_kwh: float


class AssetInfo(BaseModel):
    """As-designed identity for an asset. Static for the life of the process."""

    id: str
    name: str
    kind: str
    area: str
    criticality: Criticality = Criticality.MEDIUM
    manufacturer: str | None = None
    model: str | None = None
    commissioned: str | None = None
    position: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    feeds: list[str] = Field(default_factory=list)
    standby: bool = False
    design: dict[str, Any] = Field(default_factory=dict)
    tags: list[TagSpec] = Field(default_factory=list)
    degradation_modes: list[str] = Field(default_factory=list)


class Plant(BaseModel):
    """The full as-designed registry, served once and cached by the console."""

    plant: PlantInfo
    areas: list[Area]
    assets: list[AssetInfo]


class Residual(BaseModel):
    """One tag's disagreement between the physics model and the sensor."""

    tag: str
    observed: float
    expected: float
    residual: float
    z: float
    breached: bool = False


class RulEstimate(BaseModel):
    mode: str
    level: float
    threshold: float
    hours_remaining: float | None
    confidence: float
    trend_per_day: float


class AssetSnapshot(BaseModel):
    """Everything true about one asset at one instant."""

    id: str
    state: AssetState
    health: float = Field(ge=0, le=100)
    values: dict[str, float]
    residuals: dict[str, Residual] = Field(default_factory=dict)
    degradation: dict[str, float] = Field(default_factory=dict)
    rul: list[RulEstimate] = Field(default_factory=list)
    power_kw: float = 0.0
    active_faults: list[str] = Field(default_factory=list)
    open_alerts: int = 0


class Kpis(BaseModel):
    throughput_tph: float
    availability: float
    performance: float
    quality: float
    oee: float
    power_kw: float
    energy_intensity_kwh_t: float
    co2_kg_h: float
    energy_cost_eur_h: float
    plant_health: float


class Alert(BaseModel):
    id: str
    asset_id: str
    tag: str | None = None
    severity: Severity
    title: str
    detail: str
    raised_at: float
    cleared_at: float | None = None
    acknowledged: bool = False
    z: float | None = None


class Frame(BaseModel):
    """One broadcast tick: the whole plant, small enough to send at 1 Hz."""

    tick: int
    sim_time: float
    wall_time: float
    assets: dict[str, AssetSnapshot]
    kpis: Kpis
    alerts: list[Alert]


class TelemetryPoint(BaseModel):
    t: float
    v: float


class TelemetrySeries(BaseModel):
    asset_id: str
    tag: str
    spec: TagSpec
    points: list[TelemetryPoint]
    expected: list[TelemetryPoint] = Field(default_factory=list)


class WorkOrder(BaseModel):
    """A maintenance recommendation, ranked by risk rather than by date."""

    asset_id: str
    asset_name: str
    mode: str
    action: str
    due_in_hours: float | None
    severity: Severity
    criticality: Criticality
    risk_score: float
    estimated_downtime_h: float
    estimated_cost_eur: float
    rationale: str


class FaultRequest(BaseModel):
    asset_id: str
    mode: str
    severity: float = Field(default=0.6, ge=0.0, le=1.0)
    ramp_hours: float = Field(default=6.0, gt=0.0)


class MaintenanceRequest(BaseModel):
    asset_id: str
    mode: str | None = None


class ScenarioChange(BaseModel):
    asset_id: str
    #: A design parameter (e.g. ``setpoint_c``) or ``maintain`` to restore a
    #: degradation mode to as-new at t=0 of the projection.
    parameter: str
    value: float | None = None


class ScenarioRequest(BaseModel):
    name: str = "Untitled scenario"
    horizon_days: float = Field(default=30.0, gt=0, le=365)
    changes: list[ScenarioChange] = Field(default_factory=list)
    #: Simulated seconds per projection step. Larger = coarser but faster.
    step_seconds: float = Field(default=1800.0, ge=60.0, le=21600.0)


class ScenarioSeriesPoint(BaseModel):
    day: float
    throughput_tph: float
    power_kw: float
    oee: float
    plant_health: float
    energy_intensity_kwh_t: float


class ScenarioOutcome(BaseModel):
    label: str
    series: list[ScenarioSeriesPoint]
    total_energy_mwh: float
    total_production_t: float
    total_cost_eur: float
    total_co2_t: float
    mean_oee: float
    end_health: float
    unplanned_events: int


class ScenarioResult(BaseModel):
    name: str
    horizon_days: float
    baseline: ScenarioOutcome
    proposed: ScenarioOutcome
    delta_cost_eur: float
    delta_production_t: float
    delta_co2_t: float
    delta_oee: float
    verdict: str
    compute_ms: float

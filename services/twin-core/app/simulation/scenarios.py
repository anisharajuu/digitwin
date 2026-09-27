"""What-if projection: the part a plant manager actually signs off on.

Detecting a failing pump is table stakes. The question that releases budget is
"what does it cost me to fix it on Tuesday versus letting it run?", and that is
a question about the future, so it needs the twin run forward rather than
observed.

A projection forks the live twin - cloned degradation, cloned dynamic state,
optionally overridden design parameters - and sweeps it forward at a coarse
step under a deliberately simple reactive-maintenance policy: run until a wear
mode hits its threshold, take the unplanned outage, pay the unplanned bill,
repeat. The proposed case runs the identical model with the intervention
applied up front. The difference between the two, in euros and tonnes, is the
business case.

Nothing here is a regression on historical outcomes. It is the same physics the
live twin runs, integrated forward, which is why it can answer questions about
operating points the plant has never actually been run at.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..analytics import kpis as kpi_calc
from ..domain.models import (
    AssetState,
    Criticality,
    ScenarioChange,
    ScenarioOutcome,
    ScenarioRequest,
    ScenarioResult,
    ScenarioSeriesPoint,
)
from .degradation import DegradationSet
from .physics import Bus, SimContext, build_model

#: Unplanned work costs more than planned work - overtime, expedited parts,
#: collateral damage. Three times planned is the usual industry rule of thumb.
UNPLANNED_COST_MULTIPLIER = 3.0
#: And it keeps you down longer.
UNPLANNED_DOWNTIME_MULTIPLIER = 2.2
#: Integration step for projections; loose enough to be fast, tight enough to
#: stay stable against the reactor's ~490 s residence time.
PROJECTION_SUBSTEP = 60.0
#: Sentinel parameter meaning "restore this asset to as-new at t=0".
MAINTAIN = "maintain"


@dataclass
class _ProjectedAsset:
    """One asset inside a projection: its own model, wear and dynamic state."""

    asset_id: str
    name: str
    kind: str
    criticality: Criticality
    model: Any
    degradation: DegradationSet
    state: dict[str, float]
    down_until: float = 0.0
    events: int = 0
    maintenance_cost: float = 0.0


class ScenarioRunner:
    """Forks the live twin and sweeps it forward under a maintenance policy."""

    def __init__(self, engine) -> None:
        self.engine = engine

    # ------------------------------------------------------------------ api
    def run(self, request: ScenarioRequest) -> ScenarioResult:
        started = time.perf_counter()
        baseline = self._project("Do nothing", request, changes=[])
        proposed = self._project(request.name, request, changes=request.changes)

        delta_cost = baseline.total_cost_eur - proposed.total_cost_eur
        delta_production = proposed.total_production_t - baseline.total_production_t
        delta_co2 = baseline.total_co2_t - proposed.total_co2_t
        delta_oee = proposed.mean_oee - baseline.mean_oee

        return ScenarioResult(
            name=request.name,
            horizon_days=request.horizon_days,
            baseline=baseline,
            proposed=proposed,
            delta_cost_eur=round(delta_cost, 2),
            delta_production_t=round(delta_production, 1),
            delta_co2_t=round(delta_co2, 2),
            delta_oee=round(delta_oee, 4),
            verdict=self._verdict(delta_cost, delta_production, delta_oee, request.horizon_days),
            compute_ms=round((time.perf_counter() - started) * 1000.0, 1),
        )

    # ------------------------------------------------------------- internals
    def _fork(self, changes: list[ScenarioChange]) -> list[_ProjectedAsset]:
        overrides: dict[str, dict[str, float]] = {}
        maintain: dict[str, set[str] | None] = {}
        for change in changes:
            if change.parameter == MAINTAIN:
                # value is ignored; the whole asset is restored
                maintain[change.asset_id] = None
            elif change.value is not None:
                overrides.setdefault(change.asset_id, {})[change.parameter] = change.value

        forked: list[_ProjectedAsset] = []
        for asset_id, rt in self.engine.assets.items():
            design = dict(rt.info.design)
            design.update(overrides.get(asset_id, {}))

            degradation = rt.degradation.clone()
            if asset_id in maintain:
                for mode in degradation.modes.values():
                    mode.reset()

            forked.append(
                _ProjectedAsset(
                    asset_id=asset_id,
                    name=rt.info.name,
                    kind=rt.info.kind,
                    criticality=rt.info.criticality,
                    model=build_model(rt.info.kind, asset_id, design, standby=rt.info.standby),
                    degradation=degradation,
                    state=dict(rt.state),
                )
            )
        return forked

    def _project(
        self, label: str, request: ScenarioRequest, changes: list[ScenarioChange]
    ) -> ScenarioOutcome:
        assets = self._fork(changes)
        bus = Bus()
        plant = self.engine.plant_info

        # Planned work happens up front and is charged at planned rates.
        upfront_cost = 0.0
        for change in changes:
            if change.parameter != MAINTAIN:
                continue
            rt = self.engine.assets.get(change.asset_id)
            if rt is None:
                continue
            for mode in rt.degradation.modes.values():
                upfront_cost += mode.spec.cost_eur
            target = next(a for a in assets if a.asset_id == change.asset_id)
            worst = max((m.spec.downtime_h for m in rt.degradation.modes.values()), default=0.0)
            target.down_until = worst * 3600.0

        step = request.step_seconds
        total_seconds = request.horizon_days * 86_400.0
        steps = max(1, int(total_seconds / step))
        hours_per_step = step / 3600.0

        series: list[ScenarioSeriesPoint] = []
        total_energy_kwh = 0.0
        total_production_t = 0.0
        total_co2_kg = 0.0
        maintenance_cost = upfront_cost
        oee_sum = 0.0
        # Sample the curve down to something a chart can actually draw.
        sample_every = max(1, steps // 160)

        sim_time = 0.0
        for index in range(steps):
            sim_time += step
            ctx = SimContext(dt=step, sim_time=sim_time, max_substep=PROJECTION_SUBSTEP)
            bus.begin_tick()

            states: dict[str, AssetState] = {}
            healths: dict[str, float] = {}
            criticalities: dict[str, Criticality] = {}
            power_kw = 0.0

            for asset in assets:
                down = sim_time < asset.down_until
                readings = asset.model.solve(asset.state, asset.degradation.levels(), ctx, bus)
                if not down:
                    asset.degradation.advance(step, asset.model.stress(readings))
                    power_kw += asset.model.power_kw(readings)

                # Reactive policy: run to failure, then take the hit.
                for mode in asset.degradation.modes.values():
                    if mode.breached and not down:
                        asset.events += 1
                        maintenance_cost += mode.spec.cost_eur * UNPLANNED_COST_MULTIPLIER
                        asset.down_until = (
                            sim_time + mode.spec.downtime_h * UNPLANNED_DOWNTIME_MULTIPLIER * 3600.0
                        )
                        mode.reset()
                        down = True

                healths[asset.asset_id] = asset.degradation.health()
                criticalities[asset.asset_id] = asset.criticality
                states[asset.asset_id] = (
                    AssetState.MAINTENANCE
                    if down
                    else (AssetState.STANDBY if asset.model.standby else AssetState.RUNNING)
                )

            # An outage on a high-criticality asset stops the line; the
            # standby pump is exactly why P-101B exists and does not.
            line_down = any(
                states[a.asset_id] == AssetState.MAINTENANCE
                and a.criticality in (Criticality.HIGH, Criticality.CRITICAL)
                and not a.model.standby
                for a in assets
            )
            throughput = 0.0 if line_down else bus.get("reactor_product_tph", 0.0)
            quality = bus.get("product_quality", 1.0)

            kpis = kpi_calc.compute(
                states=states,
                healths=healths,
                criticalities=criticalities,
                throughput_tph=throughput,
                quality=quality,
                power_kw=power_kw,
                design_rate_tph=plant.design_rate_tph,
                tariff_eur_kwh=plant.energy_tariff_eur_kwh,
                grid_intensity=plant.grid_intensity_kg_co2_kwh,
            )

            total_energy_kwh += power_kw * hours_per_step
            # Saleable tonnes, not tonnes pushed through the line. Off-spec
            # product is a cost, not an output.
            total_production_t += throughput * quality * hours_per_step
            total_co2_kg += power_kw * plant.grid_intensity_kg_co2_kwh * hours_per_step
            oee_sum += kpis.oee

            if index % sample_every == 0 or index == steps - 1:
                series.append(
                    ScenarioSeriesPoint(
                        day=round(sim_time / 86_400.0, 3),
                        throughput_tph=kpis.throughput_tph,
                        power_kw=kpis.power_kw,
                        oee=kpis.oee,
                        plant_health=kpis.plant_health,
                        energy_intensity_kwh_t=kpis.energy_intensity_kwh_t,
                    )
                )

        energy_cost = total_energy_kwh * plant.energy_tariff_eur_kwh
        return ScenarioOutcome(
            label=label,
            series=series,
            total_energy_mwh=round(total_energy_kwh / 1000.0, 2),
            total_production_t=round(total_production_t, 1),
            total_cost_eur=round(energy_cost + maintenance_cost, 2),
            total_co2_t=round(total_co2_kg / 1000.0, 2),
            mean_oee=round(oee_sum / steps, 4),
            end_health=round(sum(a.degradation.health() for a in assets) / len(assets), 1),
            unplanned_events=sum(a.events for a in assets),
        )

    @staticmethod
    def _verdict(
        delta_cost: float, delta_production: float, delta_oee: float, horizon_days: float
    ) -> str:
        annual = delta_cost * (365.0 / horizon_days) if horizon_days > 0 else 0.0
        if delta_cost > 0 and delta_production >= -1.0:
            return (
                f"Proceed. Saves EUR {delta_cost:,.0f} over {horizon_days:.0f} days "
                f"(EUR {annual:,.0f}/yr annualised), with {delta_production:+,.0f} t of "
                f"production and {delta_oee * 100:+.1f} pts of OEE against doing nothing."
            )
        if delta_cost > 0:
            return (
                f"Marginal. Saves EUR {delta_cost:,.0f} over {horizon_days:.0f} days but "
                f"costs {abs(delta_production):,.0f} t of production - worth it only if "
                f"the line is not sold out."
            )
        return (
            f"Do not proceed on these numbers. Costs EUR {abs(delta_cost):,.0f} more over "
            f"{horizon_days:.0f} days than leaving the plant alone."
        )

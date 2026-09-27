"""The twin itself: one tick loop over every asset, every tick, forever.

Each tick runs the plant twice. The *real* pass carries the accumulated wear
and any injected faults, and its output has measurement noise added - that is
what a historian would have recorded. The *reference* pass runs each asset
as-new, fed the conditions its real counterpart actually measured, with every
degradation level pinned to zero and no noise - that is what that machine
should have done under exactly the operating point it saw.

Feeding the reference the *measured* inputs rather than letting it simulate a
parallel plant is what keeps the diagnosis local: a worn pump shows up as a
pump residual, not as a reactor residual caused by the reactor being starved.

Two passes rather than one is the whole design. It means no symptom anywhere
in this service is hard-coded: the residual that raises an alert is a genuine
disagreement between a physical model and a measurement, and every downstream
number (health, RUL, OEE, the work-order queue) is derived from that same
disagreement rather than asserted alongside it.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..analytics import kpis as kpi_calc
from ..analytics.anomaly import AnomalyEngine
from ..analytics.rul import RulEngine
from ..domain.models import (
    Alert,
    Area,
    AssetInfo,
    AssetSnapshot,
    AssetState,
    Criticality,
    Frame,
    Plant,
    PlantInfo,
    Severity,
    WorkOrder,
)
from ..store.timeseries import TimeSeriesStore
from .degradation import DegradationSet
from .faults import ActiveFault, FaultManager
from .physics import AssetModel, Bus, ObserverBus, SimContext, Tag, build_model


def _measure(tag: Tag, value: float, rng: random.Random) -> float:
    """Apply instrument noise, then the instrument's own range limits.

    A transmitter cannot report outside its calibrated span, so a zero flow
    reads zero rather than dithering negative.
    """
    reading = value + (rng.gauss(0.0, tag.sigma) if tag.sigma else 0.0)
    if tag.lo is not None:
        reading = max(tag.lo, reading)
    if tag.hi is not None:
        reading = min(tag.hi, reading)
    return reading


@dataclass
class AssetRuntime:
    """Everything mutable about one asset while the twin is running."""

    info: AssetInfo
    model: AssetModel
    degradation: DegradationSet
    tags: dict[str, Tag]
    state: dict[str, float]
    ref_state: dict[str, float]
    rng: random.Random
    maintenance_until: float = 0.0
    last_values: dict[str, float] = field(default_factory=dict)
    last_expected: dict[str, float] = field(default_factory=dict)


class TwinEngine:
    """Owns the plant, the clock, and everything derived from them."""

    def __init__(
        self,
        plant_file: Path,
        *,
        dt: float = 60.0,
        history_points: int = 3600,
        warmup_ticks: int = 120,
        seed: int = 20260927,
    ) -> None:
        self.dt = dt
        self.tick_count = 0
        self.sim_time = 0.0
        self.started_wall = time.time()

        self.warmup_ticks = warmup_ticks
        self.store = TimeSeriesStore(capacity=history_points)
        self.anomaly = AnomalyEngine(warmup=warmup_ticks)
        self.rul = RulEngine(sample_every_seconds=max(300.0, dt * 8))
        self.faults = FaultManager()

        self._bus = Bus()
        # The reference pass observes the real plant rather than simulating a
        # parallel one - see ObserverBus for why that distinction matters.
        self._ref_bus = ObserverBus(self._bus)
        self._subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self._frame: Frame | None = None
        self._seed = seed

        self.plant_info, self.areas, self.assets = self._load(plant_file, seed)

    # ------------------------------------------------------------------ load
    def _load(
        self, plant_file: Path, seed: int
    ) -> tuple[PlantInfo, list[Area], dict[str, AssetRuntime]]:
        raw: dict[str, Any] = yaml.safe_load(Path(plant_file).read_text())
        plant_info = PlantInfo(**raw["plant"])
        areas = [Area(**a) for a in raw["areas"]]

        assets: dict[str, AssetRuntime] = {}
        for index, entry in enumerate(raw["assets"]):
            design = entry.get("design", {}) or {}
            standby = bool(entry.get("standby", False))
            model = build_model(entry["kind"], entry["id"], design, standby=standby)

            tags = {tag.name: tag for tag in model.tags()}
            mode_specs = model.mode_specs()
            degradation = DegradationSet.from_specs(mode_specs)

            # Seed each asset part-way through life so the plant does not look
            # implausibly new on first boot, and so RUL has something to say
            # immediately. Kept modest: a well-run plant is mostly healthy, and
            # a dashboard that boots amber teaches operators to ignore it.
            # Deterministic, so demos are reproducible.
            init_rng = random.Random(seed + index * 977)
            for mode in degradation.modes.values():
                # Seed as a fraction of *this mode's* threshold, not as an
                # absolute level. A transmitter that needs recalibrating at
                # 0.70 would otherwise boot a quarter of the way through its
                # life while a bearing with a 1.0 threshold booted at a tenth.
                mode.level = round(init_rng.uniform(0.02, 0.17) * mode.spec.threshold, 4)

            info = AssetInfo(
                id=entry["id"],
                name=entry["name"],
                kind=entry["kind"],
                area=entry["area"],
                criticality=Criticality(entry.get("criticality", "medium")),
                manufacturer=entry.get("manufacturer"),
                model=entry.get("model"),
                commissioned=str(entry.get("commissioned")) if entry.get("commissioned") else None,
                position=[float(v) for v in entry.get("position", [0, 0, 0])],
                feeds=list(entry.get("feeds", [])),
                standby=standby,
                design=design,
                tags=[tag.spec() for tag in model.tags()],
                degradation_modes=[spec.name for spec in mode_specs],
            )

            for tag in model.tags():
                if tag.monitored:
                    self.anomaly.register(entry["id"], tag.name, tag.sigma)

            assets[entry["id"]] = AssetRuntime(
                info=info,
                model=model,
                degradation=degradation,
                tags=tags,
                state=model.initial_state(),
                ref_state=model.initial_state(),
                rng=random.Random(seed + index * 7919),
            )
        return plant_info, areas, assets

    # ------------------------------------------------------------------ tick
    def tick(self) -> Frame:
        self.tick_count += 1
        self.sim_time += self.dt
        ctx = SimContext(dt=self.dt, sim_time=self.sim_time)

        self.faults.advance(self.dt)
        self._apply_fault_rates()

        order = list(self.assets.values())

        # Real and reference are solved interleaved, asset by asset, rather
        # than as two separate sweeps.
        #
        # That ordering matters more than it looks. Some signals are read a
        # tick late by design - the chiller is solved before the reactor whose
        # jacket duty it serves - so a reference sweep run *after* the real
        # sweep would read this tick's value where its real counterpart read
        # last tick's. The resulting one-tick mismatch shows up as a residual
        # on every transient, and the console raises an alert about a
        # scheduling artefact. Interleaving guarantees both copies of an asset
        # observe the bus in exactly the same state.
        self._bus.begin_tick()
        self._ref_bus.begin_tick()
        zero_levels: dict[str, float] = {}
        real: dict[str, dict[str, float]] = {}
        reference: dict[str, dict[str, float]] = {}
        for rt in order:
            real[rt.info.id] = rt.model.solve(rt.state, rt.degradation.levels(), ctx, self._bus)
            reference[rt.info.id] = rt.model.solve(rt.ref_state, zero_levels, ctx, self._ref_bus)
            rt.model.anchor_reference(rt.state, rt.ref_state)

        snapshots: dict[str, AssetSnapshot] = {}
        states: dict[str, AssetState] = {}
        healths: dict[str, float] = {}
        criticalities: dict[str, Criticality] = {}
        total_power = 0.0

        for rt in order:
            aid = rt.info.id
            clean = real[aid]
            expected = reference[aid]

            # Instrument noise goes on last, so the bus that fed downstream
            # assets carried true process values rather than compounding noise.
            observed = {
                name: _measure(rt.tags[name], value, rt.rng) for name, value in clean.items()
            }

            residuals = self.anomaly.evaluate(
                aid,
                rt.info.name,
                {k: v for k, v in observed.items() if rt.tags[k].monitored},
                expected,
                self.sim_time,
                {name: tag.label for name, tag in rt.tags.items()},
                {name: tag.unit for name, tag in rt.tags.items()},
            )

            in_maintenance = self.sim_time < rt.maintenance_until
            if not in_maintenance:
                rt.degradation.advance(self.dt, rt.model.stress(clean))
            for name, mode in rt.degradation.modes.items():
                self.rul.observe(aid, name, mode.spec.threshold, mode.level, self.sim_time)

            health = rt.degradation.health()
            open_alerts = self.anomaly.open_count(aid)
            state = self._state_for(rt, health, open_alerts, in_maintenance)
            power = rt.model.power_kw(clean)

            for name, value in observed.items():
                self.store.record(aid, name, self.sim_time, value, expected.get(name))

            rt.last_values, rt.last_expected = observed, expected
            states[aid] = state
            healths[aid] = health
            criticalities[aid] = rt.info.criticality
            total_power += power

            snapshots[aid] = AssetSnapshot(
                id=aid,
                state=state,
                health=health,
                values={k: round(v, 5) for k, v in observed.items()},
                residuals=residuals,
                degradation=rt.degradation.levels(),
                rul=self.rul.estimates_for(aid),
                power_kw=round(power, 2),
                active_faults=[f.spec.label for f in self.faults.for_asset(aid)],
                open_alerts=open_alerts,
            )

        frame = Frame(
            tick=self.tick_count,
            sim_time=self.sim_time,
            wall_time=time.time(),
            assets=snapshots,
            kpis=kpi_calc.compute(
                states=states,
                healths=healths,
                criticalities=criticalities,
                # Gross rate, not the on-spec rate: quality is a separate OEE
                # term, and feeding the already-quality-adjusted figure in here
                # would square it.
                throughput_tph=self._bus.get("reactor_product_tph", 0.0),
                quality=self._bus.get("product_quality", 1.0),
                power_kw=total_power,
                design_rate_tph=self.plant_info.design_rate_tph,
                tariff_eur_kwh=self.plant_info.energy_tariff_eur_kwh,
                grid_intensity=self.plant_info.grid_intensity_kg_co2_kwh,
            ),
            alerts=self.anomaly.open_alerts(),
        )
        self._frame = frame
        return frame

    def prime(self, settle_ticks: int = 300, warm_ticks: int | None = None) -> None:
        """Bring the twin up ready to work, in two phases.

        **Settle** runs physics only. The reactor takes several residence
        times to reach equilibrium, and the reference copy settles on a
        slightly different trajectory to the real one. A detector that
        characterised "normal" during that transient would freeze a baseline
        taken from a plant that was still moving, then alarm on the settled
        steady state.

        **Warm** then runs real ticks, so the residual detectors fit their
        baselines and the history buffers fill. Without it the service answers
        every request for the first two minutes of its life with an empty
        chart and a detector that structurally cannot alert - which is
        indistinguishable, to anyone watching, from a plant with no problems.

        Both phases together cost well under a second, and the twin is useful
        on the first request it serves.
        """
        sim_time = 0.0
        for _ in range(settle_ticks):
            # Advance the clock while priming: anything scheduled off sim_time
            # (the product export slot, the air-header demand cycle) has to
            # actually run, or the twin settles into a state it will never
            # revisit once the real loop starts.
            sim_time += self.dt
            ctx = SimContext(dt=self.dt, sim_time=sim_time)
            self._bus.begin_tick()
            self._ref_bus.begin_tick()
            for rt in self.assets.values():
                readings = rt.model.solve(rt.state, rt.degradation.levels(), ctx, self._bus)
                rt.model.solve(rt.ref_state, {}, ctx, self._ref_bus)
                rt.model.anchor_reference(rt.state, rt.ref_state)

                # Age the plant and record the wear trend while priming. The
                # line did not come into existence when the dashboard was
                # opened, and Theil-Sen needs history before it will commit to
                # a projection - without this the work-order queue sits empty
                # for the first couple of minutes of every demo.
                rt.degradation.advance(self.dt, rt.model.stress(readings))
                for name, mode in rt.degradation.modes.items():
                    self.rul.observe(rt.info.id, name, mode.spec.threshold, mode.level, sim_time)
        self.sim_time = sim_time

        # Phase 2: real ticks, so detectors warm up and history fills.
        for _ in range(warm_ticks if warm_ticks is not None else self.warmup_ticks + 30):
            self.tick()

        # Anything raised while the baselines were still being fitted is an
        # artefact of the fit, not a finding. Start with a clean board.
        self.anomaly.discard_all()

    def _apply_fault_rates(self) -> None:
        for aid, rt in self.assets.items():
            rates = self.faults.rates_for(aid)
            for name, mode in rt.degradation.modes.items():
                mode.fault_rate_per_day = rates.get(name, 0.0)

    def _state_for(
        self, rt: AssetRuntime, health: float, open_alerts: int, in_maintenance: bool
    ) -> AssetState:
        if in_maintenance:
            return AssetState.MAINTENANCE
        if rt.info.standby:
            return AssetState.STANDBY
        # A machine is only "down" once a mode has actually reached its
        # intervention threshold. An open alert means degraded, not stopped -
        # calling every alert an outage would make availability meaningless.
        if health <= 25.0 or any(m.breached for m in rt.degradation.modes.values()):
            return AssetState.FAULT
        if open_alerts > 0 or health < 80.0:
            return AssetState.DEGRADED
        return AssetState.RUNNING

    # ------------------------------------------------------------ operations
    def inject_fault(
        self, asset_id: str, fault_id: str, severity: float, ramp_hours: float
    ) -> ActiveFault:
        if asset_id not in self.assets:
            raise KeyError(asset_id)
        return self.faults.inject(asset_id, fault_id, severity, ramp_hours, self.sim_time)

    def clear_fault(self, fault_id: str) -> bool:
        return self.faults.clear(fault_id) is not None

    def perform_maintenance(self, asset_id: str, mode: str | None = None) -> dict[str, Any]:
        """Restore one or all wear modes on an asset to as-new.

        Also resets the RUL history and closes open alerts, because after an
        overhaul the old trend is no longer evidence about the new machine.
        """
        rt = self.assets.get(asset_id)
        if rt is None:
            raise KeyError(asset_id)

        restored: list[str] = []
        downtime_h = 0.0
        cost = 0.0
        for name, mode_state in rt.degradation.modes.items():
            if mode is not None and name != mode:
                continue
            downtime_h = max(downtime_h, mode_state.spec.downtime_h)
            cost += mode_state.spec.cost_eur
            mode_state.reset()
            restored.append(name)

        if not restored:
            raise KeyError(f"{asset_id} has no degradation mode '{mode}'")

        self.faults.clear_for_asset(asset_id, mode)
        self.anomaly.clear_for_asset(asset_id, self.sim_time)
        self.rul.reset(asset_id, mode)
        # Hold the asset in MAINTENANCE for the work's duration so the effect
        # on availability shows up in OEE rather than being free.
        rt.maintenance_until = self.sim_time + downtime_h * 3600.0
        rt.state = rt.model.initial_state()

        return {
            "asset_id": asset_id,
            "restored": restored,
            "downtime_h": downtime_h,
            "cost_eur": round(cost, 2),
            "back_online_sim_time": rt.maintenance_until,
        }

    def work_orders(self) -> list[WorkOrder]:
        """Rank every pending intervention by risk, not by calendar date."""
        orders: list[WorkOrder] = []
        for aid, rt in self.assets.items():
            weight = kpi_calc.CRITICALITY_WEIGHT.get(rt.info.criticality, 1.0)
            for estimate in self.rul.estimates_for(aid):
                spec = rt.degradation.modes[estimate.mode].spec
                hours = estimate.hours_remaining
                if hours is None or hours > 24 * 180:
                    continue  # nothing actionable inside a planning horizon

                urgency = 1.0 / (1.0 + hours / 168.0)  # 1 week reference
                risk = min(100.0, weight * urgency * 32.0 * (0.5 + estimate.confidence))

                if hours < 72:
                    severity = Severity.CRITICAL
                elif hours < 336:
                    severity = Severity.WARNING
                else:
                    severity = Severity.INFO

                orders.append(
                    WorkOrder(
                        asset_id=aid,
                        asset_name=rt.info.name,
                        mode=estimate.mode,
                        action=spec.action,
                        due_in_hours=round(hours, 1),
                        severity=severity,
                        criticality=rt.info.criticality,
                        risk_score=round(risk, 1),
                        estimated_downtime_h=spec.downtime_h,
                        estimated_cost_eur=spec.cost_eur,
                        rationale=(
                            f"{spec.label} at {estimate.level * 100:.1f}% of its intervention "
                            f"threshold, trending {estimate.trend_per_day * 100:.2f}%/day "
                            f"(confidence {estimate.confidence:.0%}). {spec.effect}"
                        ),
                    )
                )
        orders.sort(key=lambda o: o.risk_score, reverse=True)
        return orders

    # ------------------------------------------------------------- accessors
    def plant(self) -> Plant:
        return Plant(
            plant=self.plant_info,
            areas=self.areas,
            assets=[rt.info for rt in self.assets.values()],
        )

    def frame(self) -> Frame:
        return self._frame if self._frame is not None else self.tick()

    def alerts(self, limit: int = 200, include_cleared: bool = True) -> list[Alert]:
        return self.anomaly.all_alerts(limit=limit, include_cleared=include_cleared)

    # ------------------------------------------------------------- lifecycle
    async def run(self, interval: float) -> None:
        """Advance the twin on a fixed wall-clock cadence and fan out frames."""
        while True:
            started = time.perf_counter()
            try:
                frame = await asyncio.to_thread(self.tick)
                self._broadcast(frame)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - keep the twin alive
                import traceback

                traceback.print_exc()
            elapsed = time.perf_counter() - started
            await asyncio.sleep(max(0.0, interval - elapsed))

    def start(self, interval: float) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run(interval))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _broadcast(self, frame: Frame) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                # A slow console must never back-pressure the simulation.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(frame)

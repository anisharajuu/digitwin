"""Degradation modes: the slow-moving state that makes a twin worth running.

Every asset carries one or more wear mechanisms as a dimensionless level in
``[0, 1]``, where ``1.0`` is "this needs intervention now". Levels advance on a
base rate drawn from the asset's duty, are accelerated by operating stress
(cavitation, over-temperature, high load) and by any injected fault, and are
reset by a maintenance action.

The levels are deliberately *not* readable by any sensor. They are the hidden
state the analytics layer has to infer from residuals, which is the whole point
of the exercise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SECONDS_PER_DAY = 86_400.0


@dataclass(frozen=True)
class ModeSpec:
    """Static description of one wear mechanism."""

    name: str
    label: str
    #: Level gained per day of normal-duty operation. A rate of 0.002
    #: implies ~500 days from as-new to intervention under nominal stress.
    base_rate_per_day: float
    #: Level at which the mode is considered to demand intervention.
    threshold: float = 1.0
    #: Maintenance activity that restores this mode to as-new.
    action: str = "Inspect and service"
    #: What the operator actually sees when this mode advances.
    effect: str = ""
    #: Hours of downtime a planned intervention costs.
    downtime_h: float = 4.0
    #: Parts plus labour for a planned intervention, in euros.
    cost_eur: float = 2_500.0


@dataclass
class ModeState:
    """Live wear state for one mechanism on one asset."""

    spec: ModeSpec
    level: float = 0.0
    #: Extra level/day contributed by an injected fault. Ramped in by the
    #: fault manager rather than applied as a step, so trends stay realistic.
    fault_rate_per_day: float = 0.0
    fault_id: str | None = None

    def advance(self, dt_seconds: float, stress: float = 1.0) -> None:
        """Advance wear by ``dt_seconds`` of operation at the given stress.

        ``stress`` is a multiplier on the base rate: 1.0 is nominal duty, 3.0
        is a pump running in cavitation, 0.0 is an idle standby machine that
        is not wearing at all.
        """
        rate = self.spec.base_rate_per_day * max(0.0, stress) + self.fault_rate_per_day
        self.level = _clamp(self.level + rate * (dt_seconds / SECONDS_PER_DAY))

    def reset(self) -> None:
        """Restore to as-new and drop any fault driving it."""
        self.level = 0.0
        self.fault_rate_per_day = 0.0
        self.fault_id = None

    @property
    def breached(self) -> bool:
        return self.level >= self.spec.threshold

    @property
    def fraction_of_threshold(self) -> float:
        return self.level / self.spec.threshold if self.spec.threshold > 0 else 0.0


@dataclass
class DegradationSet:
    """The collection of wear mechanisms belonging to one asset."""

    modes: dict[str, ModeState] = field(default_factory=dict)

    @classmethod
    def from_specs(cls, specs: list[ModeSpec], initial: dict[str, float] | None = None):
        initial = initial or {}
        return cls(
            modes={
                spec.name: ModeState(spec=spec, level=_clamp(initial.get(spec.name, 0.0)))
                for spec in specs
            }
        )

    def level(self, name: str) -> float:
        mode = self.modes.get(name)
        return mode.level if mode else 0.0

    def levels(self) -> dict[str, float]:
        return {name: round(mode.level, 5) for name, mode in self.modes.items()}

    def advance(self, dt_seconds: float, stress: dict[str, float] | None = None) -> None:
        stress = stress or {}
        for name, mode in self.modes.items():
            mode.advance(dt_seconds, stress.get(name, 1.0))

    def health(self) -> float:
        """0-100 health index: the worst mode dominates, the rest contribute.

        A single mechanism at threshold should read as unhealthy even if every
        other mechanism is pristine, so the worst mode is weighted heavily
        rather than averaged away.
        """
        if not self.modes:
            return 100.0
        fractions = [min(1.0, m.fraction_of_threshold) for m in self.modes.values()]
        worst = max(fractions)
        mean = sum(fractions) / len(fractions)
        damage = 0.75 * worst + 0.25 * mean
        return round(max(0.0, 100.0 * (1.0 - damage)), 1)

    def snapshot(self) -> dict[str, float]:
        return self.levels()

    def clone(self) -> DegradationSet:
        """Deep-ish copy used by what-if projections, which must not mutate live state."""
        return DegradationSet(
            modes={
                name: ModeState(
                    spec=mode.spec,
                    level=mode.level,
                    fault_rate_per_day=mode.fault_rate_per_day,
                    fault_id=mode.fault_id,
                )
                for name, mode in self.modes.items()
            }
        )


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))

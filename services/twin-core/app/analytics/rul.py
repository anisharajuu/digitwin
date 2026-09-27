"""Remaining-useful-life estimation.

Wear is not linear and the samples are noisy, so an ordinary least-squares fit
is a poor choice: one bad point drags the slope and the projected date jumps
around, which destroys an operator's trust in the number within about a day.

Theil-Sen is used instead - the median of all pairwise slopes. It tolerates up
to ~29% contaminated samples before it breaks down, and because it is a median
it moves smoothly as new data arrives. The spread of those pairwise slopes also
falls out for free, which gives an honest confidence figure rather than a
fabricated one.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field

from ..domain.models import RulEstimate

SECONDS_PER_DAY = 86_400.0
#: Minimum samples before any projection is published.
MIN_SAMPLES = 12
#: Samples retained per mode. At the default sampling interval this is a
#: couple of simulated weeks of lever arm, which is plenty to fit a trend.
WINDOW = 180


@dataclass
class ModeTracker:
    """Rolling history of one degradation mode's level."""

    asset_id: str
    mode: str
    threshold: float
    days: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))
    levels: deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))

    def observe(self, sim_time: float, level: float) -> None:
        self.days.append(sim_time / SECONDS_PER_DAY)
        self.levels.append(level)

    def estimate(self) -> RulEstimate:
        level = self.levels[-1] if self.levels else 0.0
        slope, confidence = self._theil_sen()

        hours: float | None
        if slope <= 1e-9:
            hours = None  # not trending toward failure on current evidence
        else:
            remaining = max(0.0, self.threshold - level)
            hours = remaining / slope * 24.0
            # Beyond a couple of years the number is meaningless; say so by
            # capping rather than printing a spuriously precise date.
            hours = min(hours, 24.0 * 730.0)

        return RulEstimate(
            mode=self.mode,
            level=round(level, 4),
            threshold=self.threshold,
            hours_remaining=round(hours, 1) if hours is not None else None,
            confidence=round(confidence, 3),
            trend_per_day=round(slope, 6),
        )

    def _theil_sen(self) -> tuple[float, float]:
        n = len(self.levels)
        if n < MIN_SAMPLES:
            return 0.0, 0.0

        xs, ys = list(self.days), list(self.levels)
        slopes: list[float] = []
        # Sub-sample the pair set on long windows: the median is stable well
        # before we need all ~16k pairs, and this keeps the tick cheap.
        stride = 1 if n <= 60 else 2
        for i in range(0, n - 1, stride):
            for j in range(i + 1, n, stride):
                dx = xs[j] - xs[i]
                if dx > 1e-9:
                    slopes.append((ys[j] - ys[i]) / dx)
        if not slopes:
            return 0.0, 0.0

        slopes.sort()
        median = statistics.median(slopes)

        # Confidence: how tightly the pairwise slopes agree, scaled by how
        # much history we have. A wide spread means "we don't really know yet".
        q1 = slopes[len(slopes) // 4]
        q3 = slopes[(3 * len(slopes)) // 4]
        spread = q3 - q1
        if abs(median) < 1e-12:
            agreement = 0.0
        else:
            agreement = max(0.0, 1.0 - min(1.0, spread / (abs(median) * 2.0)))
        maturity = min(1.0, n / float(WINDOW / 2))
        return median, agreement * 0.75 + maturity * 0.25


class RulEngine:
    """Tracks every degradation mode on every asset and projects each forward."""

    def __init__(self, sample_every_seconds: float = 900.0) -> None:
        self.sample_every = sample_every_seconds
        self._trackers: dict[tuple[str, str], ModeTracker] = {}
        self._last_sample: dict[tuple[str, str], float] = {}

    def observe(
        self, asset_id: str, mode: str, threshold: float, level: float, sim_time: float
    ) -> None:
        key = (asset_id, mode)
        last = self._last_sample.get(key)
        if last is not None and sim_time - last < self.sample_every:
            return
        tracker = self._trackers.get(key)
        if tracker is None:
            tracker = ModeTracker(asset_id=asset_id, mode=mode, threshold=threshold)
            self._trackers[key] = tracker
        tracker.observe(sim_time, level)
        self._last_sample[key] = sim_time

    def estimates_for(self, asset_id: str) -> list[RulEstimate]:
        out = [t.estimate() for (aid, _m), t in self._trackers.items() if aid == asset_id]
        # Soonest failure first - that is the one an operator has to act on.
        out.sort(key=lambda e: (e.hours_remaining is None, e.hours_remaining or 0.0))
        return out

    def reset(self, asset_id: str, mode: str | None = None) -> None:
        for key in list(self._trackers):
            if key[0] == asset_id and (mode is None or key[1] == mode):
                self._trackers.pop(key, None)
                self._last_sample.pop(key, None)

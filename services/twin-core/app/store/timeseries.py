"""In-memory time-series retention.

Deliberately not a database. A twin at 1 Hz over ten assets produces ~70
series; an hour of history is a few megabytes of floats, and keeping it in
process means the console's chart requests are sub-millisecond with no
operational surface to run. Swapping this for TimescaleDB or InfluxDB is a
matter of reimplementing :class:`TimeSeriesStore` - nothing above it knows
where the points live.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class Series:
    """A fixed-capacity ring of (timestamp, value) pairs for one tag."""

    capacity: int
    times: deque[float] = field(default_factory=deque)
    values: deque[float] = field(default_factory=deque)
    expected: deque[float] = field(default_factory=deque)

    def append(self, t: float, v: float, expected: float | None = None) -> None:
        if len(self.times) >= self.capacity:
            self.times.popleft()
            self.values.popleft()
            if self.expected:
                self.expected.popleft()
        self.times.append(t)
        self.values.append(v)
        self.expected.append(expected if expected is not None else v)

    def tail(self, n: int) -> tuple[list[float], list[float], list[float]]:
        if n <= 0 or not self.times:
            return [], [], []
        n = min(n, len(self.times))
        return (
            list(self.times)[-n:],
            list(self.values)[-n:],
            list(self.expected)[-n:],
        )

    def recent_values(self, n: int) -> list[float]:
        if not self.values:
            return []
        n = min(n, len(self.values))
        return list(self.values)[-n:]

    def __len__(self) -> int:
        return len(self.times)


class TimeSeriesStore:
    """Every tag on every asset, keyed ``(asset_id, tag)``."""

    def __init__(self, capacity: int = 3600) -> None:
        self.capacity = capacity
        self._series: dict[tuple[str, str], Series] = {}

    def record(
        self, asset_id: str, tag: str, t: float, value: float, expected: float | None = None
    ) -> None:
        key = (asset_id, tag)
        series = self._series.get(key)
        if series is None:
            series = Series(capacity=self.capacity)
            self._series[key] = series
        series.append(t, value, expected)

    def get(self, asset_id: str, tag: str) -> Series | None:
        return self._series.get((asset_id, tag))

    def tags_for(self, asset_id: str) -> list[str]:
        return sorted(tag for (aid, tag) in self._series if aid == asset_id)

    def size(self) -> int:
        return sum(len(s) for s in self._series.values())

    def series_count(self) -> int:
        return len(self._series)

"""Runtime configuration, read once at import from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Everything tunable about a running twin-core process."""

    plant_file: Path = field(
        default_factory=lambda: Path(
            os.getenv("TWIN_PLANT_FILE") or APP_DIR / "plant" / "aurora_works.yaml"
        )
    )

    #: Wall-clock seconds between simulation ticks.
    tick_seconds: float = field(default_factory=lambda: _env_float("TWIN_TICK_SECONDS", 1.0))

    #: Simulated seconds per wall-clock second. The default (60x) means a
    #: demo shows an hour of plant behaviour every minute, which is fast
    #: enough for degradation to be visible without being cartoonish.
    sim_speed: float = field(default_factory=lambda: _env_float("TWIN_SIM_SPEED", 60.0))

    #: Points retained per tag in the in-memory ring buffer.
    history_points: int = field(default_factory=lambda: _env_int("TWIN_HISTORY_POINTS", 3600))

    #: Ticks the residual detector observes before it will raise anything.
    warmup_ticks: int = field(default_factory=lambda: _env_int("TWIN_WARMUP_TICKS", 120))

    cors_origins: list[str] = field(
        default_factory=lambda: _env_list(
            "TWIN_CORS_ORIGINS",
            [
                "http://localhost:5173",
                "http://localhost:4173",
                "http://127.0.0.1:5173",
            ],
        )
    )

    @property
    def sim_dt(self) -> float:
        """Simulated seconds advanced by a single tick."""
        return self.tick_seconds * self.sim_speed


settings = Settings()

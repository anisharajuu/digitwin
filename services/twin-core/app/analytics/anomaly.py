"""Model-residual anomaly detection.

Threshold alarms tell you a machine has already failed. The point of a twin is
to notice the moment a machine stops behaving like *itself*, which happens far
earlier and is invisible to any fixed limit.

For every monitored tag the engine hands us two numbers: what the sensor read,
and what the as-new physics model says it should have read under identical
operating conditions. The difference is the residual. During a warm-up window
we characterise the residual's normal distribution using the median and the
median absolute deviation - robust statistics, so a fault arriving during
warm-up widens the band rather than poisoning the centre. After that, the
residual is scored in robust standard deviations, smoothed with an EWMA to
reject single-sample spikes, and required to hold over several consecutive
samples before anything is raised.

That combination is what keeps the false-positive rate survivable on a plant
with seventy live tags.
"""

from __future__ import annotations

import statistics
import uuid
from collections import deque
from dataclasses import dataclass, field

from ..domain.models import Alert, Residual, Severity

#: Robust-sigma at which a tag is flagged as drifting.
WARN_Z = 4.0
#: Robust-sigma at which a tag is flagged as a hard deviation.
CRITICAL_Z = 7.5
#: Consecutive breaching samples required before an alert is raised.
PERSISTENCE = 6
#: Consecutive in-band samples required before an alert clears.
CLEAR_PERSISTENCE = 20
#: EWMA smoothing factor on the z-score.
EWMA_ALPHA = 0.25


@dataclass
class TagDetector:
    """Residual detector for a single tag on a single asset."""

    asset_id: str
    tag: str
    noise_sigma: float = 0.0
    warmup: int = 120

    _window: deque[float] = field(default_factory=lambda: deque(maxlen=600))
    _centre: float = 0.0
    _scale: float = 1.0
    _ewma_z: float = 0.0
    _seen: int = 0
    _breach_run: int = 0
    _clear_run: int = 0
    _ready: bool = False

    def update(self, observed: float, expected: float) -> Residual:
        residual = observed - expected
        self._seen += 1
        self._window.append(residual)

        if not self._ready:
            # Keep re-fitting while we warm up, then freeze the baseline so a
            # slow drift cannot quietly redefine "normal" underneath us.
            if self._seen >= max(20, self.warmup // 4):
                self._fit()
            if self._seen >= self.warmup:
                self._fit()
                self._ready = True
            return Residual(
                tag=self.tag,
                observed=observed,
                expected=expected,
                residual=residual,
                z=0.0,
                breached=False,
            )

        z = (residual - self._centre) / self._scale
        self._ewma_z = EWMA_ALPHA * z + (1.0 - EWMA_ALPHA) * self._ewma_z

        if abs(self._ewma_z) >= WARN_Z:
            self._breach_run += 1
            self._clear_run = 0
        else:
            self._clear_run += 1
            self._breach_run = 0

        return Residual(
            tag=self.tag,
            observed=observed,
            expected=expected,
            residual=residual,
            z=self._ewma_z,
            breached=self._breach_run >= PERSISTENCE,
        )

    def _fit(self) -> None:
        data = list(self._window)
        if len(data) < 8:
            return
        centre = statistics.median(data)
        mad = statistics.median([abs(x - centre) for x in data])
        robust_sigma = 1.4826 * mad
        # Floor the scale so a quiet tag cannot manufacture enormous z-scores
        # out of quantisation noise.
        self._centre = centre
        self._scale = max(robust_sigma, self.noise_sigma, 1e-6)

    @property
    def severity(self) -> Severity:
        magnitude = abs(self._ewma_z)
        if magnitude >= CRITICAL_Z:
            return Severity.CRITICAL
        if magnitude >= WARN_Z:
            return Severity.WARNING
        return Severity.INFO

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def z(self) -> float:
        return self._ewma_z

    @property
    def should_clear(self) -> bool:
        return self._clear_run >= CLEAR_PERSISTENCE


class AnomalyEngine:
    """Owns every tag detector and the alert lifecycle built on top of them."""

    def __init__(self, warmup: int = 120) -> None:
        self.warmup = warmup
        self._detectors: dict[tuple[str, str], TagDetector] = {}
        self._alerts: dict[str, Alert] = {}
        self._open_by_key: dict[tuple[str, str], str] = {}

    def register(self, asset_id: str, tag: str, noise_sigma: float) -> None:
        key = (asset_id, tag)
        if key not in self._detectors:
            self._detectors[key] = TagDetector(
                asset_id=asset_id, tag=tag, noise_sigma=noise_sigma, warmup=self.warmup
            )

    def evaluate(
        self,
        asset_id: str,
        asset_name: str,
        observed: dict[str, float],
        expected: dict[str, float],
        sim_time: float,
        labels: dict[str, str],
        units: dict[str, str],
    ) -> dict[str, Residual]:
        """Score every registered tag on one asset and fold alerts forward."""
        residuals: dict[str, Residual] = {}
        for tag, value in observed.items():
            detector = self._detectors.get((asset_id, tag))
            if detector is None:
                continue
            residual = detector.update(value, expected.get(tag, value))
            residuals[tag] = residual
            self._reconcile(detector, asset_id, asset_name, residual, sim_time, labels, units)
        return residuals

    def _reconcile(
        self,
        detector: TagDetector,
        asset_id: str,
        asset_name: str,
        residual: Residual,
        sim_time: float,
        labels: dict[str, str],
        units: dict[str, str],
    ) -> None:
        key = (asset_id, detector.tag)
        open_id = self._open_by_key.get(key)
        label = labels.get(detector.tag, detector.tag)
        unit = units.get(detector.tag, "")

        if residual.breached:
            direction = "above" if residual.z > 0 else "below"
            detail = (
                f"{label} is reading {abs(residual.residual):.3g} {unit} {direction} "
                f"the value the twin predicts for the current operating point "
                f"({residual.observed:.4g} observed vs {residual.expected:.4g} modelled, "
                f"{abs(residual.z):.1f} sigma)."
            )
            if open_id is None:
                alert = Alert(
                    id=f"alr_{uuid.uuid4().hex[:10]}",
                    asset_id=asset_id,
                    tag=detector.tag,
                    severity=detector.severity,
                    title=f"{asset_name}: {label} deviating from model",
                    detail=detail,
                    raised_at=sim_time,
                    z=round(residual.z, 2),
                )
                self._alerts[alert.id] = alert
                self._open_by_key[key] = alert.id
            else:
                alert = self._alerts[open_id]
                # Escalation is allowed; de-escalation is not, so an alert
                # that peaked at critical stays visible as critical until it
                # actually clears.
                if detector.severity == Severity.CRITICAL:
                    alert.severity = Severity.CRITICAL
                alert.detail = detail
                alert.z = round(residual.z, 2)
        elif open_id is not None and detector.should_clear:
            alert = self._alerts[open_id]
            alert.cleared_at = sim_time
            self._open_by_key.pop(key, None)

    # -- alert access ------------------------------------------------------
    #: Ranking order for the feed. Severity first, then how far off model.
    _SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}

    def open_alerts(self) -> list[Alert]:
        """Open alerts, worst first.

        Ordering by severity and then by the size of the deviation puts the
        asset that is actually failing at the top of the feed. Secondary
        indications on neighbouring equipment - a chiller whose duty fell
        because the pump feeding the line is worn - are real, and worth
        showing, but they should not be what an operator reads first.
        """
        alerts = [a for a in self._alerts.values() if a.cleared_at is None]
        alerts.sort(key=lambda a: (self._SEVERITY_RANK.get(a.severity, 3), -abs(a.z or 0.0)))
        return alerts

    def open_count(self, asset_id: str) -> int:
        return sum(
            1 for a in self._alerts.values() if a.asset_id == asset_id and a.cleared_at is None
        )

    def all_alerts(self, limit: int = 200, include_cleared: bool = True) -> list[Alert]:
        alerts = list(self._alerts.values())
        if not include_cleared:
            alerts = [a for a in alerts if a.cleared_at is None]
        alerts.sort(key=lambda a: a.raised_at, reverse=True)
        return alerts[:limit]

    def acknowledge(self, alert_id: str) -> Alert | None:
        alert = self._alerts.get(alert_id)
        if alert is not None:
            alert.acknowledged = True
        return alert

    def discard_all(self) -> None:
        """Forget every alert entirely, as opposed to clearing them.

        Used once at the end of warm-up: an alert raised while a baseline was
        still being fitted is an artefact of the fit, and leaving it in the
        history would teach an operator that the feed is noisy.
        """
        self._alerts.clear()
        self._open_by_key.clear()
        for detector in self._detectors.values():
            detector._breach_run = 0
            detector._clear_run = 0
            detector._ewma_z = 0.0

    def clear_for_asset(self, asset_id: str, sim_time: float) -> int:
        """Close every open alert on an asset, e.g. after maintenance."""
        closed = 0
        for key, alert_id in list(self._open_by_key.items()):
            if key[0] != asset_id:
                continue
            alert = self._alerts.get(alert_id)
            if alert is not None:
                alert.cleared_at = sim_time
                closed += 1
            self._open_by_key.pop(key, None)
        # Reset the detectors too - after an overhaul the baseline is new.
        for (aid, _tag), detector in self._detectors.items():
            if aid == asset_id:
                detector._breach_run = 0
                detector._ewma_z = 0.0
        return closed

    @property
    def ready(self) -> bool:
        detectors = list(self._detectors.values())
        return bool(detectors) and all(d.ready for d in detectors)

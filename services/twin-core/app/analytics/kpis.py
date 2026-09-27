"""Plant-level KPIs: the numbers a plant manager is actually measured on.

OEE is computed the standard way (availability x performance x quality) but
each term is sourced from the twin rather than from a manual log:

* **availability** - criticality-weighted, driven by which assets are in a
  fault or maintenance state right now.
* **performance** - achieved throughput against the line's design rate.
* **quality** - on-spec yield end to end: reactor conversion multiplied by
  the separator's split efficiency. Unreacted feed and a failed phase split
  both cost saleable tonnes, so both belong in the same term.

Energy intensity, cost and CO2 all fall out of the same tick, which is the
point: reliability and sustainability reporting stop being separate exercises.
"""

from __future__ import annotations

from ..domain.models import AssetState, Criticality, Kpis

#: How heavily each criticality class pulls on plant availability and health.
CRITICALITY_WEIGHT: dict[Criticality, float] = {
    Criticality.LOW: 0.5,
    Criticality.MEDIUM: 1.0,
    Criticality.HIGH: 2.0,
    Criticality.CRITICAL: 4.0,
}


def compute(
    *,
    states: dict[str, AssetState],
    healths: dict[str, float],
    criticalities: dict[str, Criticality],
    throughput_tph: float,
    quality: float,
    power_kw: float,
    design_rate_tph: float,
    tariff_eur_kwh: float,
    grid_intensity: float,
) -> Kpis:
    total_weight = 0.0
    down_weight = 0.0
    health_weighted = 0.0

    for asset_id, state in states.items():
        weight = CRITICALITY_WEIGHT.get(criticalities.get(asset_id, Criticality.MEDIUM), 1.0)
        total_weight += weight
        health_weighted += weight * healths.get(asset_id, 100.0)
        if state in (AssetState.FAULT, AssetState.MAINTENANCE):
            down_weight += weight

    availability = 1.0 - (down_weight / total_weight if total_weight else 0.0)
    performance = throughput_tph / design_rate_tph if design_rate_tph > 0 else 0.0
    performance = min(performance, 1.15)  # a line can beat nameplate, but not absurdly
    quality = max(0.0, min(1.0, quality))
    oee = availability * performance * quality

    energy_intensity = power_kw / throughput_tph if throughput_tph > 0.5 else 0.0
    plant_health = health_weighted / total_weight if total_weight else 100.0

    return Kpis(
        throughput_tph=round(throughput_tph, 2),
        availability=round(availability, 4),
        performance=round(performance, 4),
        quality=round(quality, 4),
        oee=round(oee, 4),
        power_kw=round(power_kw, 1),
        energy_intensity_kwh_t=round(energy_intensity, 3),
        co2_kg_h=round(power_kw * grid_intensity, 1),
        energy_cost_eur_h=round(power_kw * tariff_eur_kwh, 2),
        plant_health=round(plant_health, 1),
    )

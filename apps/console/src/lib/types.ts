/**
 * Mirrors the pydantic models in `services/twin-core/app/domain/models.py`.
 *
 * Kept hand-written rather than generated: the surface is small, and a
 * generated client would obscure the one thing worth reading here, which is
 * what the twin actually publishes on every tick.
 */

export type AssetState = 'running' | 'standby' | 'degraded' | 'fault' | 'maintenance'
export type Severity = 'info' | 'warning' | 'critical'
export type Criticality = 'low' | 'medium' | 'high' | 'critical'
export type TagClass = 'process' | 'condition' | 'electrical' | 'derived'

export interface TagSpec {
  name: string
  label: string
  unit: string
  tag_class: TagClass
  lo: number | null
  hi: number | null
  precision: number
  monitored: boolean
}

export interface Area {
  id: string
  name: string
  colour: string
}

export interface PlantInfo {
  id: string
  name: string
  line: string
  location: string
  timezone: string
  product: string
  design_rate_tph: number
  energy_tariff_eur_kwh: number
  grid_intensity_kg_co2_kwh: number
}

export interface AssetInfo {
  id: string
  name: string
  kind: string
  area: string
  criticality: Criticality
  manufacturer: string | null
  model: string | null
  commissioned: string | null
  position: [number, number, number]
  feeds: string[]
  standby: boolean
  design: Record<string, number | string>
  tags: TagSpec[]
  degradation_modes: string[]
}

export interface Plant {
  plant: PlantInfo
  areas: Area[]
  assets: AssetInfo[]
}

/** One tag's disagreement between the physics model and the sensor. */
export interface Residual {
  tag: string
  observed: number
  expected: number
  residual: number
  z: number
  breached: boolean
}

export interface RulEstimate {
  mode: string
  level: number
  threshold: number
  hours_remaining: number | null
  confidence: number
  trend_per_day: number
}

export interface AssetSnapshot {
  id: string
  state: AssetState
  health: number
  values: Record<string, number>
  residuals: Record<string, Residual>
  degradation: Record<string, number>
  rul: RulEstimate[]
  power_kw: number
  active_faults: string[]
  open_alerts: number
}

export interface Kpis {
  throughput_tph: number
  availability: number
  performance: number
  quality: number
  oee: number
  power_kw: number
  energy_intensity_kwh_t: number
  co2_kg_h: number
  energy_cost_eur_h: number
  plant_health: number
}

export interface Alert {
  id: string
  asset_id: string
  tag: string | null
  severity: Severity
  title: string
  detail: string
  raised_at: number
  cleared_at: number | null
  acknowledged: boolean
  z: number | null
}

export interface Frame {
  tick: number
  sim_time: number
  wall_time: number
  assets: Record<string, AssetSnapshot>
  kpis: Kpis
  alerts: Alert[]
}

export interface TelemetryPoint {
  t: number
  v: number
}

export interface TelemetrySeries {
  asset_id: string
  tag: string
  spec: TagSpec
  points: TelemetryPoint[]
  expected: TelemetryPoint[]
}

export interface WorkOrder {
  asset_id: string
  asset_name: string
  mode: string
  action: string
  due_in_hours: number | null
  severity: Severity
  criticality: Criticality
  risk_score: number
  estimated_downtime_h: number
  estimated_cost_eur: number
  rationale: string
}

export interface DegradationDetail {
  name: string
  label: string
  level: number
  threshold: number
  action: string
  effect: string
  downtime_h: number
  cost_eur: number
}

export interface InjectableFault {
  id: string
  label: string
  mode: string
  description: string
  symptom: string
}

export interface ActiveFault {
  id: string
  asset_id: string
  fault: string
  label: string
  mode: string
  severity: number
  ramp_hours: number
  progress: number
  symptom: string
}

export interface AssetDetail {
  info: AssetInfo
  snapshot: AssetSnapshot | null
  degradation_detail: DegradationDetail[]
  injectable_faults: InjectableFault[]
  active_faults: ActiveFault[]
}

export interface ScenarioChange {
  asset_id: string
  parameter: string
  value?: number | null
}

export interface ScenarioSeriesPoint {
  day: number
  throughput_tph: number
  power_kw: number
  oee: number
  plant_health: number
  energy_intensity_kwh_t: number
}

export interface ScenarioOutcome {
  label: string
  series: ScenarioSeriesPoint[]
  total_energy_mwh: number
  total_production_t: number
  total_cost_eur: number
  total_co2_t: number
  mean_oee: number
  end_health: number
  unplanned_events: number
}

export interface ScenarioResult {
  name: string
  horizon_days: number
  baseline: ScenarioOutcome
  proposed: ScenarioOutcome
  delta_cost_eur: number
  delta_production_t: number
  delta_co2_t: number
  delta_oee: number
  verdict: string
  compute_ms: number
}

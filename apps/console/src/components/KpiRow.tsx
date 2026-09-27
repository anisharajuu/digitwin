/** The six numbers the plant is run on, with their recent trend. */

import { Sparkline } from './Primitives'
import { eur, healthColour, num, pct } from '../lib/format'
import { useTwin } from '../state/useTwin'

interface Tile {
  label: string
  value: string
  unit?: string
  series: number[]
  colour: string
  hint: string
}

export default function KpiRow() {
  const { frame, history } = useTwin()
  if (!frame) return null

  const k = frame.kpis
  const trail = <T,>(pick: (h: (typeof history)[number]) => T) => history.slice(-90).map(pick)

  const tiles: Tile[] = [
    {
      label: 'OEE',
      value: pct(k.oee),
      series: trail((h) => h.oee),
      colour: k.oee > 0.8 ? '#34d399' : k.oee > 0.65 ? '#fbbf24' : '#fb7185',
      hint: `A ${pct(k.availability, 1)} x P ${pct(k.performance, 1)} x Q ${pct(k.quality, 1)}`,
    },
    {
      label: 'Throughput',
      value: num(k.throughput_tph, 1),
      unit: 't/h',
      series: trail((h) => h.throughput_tph),
      colour: '#22d3ee',
      hint: 'Gross rate through the reactor',
    },
    {
      label: 'Plant health',
      value: num(k.plant_health, 1),
      series: trail((h) => h.plant_health),
      colour: healthColour(k.plant_health),
      hint: 'Criticality-weighted across all assets',
    },
    {
      label: 'Power',
      value: num(k.power_kw, 0),
      unit: 'kW',
      series: trail((h) => h.power_kw),
      colour: '#a78bfa',
      hint: `${eur(k.energy_cost_eur_h)}/h at the current tariff`,
    },
    {
      label: 'Energy intensity',
      value: num(k.energy_intensity_kwh_t, 2),
      unit: 'kWh/t',
      series: trail((h) => h.energy_intensity_kwh_t),
      colour: '#f59e0b',
      hint: 'Rises before power does when throughput slips',
    },
    {
      label: 'Carbon',
      value: num(k.co2_kg_h, 0),
      unit: 'kg/h',
      series: trail((h) => h.co2_kg_h),
      colour: '#94a3b8',
      hint: 'Scope 2, at the configured grid intensity',
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      {tiles.map((tile) => (
        <div key={tile.label} className="panel group px-3.5 py-3" title={tile.hint}>
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
            {tile.label}
          </div>
          <div className="mt-1 flex items-end justify-between gap-2">
            <div className="num text-2xl font-semibold leading-none" style={{ color: tile.colour }}>
              {tile.value}
              {tile.unit && (
                <span className="ml-1 text-[11px] font-normal text-slate-500">{tile.unit}</span>
              )}
            </div>
            <Sparkline values={tile.series} colour={tile.colour} width={72} height={24} />
          </div>
          <div className="mt-1.5 truncate text-[10px] text-slate-600 transition group-hover:text-slate-500">
            {tile.hint}
          </div>
        </div>
      ))}
    </div>
  )
}

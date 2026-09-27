/**
 * What-if projection.
 *
 * Everything else on this console describes the present. This is the only
 * view that answers the question that releases budget: what does doing this
 * cost me, against doing nothing, over the next N days.
 */

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useState } from 'react'

import { Empty, Panel } from './Primitives'
import { api } from '../lib/api'
import { eur, num, pct } from '../lib/format'
import { useTwin } from '../state/useTwin'
import type { ScenarioChange, ScenarioResult } from '../lib/types'

type Lever =
  | { kind: 'maintain'; assetId: string }
  | { kind: 'parameter'; assetId: string; parameter: string; value: number }

/** Design parameters worth exposing as levers, per asset kind. */
const PARAMETERS: Record<string, { key: string; label: string; unit: string; step: number }[]> = {
  reactor: [{ key: 'setpoint_c', label: 'Reactor setpoint', unit: 'degC', step: 0.5 }],
  chiller: [{ key: 'supply_setpoint_c', label: 'Chilled water setpoint', unit: 'degC', step: 0.5 }],
  compressor: [
    { key: 'discharge_pressure_bar', label: 'Header pressure', unit: 'bar', step: 0.1 },
  ],
  heat_exchanger: [{ key: 'hot_inlet_c', label: 'Hot utility inlet', unit: 'degC', step: 1 }],
}

function Delta({ label, value, format }: { label: string; value: number; format: (v: number) => string }) {
  const good = value > 0
  return (
    <div className="rounded-lg border border-line bg-ink-700/50 px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className={`num mt-0.5 text-lg font-semibold ${good ? 'text-ok' : 'text-crit'}`}>
        {value > 0 ? '+' : ''}
        {format(value)}
      </div>
    </div>
  )
}

export default function ScenarioBuilder() {
  const { plant } = useTwin()
  const [name, setName] = useState('Overhaul before the trend bites')
  const [horizon, setHorizon] = useState(45)
  const [levers, setLevers] = useState<Lever[]>([])
  const [result, setResult] = useState<ScenarioResult | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [assetId, setAssetId] = useState('')
  const [parameter, setParameter] = useState('maintain')

  const assets = plant?.assets ?? []
  const selected = assets.find((a) => a.id === assetId)
  const available = selected ? (PARAMETERS[selected.kind] ?? []) : []
  const chosenParam = available.find((p) => p.key === parameter)

  const addLever = () => {
    if (!selected) return
    if (parameter === 'maintain') {
      setLevers((prev) => [
        ...prev.filter((l) => !(l.kind === 'maintain' && l.assetId === assetId)),
        { kind: 'maintain', assetId },
      ])
    } else if (chosenParam) {
      const current = Number(selected.design[chosenParam.key] ?? 0)
      setLevers((prev) => [
        ...prev.filter(
          (l) => !(l.kind === 'parameter' && l.assetId === assetId && l.parameter === parameter),
        ),
        { kind: 'parameter', assetId, parameter, value: current },
      ])
    }
  }

  const run = async () => {
    setRunning(true)
    setError(null)
    try {
      const changes: ScenarioChange[] = levers.map((lever) =>
        lever.kind === 'maintain'
          ? { asset_id: lever.assetId, parameter: 'maintain' }
          : { asset_id: lever.assetId, parameter: lever.parameter, value: lever.value },
      )
      setResult(await api.simulate(name || 'Untitled scenario', horizon, changes))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }

  const chartRows =
    result?.baseline.series.map((point, index) => ({
      day: point.day,
      baseline: point.plant_health,
      proposed: result.proposed.series[index]?.plant_health ?? null,
      baselineOee: point.oee * 100,
      proposedOee: (result.proposed.series[index]?.oee ?? 0) * 100,
    })) ?? []

  return (
    <div className="grid min-h-0 gap-3 xl:grid-cols-[340px_minmax(0,1fr)]">
      {/* ------------------------------------------------------- the builder */}
      <Panel title="Build a scenario">
        <div className="flex flex-col gap-3">
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-[0.12em] text-slate-500">
              Name
            </label>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="field"
              placeholder="What are you proposing?"
            />
          </div>

          <div>
            <label className="mb-1 flex justify-between text-[10px] uppercase tracking-[0.12em] text-slate-500">
              <span>Horizon</span>
              <span className="num text-slate-400">{horizon} days</span>
            </label>
            <input
              type="range"
              min={7}
              max={180}
              step={1}
              value={horizon}
              onChange={(event) => setHorizon(Number(event.target.value))}
              className="w-full accent-cyan-400"
            />
          </div>

          <div className="rounded-lg border border-line bg-ink-900/40 p-2.5">
            <div className="mb-2 text-[10px] uppercase tracking-[0.12em] text-slate-500">
              Add a change
            </div>
            <div className="flex flex-col gap-2">
              <select
                value={assetId}
                onChange={(event) => {
                  setAssetId(event.target.value)
                  setParameter('maintain')
                }}
                className="field"
              >
                <option value="">Select an asset...</option>
                {assets.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.id} - {asset.name}
                  </option>
                ))}
              </select>

              {selected && (
                <select
                  value={parameter}
                  onChange={(event) => setParameter(event.target.value)}
                  className="field"
                >
                  <option value="maintain">Restore to as-new (maintenance)</option>
                  {available.map((p) => (
                    <option key={p.key} value={p.key}>
                      Change {p.label}
                    </option>
                  ))}
                </select>
              )}

              <button onClick={addLever} disabled={!selected} className="btn w-full">
                Add change
              </button>
            </div>
          </div>

          {levers.length > 0 && (
            <ul className="flex flex-col gap-1.5">
              {levers.map((lever, index) => {
                const asset = assets.find((a) => a.id === lever.assetId)
                const meta =
                  lever.kind === 'parameter'
                    ? (PARAMETERS[asset?.kind ?? '']?.find((p) => p.key === lever.parameter) ?? null)
                    : null
                return (
                  <li
                    key={`${lever.assetId}-${lever.kind}-${index}`}
                    className="rounded-lg border border-line bg-ink-700/50 px-2.5 py-2"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="num text-[11px] font-semibold text-slate-300">
                          {lever.assetId}
                        </div>
                        <div className="text-[10px] text-slate-500">
                          {lever.kind === 'maintain' ? 'Restore to as-new' : meta?.label}
                        </div>
                      </div>
                      <button
                        onClick={() => setLevers((prev) => prev.filter((_, i) => i !== index))}
                        className="text-slate-600 transition hover:text-crit"
                      >
                        &times;
                      </button>
                    </div>
                    {lever.kind === 'parameter' && meta && (
                      <div className="mt-1.5 flex items-center gap-2">
                        <input
                          type="number"
                          step={meta.step}
                          value={lever.value}
                          onChange={(event) =>
                            setLevers((prev) =>
                              prev.map((l, i) =>
                                i === index && l.kind === 'parameter'
                                  ? { ...l, value: Number(event.target.value) }
                                  : l,
                              ),
                            )
                          }
                          className="field num py-1"
                        />
                        <span className="text-[10px] text-slate-600">{meta.unit}</span>
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}

          <button onClick={run} disabled={running} className="btn-primary w-full">
            {running ? 'Projecting...' : `Project ${horizon} days`}
          </button>
          <p className="text-[10px] leading-snug text-slate-600">
            The projection forks the live twin and sweeps it forward under a run-to-failure
            policy, then compares that against the same plant with your changes applied.
          </p>
          {error && <div className="text-[11px] text-crit">{error}</div>}
        </div>
      </Panel>

      {/* -------------------------------------------------------- the result */}
      <div className="flex min-h-0 flex-col gap-3">
        {!result ? (
          <Panel title="Result">
            <Empty>
              Build a scenario and project it.
              <br />
              <span className="text-slate-700">
                Try restoring an asset that already has an open alert.
              </span>
            </Empty>
          </Panel>
        ) : (
          <>
            <div className="panel px-4 py-3.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold text-slate-100">{result.name}</h3>
                <span className="num text-[10px] text-slate-600">
                  {result.horizon_days} days projected in {num(result.compute_ms, 0)} ms
                </span>
              </div>
              <p
                className={`mt-2 text-xs leading-relaxed ${
                  result.delta_cost_eur > 0 ? 'text-ok' : 'text-crit'
                }`}
              >
                {result.verdict}
              </p>
              <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
                <Delta label="Net cost" value={result.delta_cost_eur} format={(v) => eur(v)} />
                <Delta
                  label="Production"
                  value={result.delta_production_t}
                  format={(v) => `${num(v, 0)} t`}
                />
                <Delta
                  label="OEE"
                  value={result.delta_oee * 100}
                  format={(v) => `${num(v, 1)} pts`}
                />
                <Delta
                  label="Carbon"
                  value={result.delta_co2_t}
                  format={(v) => `${num(v, 1)} t`}
                />
              </div>
            </div>

            <Panel title="Projected plant health">
              <ResponsiveContainer width="100%" height={210}>
                <LineChart data={chartRows} margin={{ top: 6, right: 8, bottom: 0, left: -14 }}>
                  <CartesianGrid stroke="#1a2231" strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tick={{ fill: '#475569', fontSize: 10 }}
                    stroke="#1e2838"
                    tickLine={false}
                    unit=" d"
                  />
                  <YAxis
                    tick={{ fill: '#475569', fontSize: 10 }}
                    stroke="#1e2838"
                    tickLine={false}
                    width={44}
                    domain={[0, 100]}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#0c1017',
                      border: '1px solid #1e2838',
                      borderRadius: 10,
                      fontSize: 11,
                    }}
                    labelFormatter={(v) => `Day ${num(Number(v), 1)}`}
                    formatter={(value, nm) => [num(Number(value), 1), nm]}
                  />
                  <Legend
                    verticalAlign="top"
                    height={24}
                    iconType="plainline"
                    wrapperStyle={{ fontSize: 11, color: '#64748b' }}
                  />
                  <Line
                    dataKey="baseline"
                    name="Do nothing"
                    stroke="#64748b"
                    strokeWidth={1.6}
                    strokeDasharray="5 4"
                    dot={false}
                    isAnimationActive={false}
                  />
                  <Line
                    dataKey="proposed"
                    name={result.proposed.label}
                    stroke="#22d3ee"
                    strokeWidth={1.9}
                    dot={false}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Side by side">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-slate-600">
                    <th className="pb-2 text-left font-semibold">Outcome</th>
                    <th className="pb-2 text-right font-semibold">Do nothing</th>
                    <th className="pb-2 text-right font-semibold">Proposed</th>
                  </tr>
                </thead>
                <tbody className="num text-slate-300">
                  {(
                    [
                      ['Total cost', (o) => eur(o.total_cost_eur)],
                      ['Saleable production', (o) => `${num(o.total_production_t, 0)} t`],
                      ['Energy', (o) => `${num(o.total_energy_mwh, 1)} MWh`],
                      ['Carbon', (o) => `${num(o.total_co2_t, 1)} t`],
                      ['Mean OEE', (o) => pct(o.mean_oee)],
                      ['Unplanned outages', (o) => String(o.unplanned_events)],
                      ['Plant health at end', (o) => num(o.end_health, 1)],
                    ] as [string, (o: ScenarioResult['baseline']) => string][]
                  ).map(([label, render]) => (
                    <tr key={label} className="border-t border-line/60">
                      <td className="py-1.5 font-sans text-slate-500">{label}</td>
                      <td className="py-1.5 text-right text-slate-500">
                        {render(result.baseline)}
                      </td>
                      <td className="py-1.5 text-right text-accent">{render(result.proposed)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </>
        )}
      </div>
    </div>
  )
}

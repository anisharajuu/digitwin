/**
 * Everything about one asset, in the order an engineer asks for it:
 * what is it doing, what disagrees with the model, how worn is it, how long
 * have I got, and what can I do about it.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'

import { Empty, HealthBar, Panel, StateChip } from './Primitives'
import TrendChart from './TrendChart'
import { api } from '../lib/api'
import { duration, eur, healthColour, num, pct, titleCase } from '../lib/format'
import { useTwin } from '../state/useTwin'
import type { AssetDetail, TagSpec } from '../lib/types'

const TAG_CLASS_STYLE: Record<string, string> = {
  process: 'text-slate-300',
  condition: 'text-amber-300/90',
  electrical: 'text-violet-300/90',
  derived: 'text-cyan-300/90',
}

/** Residual severity, mirroring the detector's own thresholds. */
function residualTone(z: number): string {
  const magnitude = Math.abs(z)
  if (magnitude >= 7.5) return 'text-crit'
  if (magnitude >= 4) return 'text-warn'
  if (magnitude >= 2) return 'text-slate-400'
  return 'text-slate-600'
}

export default function AssetInspector({ assetId }: { assetId: string }) {
  const { frame, plant, refresh } = useTwin()
  const [detail, setDetail] = useState<AssetDetail | null>(null)
  const [tag, setTag] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [chartKey, setChartKey] = useState(0)

  const [faultId, setFaultId] = useState('')
  const [severity, setSeverity] = useState(0.7)

  const info = plant?.assets.find((a) => a.id === assetId) ?? null
  const snapshot = frame?.assets[assetId] ?? null

  const load = useCallback(async () => {
    try {
      const next = await api.asset(assetId)
      setDetail(next)
      setFaultId((current) =>
        next.injectable_faults.some((f) => f.id === current)
          ? current
          : (next.injectable_faults[0]?.id ?? ''),
      )
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    }
  }, [assetId])

  useEffect(() => {
    setDetail(null)
    setNote(null)
    void load()
  }, [load])

  // Default to the most interesting tag: whichever is furthest off model.
  useEffect(() => {
    if (tag !== null || !snapshot) return
    const worst = Object.values(snapshot.residuals).sort(
      (a, b) => Math.abs(b.z) - Math.abs(a.z),
    )[0]
    setTag(worst?.tag ?? Object.keys(snapshot.values)[0] ?? null)
  }, [snapshot, tag])

  useEffect(() => {
    setTag(null)
  }, [assetId])

  const specByTag = useMemo(() => {
    const map = new Map<string, TagSpec>()
    info?.tags.forEach((spec) => map.set(spec.name, spec))
    return map
  }, [info])

  if (!info) return <Empty>Unknown asset.</Empty>

  const act = async (label: string, run: () => Promise<unknown>) => {
    setBusy(true)
    setNote(null)
    try {
      await run()
      await Promise.all([load(), refresh()])
      setNote(label)
      setChartKey((k) => k + 1)
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const selectedFault = detail?.injectable_faults.find((f) => f.id === faultId) ?? null

  return (
    <div className="flex min-h-0 flex-col gap-3">
      {/* ---------------------------------------------------------- header */}
      <div className="panel px-4 py-3.5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2.5">
              <h2 className="text-base font-semibold text-slate-100">{info.name}</h2>
              {snapshot && <StateChip state={snapshot.state} />}
            </div>
            <div className="num mt-1 text-[11px] text-slate-500">
              {info.id} &middot; {titleCase(info.kind)}
              {info.manufacturer && ` · ${info.manufacturer} ${info.model ?? ''}`}
              {info.commissioned && ` · commissioned ${info.commissioned}`}
            </div>
          </div>
          <div className="min-w-[180px]">
            <div className="mb-1 flex justify-between text-[10px] uppercase tracking-[0.12em] text-slate-500">
              <span>Health</span>
              <span>{titleCase(info.criticality)} criticality</span>
            </div>
            <HealthBar health={snapshot?.health ?? 100} />
          </div>
        </div>

        {detail && detail.active_faults.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {detail.active_faults.map((fault) => (
              <span
                key={fault.id}
                className="chip border border-crit/40 bg-crit/10 text-crit"
                title={fault.symptom}
              >
                {fault.label} &middot; {pct(fault.severity, 0)} &middot; ramp {pct(fault.progress, 0)}
                <button
                  onClick={() => act('Fault cleared.', () => api.clearFault(fault.id))}
                  disabled={busy}
                  className="ml-1 text-crit/70 transition hover:text-crit"
                  title="Stop driving this fault (accumulated wear remains)"
                >
                  &times;
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="grid min-h-0 gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
        {/* ------------------------------------------------------ telemetry */}
        <div className="flex min-h-0 flex-col gap-3">
          <Panel title={tag ? `${specByTag.get(tag)?.label ?? tag} - sensor vs twin model` : 'Trend'}>
            {tag ? (
              <TrendChart
                assetId={assetId}
                tag={tag}
                spec={specByTag.get(tag)}
                refreshKey={chartKey}
                height={230}
              />
            ) : (
              <Empty>Select a tag.</Empty>
            )}
          </Panel>

          <Panel title="Live tags">
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
              {info.tags.map((spec) => {
                const value = snapshot?.values[spec.name]
                const residual = snapshot?.residuals[spec.name]
                const active = tag === spec.name
                return (
                  <button
                    key={spec.name}
                    onClick={() => setTag(spec.name)}
                    className={`rounded-lg border px-2.5 py-1.5 text-left transition ${
                      active
                        ? 'border-accent-dim bg-accent/10'
                        : 'border-line bg-ink-700/50 hover:border-slate-600'
                    }`}
                  >
                    <div className="flex items-baseline justify-between gap-1">
                      <span className="truncate text-[10px] text-slate-500">{spec.label}</span>
                      {residual && Math.abs(residual.z) >= 2 && (
                        <span className={`num text-[9px] font-bold ${residualTone(residual.z)}`}>
                          {residual.z > 0 ? '+' : ''}
                          {num(residual.z, 1)}&sigma;
                        </span>
                      )}
                    </div>
                    <div
                      className={`num mt-0.5 text-sm font-semibold ${
                        TAG_CLASS_STYLE[spec.tag_class] ?? 'text-slate-300'
                      }`}
                    >
                      {value === undefined ? '--' : num(value, spec.precision)}
                      <span className="ml-1 text-[10px] font-normal text-slate-600">
                        {spec.unit}
                      </span>
                    </div>
                  </button>
                )
              })}
            </div>
          </Panel>
        </div>

        {/* ------------------------------------------- wear, RUL and actions */}
        <div className="flex min-h-0 flex-col gap-3">
          <Panel title="Wear state and remaining life">
            <div className="flex flex-col gap-3">
              {(detail?.degradation_detail ?? []).map((mode) => {
                const estimate = snapshot?.rul.find((r) => r.mode === mode.name)
                const fraction = Math.min(1, mode.level / mode.threshold)
                return (
                  <div key={mode.name}>
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-xs font-medium text-slate-300">{mode.label}</span>
                      <span className="num text-[11px] text-slate-500">{pct(fraction, 0)}</span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-600">
                      <div
                        className="h-full rounded-full transition-[width] duration-500"
                        style={{
                          width: `${Math.max(2, fraction * 100)}%`,
                          backgroundColor: healthColour(100 - fraction * 100),
                        }}
                      />
                    </div>
                    <div className="mt-1 flex items-center justify-between text-[10px] text-slate-600">
                      <span>
                        {estimate?.hours_remaining != null ? (
                          <>
                            <span className="text-slate-400">
                              {duration(estimate.hours_remaining)}
                            </span>{' '}
                            to threshold &middot; {pct(estimate.confidence, 0)} confidence
                          </>
                        ) : (
                          'Not trending toward failure'
                        )}
                      </span>
                      <span className="num">{eur(mode.cost_eur, true)}</span>
                    </div>
                  </div>
                )
              })}
              {detail?.degradation_detail.length === 0 && (
                <Empty>This asset has no modelled wear mechanisms.</Empty>
              )}
            </div>

            <button
              onClick={() =>
                act('Maintenance complete - wear reset to as-new.', () =>
                  api.performMaintenance(assetId),
                )
              }
              disabled={busy || !detail?.degradation_detail.length}
              className="btn-primary mt-4 w-full"
            >
              Perform full maintenance
            </button>
          </Panel>

          {/* ------------------------------------------------ fault injection */}
          <Panel title="Inject a fault">
            {detail && detail.injectable_faults.length > 0 ? (
              <div className="flex flex-col gap-2.5">
                <select
                  value={faultId}
                  onChange={(event) => setFaultId(event.target.value)}
                  className="field"
                >
                  {detail.injectable_faults.map((fault) => (
                    <option key={fault.id} value={fault.id}>
                      {fault.label}
                    </option>
                  ))}
                </select>

                {selectedFault && (
                  <p className="text-[11px] leading-snug text-slate-500">
                    {selectedFault.description}
                    <span className="mt-1 block text-slate-600">
                      Expect: {selectedFault.symptom}
                    </span>
                  </p>
                )}

                <label className="flex items-center gap-2 text-[11px] text-slate-500">
                  <span className="w-14 shrink-0">Severity</span>
                  <input
                    type="range"
                    min={0.1}
                    max={1}
                    step={0.05}
                    value={severity}
                    onChange={(event) => setSeverity(Number(event.target.value))}
                    className="flex-1 accent-cyan-400"
                  />
                  <span className="num w-9 text-right text-slate-400">{pct(severity, 0)}</span>
                </label>

                <button
                  onClick={() =>
                    act('Fault injected - watch the residuals open up.', () =>
                      api.injectFault(assetId, faultId, severity, 3),
                    )
                  }
                  disabled={busy || !faultId}
                  className="btn w-full border-crit/40 text-crit hover:border-crit hover:text-crit"
                >
                  Inject
                </button>
                <p className="text-[10px] leading-snug text-slate-600">
                  Faults raise a wear <em>rate</em>, never a sensor value. Every symptom that
                  follows is produced by the physics.
                </p>
              </div>
            ) : (
              <Empty>No injectable faults for this asset kind.</Empty>
            )}
          </Panel>

          {note && (
            <div className="panel animate-slideIn px-3 py-2 text-[11px] text-accent">{note}</div>
          )}
        </div>
      </div>
    </div>
  )
}

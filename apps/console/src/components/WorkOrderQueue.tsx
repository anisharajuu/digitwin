/**
 * The maintenance queue, ranked by risk rather than by date.
 *
 * Sorting purely by due date is how a critical reactor slips behind a filter
 * change. Risk here is criticality x urgency x confidence, so the ordering
 * survives contact with a real shutdown plan.
 */

import { useCallback, useEffect, useState } from 'react'

import { Empty } from './Primitives'
import { api } from '../lib/api'
import { SEVERITY_STYLE, duration, eur, num, titleCase } from '../lib/format'
import { useTwin } from '../state/useTwin'
import type { WorkOrder } from '../lib/types'

export default function WorkOrderQueue({ onSelect }: { onSelect?: (assetId: string) => void }) {
  const { frame, refresh } = useTwin()
  const [orders, setOrders] = useState<WorkOrder[] | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setOrders(await api.workOrders())
    } catch {
      setOrders([])
    }
  }, [])

  // Re-poll on the tick rather than on an independent timer, so the queue
  // never shows a state the rest of the screen has moved past.
  useEffect(() => {
    void load()
  }, [load, frame?.tick && Math.floor(frame.tick / 20)])

  if (orders === null) return <Empty>Loading work orders...</Empty>
  if (orders.length === 0) {
    return (
      <Empty>
        Nothing due inside the planning horizon.
        <br />
        <span className="text-slate-700">Every asset is trending beyond 180 days.</span>
      </Empty>
    )
  }

  const perform = async (order: WorkOrder) => {
    const key = `${order.asset_id}:${order.mode}`
    setBusy(key)
    try {
      await api.performMaintenance(order.asset_id, order.mode)
      await Promise.all([load(), refresh()])
    } finally {
      setBusy(null)
    }
  }

  const totalExposure = orders.reduce((sum, o) => sum + o.estimated_cost_eur, 0)

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-2 flex items-center justify-between px-0.5 text-[11px] text-slate-500">
        <span>
          <span className="num text-slate-300">{orders.length}</span> pending
        </span>
        <span>
          Planned cost exposure <span className="num text-slate-300">{eur(totalExposure)}</span>
        </span>
      </div>

      <ul className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
        {orders.map((order) => {
          const key = `${order.asset_id}:${order.mode}`
          const style = SEVERITY_STYLE[order.severity]
          const open = expanded === key
          return (
            <li key={key} className={`rounded-lg border ${style.border} bg-ink-700/45 p-3`}>
              <div className="flex items-start gap-3">
                {/* Risk score reads as the primary sort key, so it leads. */}
                <div className="flex w-12 shrink-0 flex-col items-center">
                  <div className={`num text-lg font-bold leading-none ${style.text}`}>
                    {num(order.risk_score, 0)}
                  </div>
                  <div className="mt-0.5 text-[9px] uppercase tracking-wide text-slate-600">
                    risk
                  </div>
                </div>

                <div className="min-w-0 flex-1">
                  <button
                    onClick={() => onSelect?.(order.asset_id)}
                    className="text-left text-xs font-semibold text-slate-200 transition hover:text-accent"
                  >
                    {order.asset_name}
                    <span className="num ml-1.5 font-normal text-slate-600">{order.asset_id}</span>
                  </button>
                  <div className="mt-0.5 text-[11px] text-slate-400">{order.action}</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-600">
                    <span>
                      Due <span className={`num ${style.text}`}>{duration(order.due_in_hours)}</span>
                    </span>
                    <span className="num">{eur(order.estimated_cost_eur)}</span>
                    <span className="num">{num(order.estimated_downtime_h, 0)} h down</span>
                    <span>{titleCase(order.criticality)} criticality</span>
                    <button
                      onClick={() => setExpanded(open ? null : key)}
                      className="font-semibold uppercase tracking-wide text-slate-500 transition hover:text-accent"
                    >
                      {open ? 'Less' : 'Why?'}
                    </button>
                  </div>
                  {open && (
                    <p className="animate-slideIn mt-2 rounded-md bg-ink-900/60 p-2 text-[11px] leading-snug text-slate-400">
                      {order.rationale}
                    </p>
                  )}
                </div>

                <button
                  onClick={() => perform(order)}
                  disabled={busy === key}
                  className="btn shrink-0 self-center"
                >
                  {busy === key ? '...' : 'Execute'}
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

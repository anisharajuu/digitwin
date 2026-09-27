/** Live alert feed. Every entry names the model disagreement that raised it. */

import { useState } from 'react'

import { Empty } from './Primitives'
import { api } from '../lib/api'
import { SEVERITY_STYLE, num, simClock } from '../lib/format'
import { useTwin } from '../state/useTwin'
import type { Alert } from '../lib/types'

export default function AlertFeed({
  onSelect,
  limit = 40,
}: {
  onSelect?: (assetId: string) => void
  limit?: number
}) {
  const { frame, plant } = useTwin()
  const [acked, setAcked] = useState<Set<string>>(new Set())

  const alerts = (frame?.alerts ?? []).slice(0, limit)
  const nameOf = (id: string) => plant?.assets.find((a) => a.id === id)?.name ?? id

  if (alerts.length === 0) {
    return (
      <Empty>
        No open alerts. Every monitored tag is tracking its model.
        <br />
        <span className="text-slate-700">Inject a fault to watch the detector work.</span>
      </Empty>
    )
  }

  const acknowledge = async (alert: Alert) => {
    setAcked((prev) => new Set(prev).add(alert.id))
    try {
      await api.acknowledge(alert.id)
    } catch {
      // Acknowledgement is cosmetic; if it fails the alert simply stays lit.
      setAcked((prev) => {
        const next = new Set(prev)
        next.delete(alert.id)
        return next
      })
    }
  }

  return (
    <ul className="flex h-full flex-col gap-2 overflow-y-auto pr-1">
      {alerts.map((alert) => {
        const style = SEVERITY_STYLE[alert.severity]
        const isAcked = alert.acknowledged || acked.has(alert.id)
        return (
          <li
            key={alert.id}
            className={`animate-slideIn rounded-lg border ${style.border} ${style.bg} p-2.5 ${
              isAcked ? 'opacity-55' : ''
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <button
                onClick={() => onSelect?.(alert.asset_id)}
                className="min-w-0 flex-1 text-left"
                title="Open this asset"
              >
                <div className={`text-xs font-semibold ${style.text}`}>
                  {nameOf(alert.asset_id)}
                </div>
                <div className="mt-0.5 text-[11px] leading-snug text-slate-400">{alert.detail}</div>
              </button>
              <div className="flex shrink-0 flex-col items-end gap-1">
                <span className={`chip ${style.bg} ${style.text}`}>{alert.severity}</span>
                {alert.z !== null && (
                  <span className="num text-[10px] text-slate-500">
                    {num(Math.abs(alert.z), 1)}&sigma;
                  </span>
                )}
              </div>
            </div>
            <div className="mt-1.5 flex items-center justify-between text-[10px] text-slate-600">
              <span className="num">raised at T+{simClock(alert.raised_at)}</span>
              {!isAcked ? (
                <button
                  onClick={() => acknowledge(alert)}
                  className="font-semibold uppercase tracking-wide text-slate-500 transition hover:text-accent"
                >
                  Acknowledge
                </button>
              ) : (
                <span className="uppercase tracking-wide text-slate-600">Acknowledged</span>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

/** Reliability desk: what needs doing, when, and what it is worth. */

import AlertFeed from '../components/AlertFeed'
import { Empty, Panel } from '../components/Primitives'
import WorkOrderQueue from '../components/WorkOrderQueue'
import { duration, healthColour, num, pct, titleCase } from '../lib/format'
import { useTwin } from '../state/useTwin'

export default function Reliability({ onSelect }: { onSelect: (assetId: string) => void }) {
  const { plant, frame } = useTwin()

  // Flatten every tracked wear mode into one table, soonest first. This is
  // the view that answers "what is actually ageing on this line?".
  const rows = (plant?.assets ?? [])
    .flatMap((asset) => {
      const snapshot = frame?.assets[asset.id]
      if (!snapshot) return []
      return snapshot.rul.map((estimate) => ({
        asset,
        snapshot,
        estimate,
      }))
    })
    .sort((a, b) => {
      const left = a.estimate.hours_remaining ?? Number.POSITIVE_INFINITY
      const right = b.estimate.hours_remaining ?? Number.POSITIVE_INFINITY
      return left - right
    })

  return (
    <div className="grid min-h-0 gap-3 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-h-0 flex-col gap-3">
        <Panel
          title="Work-order queue - ranked by risk"
          className="min-h-[280px] overflow-hidden xl:max-h-[52vh]"
        >
          <WorkOrderQueue onSelect={onSelect} />
        </Panel>

        <Panel title="Degradation register">
          {rows.length === 0 ? (
            <Empty>Waiting for the twin to establish wear trends...</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wide text-slate-600">
                    <th className="pb-2 text-left font-semibold">Asset</th>
                    <th className="pb-2 text-left font-semibold">Mechanism</th>
                    <th className="pb-2 text-right font-semibold">Wear</th>
                    <th className="pb-2 text-right font-semibold">Trend/day</th>
                    <th className="pb-2 text-right font-semibold">To threshold</th>
                    <th className="pb-2 text-right font-semibold">Conf.</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ asset, estimate }) => {
                    const fraction = Math.min(1, estimate.level / estimate.threshold)
                    return (
                      <tr
                        key={`${asset.id}:${estimate.mode}`}
                        onClick={() => onSelect(asset.id)}
                        className="cursor-pointer border-t border-line/60 transition hover:bg-ink-700/50"
                      >
                        <td className="py-1.5">
                          <span className="num font-semibold text-slate-300">{asset.id}</span>
                        </td>
                        <td className="py-1.5 text-slate-500">{titleCase(estimate.mode)}</td>
                        <td className="py-1.5 text-right">
                          <span className="inline-flex items-center justify-end gap-2">
                            <span className="h-1 w-12 overflow-hidden rounded-full bg-ink-600">
                              <span
                                className="block h-full rounded-full"
                                style={{
                                  width: `${Math.max(3, fraction * 100)}%`,
                                  backgroundColor: healthColour(100 - fraction * 100),
                                }}
                              />
                            </span>
                            <span className="num w-9 text-right text-slate-400">
                              {pct(fraction, 0)}
                            </span>
                          </span>
                        </td>
                        <td className="num py-1.5 text-right text-slate-500">
                          {estimate.trend_per_day > 0
                            ? `+${num(estimate.trend_per_day * 100, 2)}%`
                            : '--'}
                        </td>
                        <td
                          className={`num py-1.5 text-right ${
                            estimate.hours_remaining !== null && estimate.hours_remaining < 336
                              ? 'font-semibold text-warn'
                              : 'text-slate-400'
                          }`}
                        >
                          {duration(estimate.hours_remaining)}
                        </td>
                        <td className="num py-1.5 text-right text-slate-600">
                          {pct(estimate.confidence, 0)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>

      <Panel title="Alert history" className="min-h-[320px] overflow-hidden xl:max-h-[calc(100vh-9rem)]">
        <AlertFeed onSelect={onSelect} limit={60} />
      </Panel>
    </div>
  )
}

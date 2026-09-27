/** Control-room home: the numbers, the plant, and what is shouting. */

import { Suspense, lazy } from 'react'

import AlertFeed from '../components/AlertFeed'
import KpiRow from '../components/KpiRow'
import { HealthBar, Panel, StatusDot } from '../components/Primitives'
import { num, titleCase } from '../lib/format'
import { useTwin } from '../state/useTwin'

// three.js is by far the heaviest thing the console loads. Deferring it lets
// the KPI row and the alert feed paint on first byte, which is what an
// operator glancing at a wall screen actually needs first.
const PlantScene = lazy(() => import('../components/PlantScene'))

function SceneFallback() {
  return (
    <div className="flex h-[400px] items-center justify-center gap-3 text-xs text-slate-600 md:h-[460px]">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-600 border-t-accent" />
      Loading plant geometry...
    </div>
  )
}

export default function Overview({
  selected,
  onSelect,
  onOpenAsset,
}: {
  selected: string | null
  onSelect: (id: string | null) => void
  onOpenAsset: (id: string) => void
}) {
  const { plant, frame } = useTwin()

  const areaName = (id: string) => plant?.areas.find((a) => a.id === id)?.name ?? id
  const chosen = selected ? plant?.assets.find((a) => a.id === selected) : null
  const chosenSnapshot = selected ? frame?.assets[selected] : null

  return (
    <div className="flex flex-col gap-3">
      <KpiRow />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel
          title={plant ? `${plant.plant.name} - ${plant.plant.line}` : 'Plant'}
          bodyClassName="px-0 pb-0"
          action={
            plant && (
              <span className="num pr-1 text-[10px] text-slate-600">
                {plant.plant.location} &middot; {plant.plant.product}
              </span>
            )
          }
        >
          <Suspense fallback={<SceneFallback />}>
            <PlantScene
              selected={selected}
              onSelect={onSelect}
              className="h-[400px] overflow-hidden rounded-b-xl md:h-[460px]"
            />
          </Suspense>
        </Panel>

        {/* Height-matched to the scene so the feed scrolls inside the
            panel instead of stretching the page to the length of the
            alert list. */}
        <div className="flex min-h-0 flex-col gap-3 xl:h-[460px]">
          {chosen && chosenSnapshot && (
            <Panel title="Selected">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-100">{chosen.name}</div>
                  <div className="num text-[10px] text-slate-500">
                    {chosen.id} &middot; {areaName(chosen.area)}
                  </div>
                </div>
                <button onClick={() => onOpenAsset(chosen.id)} className="btn shrink-0">
                  Inspect
                </button>
              </div>
              <HealthBar health={chosenSnapshot.health} className="mt-2.5" />
              <div className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[11px]">
                {Object.entries(chosenSnapshot.values)
                  .slice(0, 6)
                  .map(([tag, value]) => {
                    const spec = chosen.tags.find((t) => t.name === tag)
                    return (
                      <div key={tag} className="flex justify-between gap-2">
                        <span className="truncate text-slate-600">{spec?.label ?? tag}</span>
                        <span className="num shrink-0 text-slate-300">
                          {num(value, spec?.precision ?? 1)}
                        </span>
                      </div>
                    )
                  })}
              </div>
            </Panel>
          )}

          <Panel
            title="Alerts"
            className="min-h-[260px] flex-1 overflow-hidden"
            action={
              <span className="num pr-1 text-[10px] text-slate-600">
                {frame?.alerts.length ?? 0} open
              </span>
            }
          >
            <AlertFeed onSelect={onOpenAsset} />
          </Panel>
        </div>
      </div>

      {/* Full-line health strip: ten assets, one glance. */}
      <Panel title="Asset health">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {plant?.assets.map((asset) => {
            const snapshot = frame?.assets[asset.id]
            if (!snapshot) return null
            const isSelected = selected === asset.id
            return (
              <button
                key={asset.id}
                onClick={() => onSelect(asset.id)}
                onDoubleClick={() => onOpenAsset(asset.id)}
                className={`rounded-lg border px-2.5 py-2 text-left transition ${
                  isSelected
                    ? 'border-accent-dim bg-accent/10'
                    : 'border-line bg-ink-700/45 hover:border-slate-600'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="num truncate text-[11px] font-semibold text-slate-300">
                    {asset.id}
                  </span>
                  <StatusDot state={snapshot.state} pulse />
                </div>
                <div className="mt-0.5 truncate text-[10px] text-slate-600">
                  {titleCase(asset.kind)}
                </div>
                <HealthBar health={snapshot.health} className="mt-1.5" />
                {snapshot.open_alerts > 0 && (
                  <div className="mt-1 text-[10px] font-semibold text-crit">
                    {snapshot.open_alerts} alert{snapshot.open_alerts > 1 ? 's' : ''}
                  </div>
                )}
              </button>
            )
          })}
        </div>
      </Panel>
    </div>
  )
}

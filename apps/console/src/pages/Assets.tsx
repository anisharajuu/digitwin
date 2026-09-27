/** Asset browser: pick from the line, inspect it in full. */

import { useState } from 'react'

import AssetInspector from '../components/AssetInspector'
import { Empty, HealthBar, StatusDot } from '../components/Primitives'
import { titleCase } from '../lib/format'
import { useTwin } from '../state/useTwin'

export default function Assets({
  selected,
  onSelect,
}: {
  selected: string | null
  onSelect: (id: string) => void
}) {
  const { plant, frame } = useTwin()
  const [query, setQuery] = useState('')

  if (!plant) return <Empty>Connecting to the twin...</Empty>

  const needle = query.trim().toLowerCase()
  const matches = plant.assets.filter(
    (asset) =>
      needle === '' ||
      asset.id.toLowerCase().includes(needle) ||
      asset.name.toLowerCase().includes(needle) ||
      asset.kind.toLowerCase().includes(needle),
  )

  const byArea = plant.areas
    .map((area) => ({ area, assets: matches.filter((a) => a.area === area.id) }))
    .filter((group) => group.assets.length > 0)

  return (
    <div className="grid min-h-0 gap-3 lg:grid-cols-[252px_minmax(0,1fr)]">
      <aside className="panel flex min-h-0 flex-col">
        <div className="p-3">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter assets..."
            className="field"
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {byArea.map(({ area, assets }) => (
            <div key={area.id} className="mb-3">
              <div className="flex items-center gap-1.5 px-1.5 pb-1.5">
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: area.colour }} />
                <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-600">
                  {area.name}
                </span>
              </div>
              <ul className="flex flex-col gap-1">
                {assets.map((asset) => {
                  const snapshot = frame?.assets[asset.id]
                  const active = selected === asset.id
                  return (
                    <li key={asset.id}>
                      <button
                        onClick={() => onSelect(asset.id)}
                        className={`w-full rounded-lg px-2.5 py-2 text-left transition ${
                          active ? 'bg-accent/10 ring-1 ring-accent-dim' : 'hover:bg-ink-700'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={`num truncate text-[11px] font-semibold ${
                              active ? 'text-accent' : 'text-slate-300'
                            }`}
                          >
                            {asset.id}
                          </span>
                          {snapshot && <StatusDot state={snapshot.state} pulse />}
                        </div>
                        <div className="mt-0.5 truncate text-[10px] text-slate-600">
                          {titleCase(asset.kind)}
                        </div>
                        {snapshot && <HealthBar health={snapshot.health} className="mt-1.5" />}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
          {byArea.length === 0 && <Empty>Nothing matches "{query}".</Empty>}
        </div>
      </aside>

      <div className="min-h-0">
        {selected ? (
          <AssetInspector key={selected} assetId={selected} />
        ) : (
          <div className="panel h-full">
            <Empty>Select an asset to inspect it.</Empty>
          </div>
        )}
      </div>
    </div>
  )
}

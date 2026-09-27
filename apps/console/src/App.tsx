/** Application shell: navigation, connection health, and the simulated clock. */

import { Suspense, lazy, useState } from 'react'

import { num, simClock } from './lib/format'
import { useTwin, type ConnectionState } from './state/useTwin'

// Each view is split out so a cold load only fetches the chunk it paints.
// Overview is the landing view and pulls in no chart runtime at all.
const Overview = lazy(() => import('./pages/Overview'))
const Assets = lazy(() => import('./pages/Assets'))
const Reliability = lazy(() => import('./pages/Reliability'))
const Scenarios = lazy(() => import('./pages/Scenarios'))

function Loading({ label }: { label: string }) {
  return (
    <div className="flex h-[60vh] flex-col items-center justify-center gap-3 text-slate-600">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-ink-600 border-t-accent" />
      <p className="text-xs">{label}</p>
    </div>
  )
}

type View = 'overview' | 'assets' | 'reliability' | 'scenarios'

const VIEWS: { id: View; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'assets', label: 'Assets' },
  { id: 'reliability', label: 'Reliability' },
  { id: 'scenarios', label: 'What-if' },
]

const CONNECTION_STYLE: Record<ConnectionState, { dot: string; label: string; text: string }> = {
  connecting: { dot: 'bg-warn', label: 'Connecting', text: 'text-warn' },
  live: { dot: 'bg-ok', label: 'Live', text: 'text-ok' },
  reconnecting: { dot: 'bg-warn', label: 'Reconnecting', text: 'text-warn' },
  failed: { dot: 'bg-crit', label: 'Offline', text: 'text-crit' },
}

export default function App() {
  const { plant, frame, connection, error } = useTwin()
  const [view, setView] = useState<View>('overview')
  const [selected, setSelected] = useState<string | null>(null)

  const openAsset = (assetId: string) => {
    setSelected(assetId)
    setView('assets')
  }

  const status = CONNECTION_STYLE[connection]
  const criticalAlerts = frame?.alerts.filter((a) => a.severity === 'critical').length ?? 0

  return (
    <div className="flex min-h-screen flex-col bg-ink-900">
      <header className="sticky top-0 z-30 border-b border-line bg-ink-900/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1800px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <div className="flex items-center gap-2.5">
            <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden="true">
              <circle cx="16" cy="16" r="9" fill="none" stroke="#22d3ee" strokeWidth="2.5" />
              <circle cx="16" cy="16" r="2.8" fill="#22d3ee" />
            </svg>
            <div>
              <div className="text-sm font-bold leading-none tracking-tight text-slate-100">
                DigiTwin
              </div>
              <div className="mt-0.5 text-[10px] leading-none text-slate-600">
                {plant ? plant.plant.name : 'Industrial digital twin'}
              </div>
            </div>
          </div>

          <nav className="flex items-center gap-1">
            {VIEWS.map((item) => (
              <button
                key={item.id}
                onClick={() => setView(item.id)}
                className={`relative rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  view === item.id
                    ? 'bg-ink-700 text-accent'
                    : 'text-slate-500 hover:bg-ink-800 hover:text-slate-300'
                }`}
              >
                {item.label}
                {item.id === 'reliability' && criticalAlerts > 0 && (
                  <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-crit px-1 text-[9px] font-bold text-ink-900">
                    {criticalAlerts}
                  </span>
                )}
              </button>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-4 text-[11px]">
            {frame && (
              <>
                <span className="hidden text-slate-600 sm:inline">
                  Simulated&nbsp;
                  <span className="num text-slate-400">T+{simClock(frame.sim_time)}</span>
                </span>
                <span className="hidden text-slate-600 md:inline">
                  tick&nbsp;<span className="num text-slate-400">{num(frame.tick, 0)}</span>
                </span>
              </>
            )}
            <span className={`flex items-center gap-1.5 font-semibold ${status.text}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${status.dot}`} />
              {status.label}
            </span>
          </div>
        </div>
      </header>

      {error && connection === 'failed' && (
        <div className="border-b border-crit/40 bg-crit/10 px-4 py-2 text-center text-xs text-crit">
          {error}
        </div>
      )}

      <main className="mx-auto w-full max-w-[1800px] flex-1 px-4 py-4">
        {!plant ? (
          <Loading label="Loading the plant registry..." />
        ) : (
          <Suspense fallback={<Loading label="Loading view..." />}>
            {view === 'overview' ? (
              <Overview selected={selected} onSelect={setSelected} onOpenAsset={openAsset} />
            ) : view === 'assets' ? (
              <Assets selected={selected} onSelect={setSelected} />
            ) : view === 'reliability' ? (
              <Reliability onSelect={openAsset} />
            ) : (
              <Scenarios />
            )}
          </Suspense>
        )}
      </main>

      <footer className="border-t border-line px-4 py-2.5">
        <div className="mx-auto flex max-w-[1800px] flex-wrap items-center justify-between gap-2 text-[10px] text-slate-700">
          <span>
            Physics-backed digital twin &middot; every alert is a model residual, not a threshold
          </span>
          {plant && (
            <span className="num">
              {plant.assets.length} assets &middot; design rate{' '}
              {num(plant.plant.design_rate_tph, 1)} t/h &middot;{' '}
              {num(plant.plant.grid_intensity_kg_co2_kwh, 3)} kg CO2/kWh
            </span>
          )}
        </div>
      </footer>
    </div>
  )
}

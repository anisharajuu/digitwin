import { Suspense, lazy } from 'react'

// Recharts only matters once someone opens this view.
const ScenarioBuilder = lazy(() => import('../components/ScenarioBuilder'))

export default function Scenarios() {
  return (
    <Suspense
      fallback={
        <div className="flex h-[50vh] items-center justify-center gap-3 text-xs text-slate-600">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-600 border-t-accent" />
          Loading the projection workspace...
        </div>
      }
    >
      <ScenarioBuilder />
    </Suspense>
  )
}

/** Small shared building blocks used across every view. */

import type { ReactNode } from 'react'

import { STATE_STYLE, healthColour, num } from '../lib/format'
import type { AssetState } from '../lib/types'

export function Panel({
  title,
  action,
  children,
  className = '',
  bodyClassName = 'px-4 pb-4',
}: {
  title?: string
  action?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={`panel flex min-h-0 flex-col ${className}`}>
      {title && (
        <header className="flex items-center justify-between gap-3 pr-3">
          <h2 className="panel-title">{title}</h2>
          {action}
        </header>
      )}
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  )
}

export function StatusDot({ state, pulse = false }: { state: AssetState; pulse?: boolean }) {
  const style = STATE_STYLE[state]
  const shouldPulse = pulse && (state === 'fault' || state === 'degraded')
  return (
    <span className="relative inline-flex h-2 w-2 shrink-0">
      {shouldPulse && (
        <span
          className="absolute inline-flex h-full w-full rounded-full animate-pulseRing"
          style={{ backgroundColor: style.dot }}
        />
      )}
      <span
        className="relative inline-flex h-2 w-2 rounded-full"
        style={{ backgroundColor: style.dot }}
      />
    </span>
  )
}

export function StateChip({ state }: { state: AssetState }) {
  const style = STATE_STYLE[state]
  return (
    <span className={`chip ${style.bg} ${style.text}`}>
      <StatusDot state={state} pulse />
      {style.label}
    </span>
  )
}

/**
 * Health as a bar rather than a number alone: an operator scanning ten rows
 * reads relative length far faster than they read two digits.
 */
export function HealthBar({ health, className = '' }: { health: number; className?: string }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-600">
        <div
          className="h-full rounded-full transition-[width] duration-500 ease-out"
          style={{ width: `${Math.max(2, health)}%`, backgroundColor: healthColour(health) }}
        />
      </div>
      <span className="num w-10 shrink-0 text-right text-xs" style={{ color: healthColour(health) }}>
        {num(health, 0)}
      </span>
    </div>
  )
}

/**
 * Inline sparkline. Hand-rolled SVG rather than a chart library: these render
 * once per tick in the header, and a full chart runtime per tile is wasteful.
 */
export function Sparkline({
  values,
  colour = '#22d3ee',
  width = 96,
  height = 26,
}: {
  values: number[]
  colour?: string
  width?: number
  height?: number
}) {
  if (values.length < 2) return <div style={{ width, height }} />

  const min = Math.min(...values)
  const max = Math.max(...values)
  // A flat series would divide by zero; draw it down the middle instead.
  const span = max - min || 1
  const step = width / (values.length - 1)
  const y = (v: number) => height - 2 - ((v - min) / span) * (height - 4)

  const line = values.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(2)},${y(v).toFixed(2)}`).join(' ')
  const area = `${line} L${width},${height} L0,${height} Z`
  const gradientId = `spark-${colour.replace('#', '')}`

  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden="true">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={colour} stopOpacity="0.30" />
          <stop offset="100%" stopColor={colour} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gradientId})`} />
      <path d={line} fill="none" stroke={colour} strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={width} cy={y(values[values.length - 1])} r="2" fill={colour} />
    </svg>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full min-h-[120px] items-center justify-center px-6 text-center text-xs text-slate-600">
      {children}
    </div>
  )
}

export function Metric({
  label,
  value,
  unit,
  tone = 'text-slate-100',
}: {
  label: string
  value: string
  unit?: string
  tone?: string
}) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
        {label}
      </div>
      <div className={`num mt-0.5 text-lg font-semibold ${tone}`}>
        {value}
        {unit && <span className="ml-1 text-xs font-normal text-slate-500">{unit}</span>}
      </div>
    </div>
  )
}

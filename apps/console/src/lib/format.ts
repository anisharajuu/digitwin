/** Display helpers. Nothing here changes a value - only how it reads. */

import type { AssetState, Severity } from './types'

export function num(value: number | null | undefined, precision = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--'
  return value.toLocaleString('en-GB', {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  })
}

export function pct(fraction: number | null | undefined, precision = 1): string {
  if (fraction === null || fraction === undefined) return '--'
  return `${(fraction * 100).toFixed(precision)}%`
}

export function eur(value: number, compact = false): string {
  return value.toLocaleString('en-GB', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 0,
    notation: compact && Math.abs(value) >= 10_000 ? 'compact' : 'standard',
  })
}

/**
 * Durations read as an engineer would say them out loud: hours up to a day,
 * then days, then months. "4,380 h" tells nobody anything.
 */
export function duration(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return 'stable'
  if (hours < 1) return `${Math.round(hours * 60)} min`
  if (hours < 48) return `${hours.toFixed(1)} h`
  const days = hours / 24
  if (days < 60) return `${days.toFixed(days < 10 ? 1 : 0)} d`
  return `${(days / 30.44).toFixed(1)} mo`
}

/** Simulated clock as elapsed time since the twin booted. */
export function simClock(seconds: number): string {
  const total = Math.floor(seconds)
  const d = Math.floor(total / 86400)
  const h = Math.floor((total % 86400) / 3600)
  const m = Math.floor((total % 3600) / 60)
  return d > 0 ? `${d}d ${h}h ${String(m).padStart(2, '0')}m` : `${h}h ${String(m).padStart(2, '0')}m`
}

export const STATE_STYLE: Record<AssetState, { label: string; text: string; bg: string; dot: string }> =
  {
    running: { label: 'Running', text: 'text-ok', bg: 'bg-ok/10', dot: '#34d399' },
    standby: { label: 'Standby', text: 'text-idle', bg: 'bg-slate-500/10', dot: '#64748b' },
    degraded: { label: 'Degraded', text: 'text-warn', bg: 'bg-warn/10', dot: '#fbbf24' },
    fault: { label: 'Fault', text: 'text-crit', bg: 'bg-crit/10', dot: '#fb7185' },
    maintenance: { label: 'Maintenance', text: 'text-accent', bg: 'bg-accent/10', dot: '#22d3ee' },
  }

export const SEVERITY_STYLE: Record<Severity, { text: string; bg: string; border: string }> = {
  info: { text: 'text-slate-300', bg: 'bg-slate-500/10', border: 'border-slate-600' },
  warning: { text: 'text-warn', bg: 'bg-warn/10', border: 'border-warn/40' },
  critical: { text: 'text-crit', bg: 'bg-crit/10', border: 'border-crit/40' },
}

/** Health colour ramp, shared by the 3D scene, gauges and tables. */
export function healthColour(health: number): string {
  if (health >= 80) return '#34d399'
  if (health >= 60) return '#a3e635'
  if (health >= 40) return '#fbbf24'
  if (health >= 25) return '#fb923c'
  return '#fb7185'
}

export function titleCase(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/**
 * Sensor against model, on one pair of axes.
 *
 * This is the view the whole platform exists to produce. A single trend line
 * tells you a value; two lines that used to sit on top of each other and no
 * longer do tell you a machine has changed - usually weeks before either line
 * approaches an alarm limit.
 */

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useEffect, useState } from 'react'

import { Empty } from './Primitives'
import { api } from '../lib/api'
import { num } from '../lib/format'
import type { TagSpec } from '../lib/types'

interface Row {
  t: number
  observed: number
  expected: number
  gap: [number, number]
}

export default function TrendChart({
  assetId,
  tag,
  spec,
  points = 300,
  refreshKey = 0,
  height = 220,
}: {
  assetId: string
  tag: string
  spec?: TagSpec
  points?: number
  refreshKey?: number
  height?: number
}) {
  const [rows, setRows] = useState<Row[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .telemetry(assetId, [tag], points)
      .then(([series]) => {
        if (cancelled || !series) return
        const t0 = series.points[0]?.t ?? 0
        setRows(
          series.points.map((point, index) => {
            const expected = series.expected[index]?.v ?? point.v
            return {
              // Minutes of simulated time before "now" reads better on an
              // axis than a raw simulation clock in seconds.
              t: Math.round((point.t - t0) / 60),
              observed: point.v,
              expected,
              gap: [Math.min(point.v, expected), Math.max(point.v, expected)],
            }
          }),
        )
        setError(null)
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      cancelled = true
    }
  }, [assetId, tag, points, refreshKey])

  if (error) return <Empty>{error}</Empty>
  if (rows.length === 0) return <Empty>Loading {tag}...</Empty>

  const precision = spec?.precision ?? 2

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
        <defs>
          <linearGradient id="gapFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#fb7185" stopOpacity={0.32} />
            <stop offset="100%" stopColor="#fb7185" stopOpacity={0.12} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#1a2231" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="t"
          tick={{ fill: '#475569', fontSize: 10 }}
          stroke="#1e2838"
          tickLine={false}
          unit=" min"
        />
        <YAxis
          tick={{ fill: '#475569', fontSize: 10 }}
          stroke="#1e2838"
          tickLine={false}
          width={52}
          domain={['auto', 'auto']}
          tickFormatter={(v: number) => num(v, precision > 2 ? 2 : precision)}
        />
        <Tooltip
          contentStyle={{
            background: '#0c1017',
            border: '1px solid #1e2838',
            borderRadius: 10,
            fontSize: 11,
          }}
          labelStyle={{ color: '#64748b' }}
          labelFormatter={(v) => `T-${rows[rows.length - 1].t - Number(v)} min`}
          formatter={(value, name) => {
            if (name === 'Deviation') return [null, null]
            return [`${num(Number(value), precision)} ${spec?.unit ?? ''}`, name]
          }}
        />
        <Legend
          verticalAlign="top"
          height={26}
          iconType="plainline"
          wrapperStyle={{ fontSize: 11, color: '#64748b' }}
        />
        {/* The shaded band IS the residual - the thing the detector scores. */}
        <Area
          dataKey="gap"
          name="Deviation"
          stroke="none"
          fill="url(#gapFill)"
          isAnimationActive={false}
          legendType="none"
        />
        <Line
          dataKey="expected"
          name="Twin model (as-new)"
          stroke="#64748b"
          strokeWidth={1.5}
          strokeDasharray="5 4"
          dot={false}
          isAnimationActive={false}
        />
        <Line
          dataKey="observed"
          name="Sensor"
          stroke="#22d3ee"
          strokeWidth={1.8}
          dot={false}
          isAnimationActive={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

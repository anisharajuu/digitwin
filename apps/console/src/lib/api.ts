/** Thin fetch wrapper over twin-core. Same origin in dev via the Vite proxy. */

import type {
  Alert,
  AssetDetail,
  Frame,
  InjectableFault,
  Plant,
  ScenarioChange,
  ScenarioResult,
  TelemetrySeries,
  WorkOrder,
} from './types'

const BASE = '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    // Surface the server's own explanation - twin-core returns a useful
    // `detail` on every 4xx, and swallowing it makes debugging miserable.
    const detail = await response.text().catch(() => '')
    let message = `${response.status} ${response.statusText}`
    try {
      const parsed = JSON.parse(detail)
      if (parsed?.detail) message = typeof parsed.detail === 'string' ? parsed.detail : message
    } catch {
      /* not JSON - keep the status line */
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  plant: () => request<Plant>('/plant'),
  frame: () => request<Frame>('/frame'),
  asset: (id: string) => request<AssetDetail>(`/assets/${id}`),

  telemetry: (id: string, tags: string[], points = 360) =>
    request<TelemetrySeries[]>(
      `/assets/${id}/telemetry?tags=${encodeURIComponent(tags.join(','))}&points=${points}`,
    ),

  alerts: (includeCleared = true, limit = 100) =>
    request<Alert[]>(`/alerts?include_cleared=${includeCleared}&limit=${limit}`),

  acknowledge: (alertId: string) =>
    request<Alert>(`/alerts/${alertId}/acknowledge`, { method: 'POST' }),

  workOrders: () => request<WorkOrder[]>('/maintenance/work-orders'),

  performMaintenance: (assetId: string, mode?: string) =>
    request<Record<string, unknown>>('/maintenance/perform', {
      method: 'POST',
      body: JSON.stringify({ asset_id: assetId, mode: mode ?? null }),
    }),

  faultCatalogue: () => request<(InjectableFault & { kinds: string[] })[]>('/faults/catalogue'),

  injectFault: (assetId: string, mode: string, severity: number, rampHours: number) =>
    request<Record<string, unknown>>('/faults', {
      method: 'POST',
      body: JSON.stringify({
        asset_id: assetId,
        mode,
        severity,
        ramp_hours: rampHours,
      }),
    }),

  clearFault: (faultId: string) =>
    request<Record<string, unknown>>(`/faults/${faultId}`, { method: 'DELETE' }),

  simulate: (name: string, horizonDays: number, changes: ScenarioChange[]) =>
    request<ScenarioResult>('/scenarios/simulate', {
      method: 'POST',
      body: JSON.stringify({ name, horizon_days: horizonDays, changes }),
    }),
}

/** WebSocket URL for the live frame stream, derived from the page origin. */
export function streamUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${BASE}/stream`
}

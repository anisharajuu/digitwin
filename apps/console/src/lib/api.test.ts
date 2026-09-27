import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, streamUrl } from './api'

function mockFetch(response: Partial<Response> & { jsonBody?: unknown }) {
  const impl = vi.fn().mockResolvedValue({
    ok: response.ok ?? true,
    status: response.status ?? 200,
    statusText: response.statusText ?? 'OK',
    json: async () => response.jsonBody ?? {},
    text: async () => JSON.stringify(response.jsonBody ?? {}),
    ...response,
  })
  vi.stubGlobal('fetch', impl)
  return impl
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('error handling', () => {
  it("surfaces twin-core's own explanation instead of a bare status code", async () => {
    // Swallowing `detail` is what makes a 404 impossible to debug from the UI.
    mockFetch({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      text: async () => JSON.stringify({ detail: "P-101A has no degradation mode 'nope'" }),
    })
    await expect(api.asset('P-101A')).rejects.toThrow("P-101A has no degradation mode 'nope'")
  })

  it('falls back to the status line when the body is not JSON', async () => {
    mockFetch({ ok: false, status: 502, statusText: 'Bad Gateway', text: async () => '<html>' })
    await expect(api.plant()).rejects.toThrow('502 Bad Gateway')
  })

  it('does not throw on a successful response', async () => {
    mockFetch({ jsonBody: { tick: 7 } })
    await expect(api.frame()).resolves.toEqual({ tick: 7 })
  })
})

describe('request shaping', () => {
  it('encodes the tag list so multi-tag requests survive the query string', async () => {
    const fetchMock = mockFetch({ jsonBody: [] })
    await api.telemetry('P-101A', ['flow_m3h', 'vibration_mms'], 120)
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/v1/assets/P-101A/telemetry?tags=flow_m3h%2Cvibration_mms&points=120',
    )
  })

  it('sends maintenance with an explicit null mode when none is given', async () => {
    const fetchMock = mockFetch({ jsonBody: {} })
    await api.performMaintenance('CHL-202')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      asset_id: 'CHL-202',
      mode: null,
    })
  })
})

describe('streamUrl', () => {
  it('derives the scheme from the page, so a TLS deployment does not fall back to ws://', () => {
    vi.stubGlobal('window', { location: { protocol: 'https:', host: 'plant.example.com' } })
    expect(streamUrl()).toBe('wss://plant.example.com/api/v1/stream')

    vi.stubGlobal('window', { location: { protocol: 'http:', host: 'localhost:5173' } })
    expect(streamUrl()).toBe('ws://localhost:5173/api/v1/stream')
  })
})

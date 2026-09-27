import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TwinProvider, useTwin } from './useTwin'
import type { Frame } from '../lib/types'

vi.mock('../lib/api', () => ({
  api: {
    plant: vi.fn().mockResolvedValue({ plant: { name: 'Aurora Works' }, areas: [], assets: [] }),
    frame: vi.fn(),
  },
  streamUrl: () => 'ws://test/api/v1/stream',
}))

/** Stand-in for the browser WebSocket, so tests can drive the stream. */
class MockSocket {
  static instances: MockSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null

  constructor(public url: string) {
    MockSocket.instances.push(this)
  }

  close() {
    this.onclose?.()
  }

  push(frame: Partial<Frame>) {
    this.onmessage?.({ data: JSON.stringify(frame) })
  }
}

const frameAt = (tick: number): Partial<Frame> => ({
  tick,
  sim_time: tick * 60,
  wall_time: 0,
  assets: {},
  kpis: { oee: 0.82, power_kw: 420 } as Frame['kpis'],
  alerts: [],
})

function Probe() {
  const { frame, history, connection } = useTwin()
  return (
    <div>
      <span data-testid="tick">{frame?.tick ?? 'none'}</span>
      <span data-testid="history">{history.length}</span>
      <span data-testid="connection">{connection}</span>
    </div>
  )
}

const latest = () => MockSocket.instances[MockSocket.instances.length - 1]

beforeEach(() => {
  MockSocket.instances = []
  vi.stubGlobal('WebSocket', MockSocket)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('TwinProvider', () => {
  it('reports live once the socket opens and paints the frames it receives', async () => {
    render(
      <TwinProvider>
        <Probe />
      </TwinProvider>,
    )

    await waitFor(() => expect(latest()).toBeDefined())
    act(() => latest().onopen?.())
    expect(screen.getByTestId('connection')).toHaveTextContent('live')

    act(() => latest().push(frameAt(1)))
    act(() => latest().push(frameAt(2)))

    expect(screen.getByTestId('tick')).toHaveTextContent('2')
    expect(screen.getByTestId('history')).toHaveTextContent('2')
  })

  it('does not double-count the frame the server replays on reconnect', async () => {
    // twin-core sends current state immediately on connect. After a
    // reconnect that repeats a tick we already hold, and appending it would
    // put a duplicate point in every sparkline.
    render(
      <TwinProvider>
        <Probe />
      </TwinProvider>,
    )
    await waitFor(() => expect(latest()).toBeDefined())
    act(() => latest().onopen?.())

    act(() => latest().push(frameAt(1)))
    act(() => latest().push(frameAt(2)))
    act(() => latest().push(frameAt(2)))
    act(() => latest().push(frameAt(1)))

    expect(screen.getByTestId('history')).toHaveTextContent('2')
  })

  it('caps history so a screen left open overnight does not grow without bound', async () => {
    render(
      <TwinProvider>
        <Probe />
      </TwinProvider>,
    )
    await waitFor(() => expect(latest()).toBeDefined())
    act(() => latest().onopen?.())

    act(() => {
      for (let tick = 1; tick <= 300; tick += 1) latest().push(frameAt(tick))
    })

    expect(screen.getByTestId('history')).toHaveTextContent('240')
    expect(screen.getByTestId('tick')).toHaveTextContent('300')
  })

  it('survives a malformed frame rather than tearing down the stream', async () => {
    render(
      <TwinProvider>
        <Probe />
      </TwinProvider>,
    )
    await waitFor(() => expect(latest()).toBeDefined())
    act(() => latest().onopen?.())

    act(() => latest().push(frameAt(1)))
    act(() => latest().onmessage?.({ data: 'not json' }))
    act(() => latest().push(frameAt(2)))

    expect(screen.getByTestId('tick')).toHaveTextContent('2')
    expect(screen.getByTestId('connection')).toHaveTextContent('live')
  })

  it('reconnects when the socket drops', async () => {
    // Real timers here rather than fake ones: the provider also resolves the
    // plant fetch on mount, and freezing the clock around that promise is
    // what produces a stray act() warning. The first backoff is 500 ms, well
    // inside waitFor's window.
    render(
      <TwinProvider>
        <Probe />
      </TwinProvider>,
    )
    await waitFor(() => expect(screen.getByTestId('connection')).toHaveTextContent('connecting'))
    await waitFor(() => expect(latest()).toBeDefined())
    act(() => latest().onopen?.())

    const before = MockSocket.instances.length
    act(() => latest().onclose?.())
    expect(screen.getByTestId('connection')).toHaveTextContent('reconnecting')

    await waitFor(() => expect(MockSocket.instances.length).toBeGreaterThan(before))
  })
})

describe('useTwin outside a provider', () => {
  it('fails loudly rather than handing back undefined state', () => {
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Probe />)).toThrow(/must be used inside a <TwinProvider>/)
    quiet.mockRestore()
  })
})

/**
 * The console's single source of live state.
 *
 * One WebSocket for the whole app, held in a context provider. Every panel
 * reads the same frame, so nothing can show a KPI from one tick beside an
 * asset state from another - which is exactly the sort of inconsistency that
 * makes an operator stop believing a screen.
 */

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { api, streamUrl } from '../lib/api'
import type { Frame, Kpis, Plant } from '../lib/types'

export type ConnectionState = 'connecting' | 'live' | 'reconnecting' | 'failed'

/** Rolling KPI history, for the header sparklines. */
export interface KpiHistoryPoint extends Kpis {
  tick: number
  sim_time: number
}

const HISTORY_LIMIT = 240

interface TwinContextValue {
  plant: Plant | null
  frame: Frame | null
  history: KpiHistoryPoint[]
  connection: ConnectionState
  error: string | null
  /** Force an immediate out-of-band refresh, e.g. right after an action. */
  refresh: () => Promise<void>
}

const TwinContext = createContext<TwinContextValue | null>(null)

export function TwinProvider({ children }: { children: ReactNode }) {
  const [plant, setPlant] = useState<Plant | null>(null)
  const [frame, setFrame] = useState<Frame | null>(null)
  const [history, setHistory] = useState<KpiHistoryPoint[]>([])
  const [connection, setConnection] = useState<ConnectionState>('connecting')
  const [error, setError] = useState<string | null>(null)

  const socketRef = useRef<WebSocket | null>(null)
  const retriesRef = useRef(0)
  const timerRef = useRef<number | null>(null)
  const closedRef = useRef(false)

  const ingest = useCallback((next: Frame) => {
    setFrame(next)
    setHistory((prev) => {
      // Guard against a duplicate first frame: the server sends current state
      // on connect, which can repeat the tick we already have after a reconnect.
      if (prev.length > 0 && prev[prev.length - 1].tick >= next.tick) return prev
      const point: KpiHistoryPoint = { ...next.kpis, tick: next.tick, sim_time: next.sim_time }
      const appended = [...prev, point]
      return appended.length > HISTORY_LIMIT ? appended.slice(-HISTORY_LIMIT) : appended
    })
  }, [])

  const refresh = useCallback(async () => {
    try {
      const next = await api.frame()
      ingest(next)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [ingest])

  // Plant topology is static - fetch it once and keep it.
  useEffect(() => {
    let cancelled = false
    api
      .plant()
      .then((p) => {
        if (!cancelled) setPlant(p)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    closedRef.current = false

    const connect = () => {
      if (closedRef.current) return
      const socket = new WebSocket(streamUrl())
      socketRef.current = socket

      socket.onopen = () => {
        retriesRef.current = 0
        setConnection('live')
        setError(null)
      }

      socket.onmessage = (event) => {
        try {
          ingest(JSON.parse(event.data) as Frame)
        } catch {
          /* a malformed frame is not worth tearing the socket down for */
        }
      }

      socket.onerror = () => {
        // onclose always follows; reconnect is handled there so the backoff
        // is not advanced twice for a single failure.
      }

      socket.onclose = () => {
        if (closedRef.current) return
        const attempt = (retriesRef.current += 1)
        if (attempt > 8) {
          setConnection('failed')
          setError('Lost the twin-core stream. Is the service running on :8000?')
          return
        }
        setConnection('reconnecting')
        // Exponential backoff, capped: a plant-floor screen left open
        // overnight must not hammer a service that is down for maintenance.
        const delay = Math.min(10_000, 500 * 2 ** (attempt - 1))
        timerRef.current = window.setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      closedRef.current = true
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      socketRef.current?.close()
    }
  }, [ingest])

  return createElement(
    TwinContext.Provider,
    { value: { plant, frame, history, connection, error, refresh } },
    children,
  )
}

export function useTwin(): TwinContextValue {
  const context = useContext(TwinContext)
  if (context === null) throw new Error('useTwin must be used inside a <TwinProvider>')
  return context
}

/** Convenience: the snapshot for one asset on the current frame. */
export function useAsset(assetId: string | null) {
  const { frame, plant } = useTwin()
  if (assetId === null) return { snapshot: null, info: null }
  return {
    snapshot: frame?.assets[assetId] ?? null,
    info: plant?.assets.find((a) => a.id === assetId) ?? null,
  }
}

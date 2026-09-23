'use client'

/**
 * RealtimeContext — single shared WebSocket connection for the whole app.
 *
 * Wrapping the app in <RealtimeProvider> means every page shares ONE dashboard
 * WebSocket instead of each component opening its own.  Components subscribe
 * by listening to the 'sentinelcv:realtime' CustomEvent (already dispatched by
 * this provider) or by using the useRealtime() hook directly.
 *
 * Usage:
 *   const { connected } = useRealtime()
 */

import React, {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useRef,
    useState,
} from 'react'
import { realtimeService } from '@/services/api'
import { getAccessToken } from '@/lib/authSession'
import { subscribeToAccessToken } from '@/lib/authSession'

interface RealtimeContextValue {
    connected: boolean
}

const RealtimeContext = createContext<RealtimeContextValue>({ connected: false })

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
    const [connected, setConnected] = useState(false)
    const wsRef = useRef<WebSocket | null>(null)
    const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const mountedRef = useRef(true)

    const dispatch = useCallback((msg: unknown) => {
        if (typeof window === 'undefined') return
        window.dispatchEvent(new CustomEvent('sentinelcv:realtime', { detail: msg }))
    }, [])

    const connect = useCallback(() => {
        const token = getAccessToken()
        if (!token || !mountedRef.current) return

        // Close any existing connection cleanly
        if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) {
            wsRef.current.close()
        }

        try {
            const ws = new WebSocket(realtimeService.dashboardSocketUrl())
            wsRef.current = ws

            ws.onopen = () => {
                if (!mountedRef.current) { ws.close(); return }
                setConnected(true)
                if (reconnectRef.current) {
                    clearTimeout(reconnectRef.current)
                    reconnectRef.current = null
                }
            }

            ws.onmessage = (evt) => {
                if (!mountedRef.current) return
                try {
                    dispatch(JSON.parse(evt.data as string))
                } catch { /* ignore malformed frames */ }
            }

            ws.onclose = () => {
                if (!mountedRef.current) return
                setConnected(false)
                wsRef.current = null
                // Reconnect after 3 s
                reconnectRef.current = setTimeout(connect, 3000)
            }

            ws.onerror = () => {
                setConnected(false)
            }
        } catch {
            setConnected(false)
            reconnectRef.current = setTimeout(connect, 3000)
        }
    }, [dispatch])

    useEffect(() => {
        mountedRef.current = true

        // Connect as soon as a valid token is available
        if (getAccessToken()) {
            connect()
        }

        // React to token changes. A *refresh* fires this while the socket is
        // already live — tearing it down then would drop realtime on every
        // token rotation (the cause of frequent "connection lost" banners).
        // The WS authenticates only at handshake and stays valid for its
        // lifetime, so only (re)connect when there is no live socket.
        const unsub = subscribeToAccessToken((token) => {
            if (token) {
                const ws = wsRef.current
                const alive =
                    ws &&
                    (ws.readyState === WebSocket.CONNECTING ||
                        ws.readyState === WebSocket.OPEN)
                if (!alive) connect()
            } else {
                // Logged out — cancel any pending reconnect and close.
                if (reconnectRef.current) {
                    clearTimeout(reconnectRef.current)
                    reconnectRef.current = null
                }
                wsRef.current?.close()
                wsRef.current = null
                setConnected(false)
            }
        })

        return () => {
            mountedRef.current = false
            unsub()
            if (reconnectRef.current) clearTimeout(reconnectRef.current)
            wsRef.current?.close()
        }
    }, [connect])

    return (
        <RealtimeContext.Provider value={{ connected }}>
            {children}
        </RealtimeContext.Provider>
    )
}

export function useRealtime() {
    return useContext(RealtimeContext)
}

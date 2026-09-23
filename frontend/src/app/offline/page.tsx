'use client'

import { useEffect, useState } from 'react'
import { WifiOff, RefreshCw } from 'lucide-react'

export default function OfflinePage() {
    const [isOnline, setIsOnline] = useState(true)

    useEffect(() => {
        const update = () => setIsOnline(navigator.onLine)
        update()
        window.addEventListener('online', update)
        window.addEventListener('offline', update)
        return () => {
            window.removeEventListener('online', update)
            window.removeEventListener('offline', update)
        }
    }, [])

    useEffect(() => {
        if (isOnline) {
            const timeout = setTimeout(() => {
                window.location.reload()
            }, 600)
            return () => clearTimeout(timeout)
        }
    }, [isOnline])

    return (
        <main className="min-h-screen flex items-center justify-center px-6">
            <div className="max-w-md text-center">
                <div className="inline-flex items-center justify-center w-20 h-20 rounded-full bg-slate-800/60 mb-6">
                    <WifiOff className="w-10 h-10 text-slate-300" aria-hidden="true" />
                </div>
                <h1 className="text-3xl font-semibold mb-3">You&apos;re offline</h1>
                <p className="text-slate-400 mb-8">
                    SentinelCV needs an internet connection for live cameras, recognition, and
                    visitor logging. Cached pages may still be available; the dashboard will
                    refresh automatically once you&apos;re back online.
                </p>
                <button
                    type="button"
                    onClick={() => window.location.reload()}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 transition-colors"
                >
                    <RefreshCw className="w-4 h-4" aria-hidden="true" />
                    Try again
                </button>
                <p className="mt-6 text-xs text-slate-500">
                    Status: {isOnline ? 'reconnected' : 'offline'}
                </p>
            </div>
        </main>
    )
}

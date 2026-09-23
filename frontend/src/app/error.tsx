'use client'

import { useEffect } from 'react'

export default function Error({
    error,
    reset,
}: {
    error: Error
    reset: () => void
}) {
    useEffect(() => {
        console.error(error)
    }, [error])

    return (
        <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-[#050505] px-6 text-white">
            <h2 className="text-xl font-bold">Something went wrong</h2>
            <p className="max-w-xl text-center text-sm text-white/60">{error.message}</p>
            <button
                onClick={reset}
                className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-brand-400"
            >
                Try again
            </button>
        </div>
    )
}

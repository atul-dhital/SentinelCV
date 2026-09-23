'use client'

import { useEffect } from 'react'

const IGNORED_REJECTIONS = [
    'Cannot find menu item with id save-page',
]

// MediaPipe's WASM runtime routes its stderr INFO logs through console.error,
// which the Next.js dev overlay then reports as errors.
const IGNORED_CONSOLE_ERRORS = [
    'Created TensorFlow Lite XNNPACK delegate',
    'INFO: Created TensorFlow Lite',
]

function shouldIgnore(reason: unknown) {
    const message = reason instanceof Error ? reason.message : String(reason ?? '')
    return IGNORED_REJECTIONS.some((pattern) => message.includes(pattern))
}

export default function DevConsoleNoiseFilter() {
    useEffect(() => {
        if (process.env.NODE_ENV !== 'development') return

        const onUnhandledRejection = (event: PromiseRejectionEvent) => {
            if (shouldIgnore(event.reason)) {
                event.preventDefault()
            }
        }

        const originalConsoleError = console.error
        console.error = (...args: unknown[]) => {
            const first = args[0]
            const message = first instanceof Error ? first.message : String(first ?? '')
            if (IGNORED_CONSOLE_ERRORS.some((pattern) => message.includes(pattern))) {
                console.info(...args)
                return
            }
            originalConsoleError(...args)
        }

        window.addEventListener('unhandledrejection', onUnhandledRejection)
        return () => {
            window.removeEventListener('unhandledrejection', onUnhandledRejection)
            console.error = originalConsoleError
        }
    }, [])

    return null
}

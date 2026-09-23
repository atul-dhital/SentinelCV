'use client'

import { useEffect } from 'react'

export default function PwaRegister() {
    useEffect(() => {
        if (typeof window === 'undefined') {
            return
        }
        if (!('serviceWorker' in navigator)) {
            return
        }

        if (process.env.NODE_ENV !== 'production') {
            navigator.serviceWorker
                .getRegistrations()
                .then((registrations) => {
                    registrations.forEach((registration) => {
                        void registration.unregister()
                    })
                })
                .catch((error) => {
                    console.error('Service worker cleanup failed:', error)
                })
            return
        }

        navigator.serviceWorker
            .register('/sw.js')
            .catch((error) => {
                console.error('Service worker registration failed:', error)
            })
    }, [])

    return null
}

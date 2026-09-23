'use client'

import React, { createContext, useContext, useEffect, useState } from 'react'

type Theme = 'dark' | 'light'
const STORAGE_KEY = 'sentinelcv-theme'

interface ThemeContextValue {
    theme: Theme
    toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue>({
    theme: 'dark',
    toggleTheme: () => {},
})

export function useTheme() {
    return useContext(ThemeContext)
}

export default function ThemeProvider({ children }: { children: React.ReactNode }) {
    const [theme, setTheme] = useState<Theme>(() => {
        if (typeof window === 'undefined') {
            return 'dark'
        }

        const stored = window.localStorage.getItem(STORAGE_KEY)
        return stored === 'light' ? 'light' : 'dark'
    })

    useEffect(() => {
        document.documentElement.classList.toggle('light-mode', theme === 'light')
        window.localStorage.setItem(STORAGE_KEY, theme)
    }, [theme])

    useEffect(() => {
        const handleToggleTheme = () => {
            setTheme((current) => current === 'dark' ? 'light' : 'dark')
        }

        window.addEventListener('sentinelcv:toggle-theme', handleToggleTheme)
        return () => window.removeEventListener('sentinelcv:toggle-theme', handleToggleTheme)
    }, [])

    const toggleTheme = () => {
        setTheme((current) => current === 'dark' ? 'light' : 'dark')
    }

    return (
        <ThemeContext.Provider value={{ theme, toggleTheme }}>
            {children}
        </ThemeContext.Provider>
    )
}

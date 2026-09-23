'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Keyboard, Palette, X } from 'lucide-react'

const shortcuts = [
    { keys: ['g', 'd'], description: 'Go to Dashboard', path: '/' },
    { keys: ['g', 'v'], description: 'Go to Visitors', path: '/visitors' },
    { keys: ['g', 'c'], description: 'Go to Live Activities', path: '/live-activities' },
    { keys: ['g', 'l'], description: 'Go to Logs', path: '/logs' },
    { keys: ['g', 'u'], description: 'Go to Upload', path: '/upload' },
    { keys: ['g', 'a'], description: 'Go to Analytics', path: '/analytics' },
    { keys: ['g', 's'], description: 'Go to Settings', path: '/settings' },
    { keys: ['g', 'r'], description: 'Go to Recommendations', path: '/recommendations' },
    { keys: ['g', 'q'], description: 'Go to Data Quality', path: '/data-quality' },
    { keys: ['t'], description: 'Toggle theme', path: '' },
    { keys: ['?'], description: 'Show keyboard shortcuts', path: '' },
]

export default function KeyboardShortcuts() {
    const router = useRouter()
    const [showHelp, setShowHelp] = useState(false)
    const [pending, setPending] = useState<string | null>(null)

    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            // Don't trigger when typing in inputs
            const target = e.target as HTMLElement
            if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') return
            if (target.isContentEditable) return

            const key = e.key.toLowerCase()

            if (key === '?' && !e.ctrlKey && !e.metaKey) {
                e.preventDefault()
                setShowHelp(prev => !prev)
                return
            }

            if (key === 'escape') {
                setShowHelp(false)
                setPending(null)
                return
            }

            if (key === 't' && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault()
                window.dispatchEvent(new CustomEvent('sentinelcv:toggle-theme'))
                return
            }

            if (pending === 'g') {
                const match = shortcuts.find(s => s.keys[0] === 'g' && s.keys[1] === key)
                if (match && match.path) {
                    e.preventDefault()
                    router.push(match.path)
                }
                setPending(null)
                return
            }

            if (key === 'g') {
                setPending('g')
                setTimeout(() => setPending(null), 1500)
                return
            }
        }

        const openHandler = () => setShowHelp(true)
        const toggleHandler = () => setShowHelp(prev => !prev)

        window.addEventListener('keydown', handler)
        window.addEventListener('sentinelcv:open-shortcuts', openHandler)
        window.addEventListener('sentinelcv:toggle-shortcuts', toggleHandler)
        return () => {
            window.removeEventListener('keydown', handler)
            window.removeEventListener('sentinelcv:open-shortcuts', openHandler)
            window.removeEventListener('sentinelcv:toggle-shortcuts', toggleHandler)
        }
    }, [pending, router])

    if (!showHelp) return null

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm">
            <div className="bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
                <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
                    <div className="flex items-center gap-2">
                        <Keyboard size={20} className="text-brand-500" />
                        <h2 className="text-lg font-bold">Keyboard Shortcuts</h2>
                    </div>
                    <button
                        onClick={() => setShowHelp(false)}
                        className="text-gray-500 hover:text-white transition-colors"
                    >
                        <X size={20} />
                    </button>
                </div>
                <div className="px-6 py-4 space-y-2 max-h-[60vh] overflow-y-auto">
                    <div className="mb-3 rounded-2xl border border-brand-500/20 bg-brand-500/8 px-4 py-3">
                        <div className="flex items-center gap-2 text-sm font-semibold text-white">
                            <Palette size={16} className="text-brand-400" />
                            Quick actions
                        </div>
                        <p className="mt-1 text-xs text-gray-400">
                            Use <kbd className="px-1.5 py-0.5 bg-gray-800 border border-gray-600 rounded text-xs font-mono">t</kbd> to switch themes from anywhere.
                        </p>
                    </div>
                    {shortcuts.map((s, i) => (
                        <div key={i} className="flex items-center justify-between py-2">
                            <span className="text-sm text-gray-300">{s.description}</span>
                            <div className="flex items-center gap-1">
                                {s.keys.map((k, j) => (
                                    <span key={j}>
                                        <kbd className="px-2 py-1 bg-gray-800 border border-gray-600 rounded text-xs font-mono text-gray-300">
                                            {k}
                                        </kbd>
                                        {j < s.keys.length - 1 && (
                                            <span className="text-gray-600 mx-0.5">+</span>
                                        )}
                                    </span>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
                <div className="px-6 py-3 border-t border-gray-700 text-center">
                    <p className="text-xs text-gray-500">Press <kbd className="px-1.5 py-0.5 bg-gray-800 border border-gray-600 rounded text-xs font-mono">?</kbd> to toggle this dialog or <kbd className="px-1.5 py-0.5 bg-gray-800 border border-gray-600 rounded text-xs font-mono">Esc</kbd> to close</p>
                </div>
            </div>
        </div>
    )
}

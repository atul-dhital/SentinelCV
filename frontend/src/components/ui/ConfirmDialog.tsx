'use client'

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { AlertTriangle, X } from 'lucide-react'

// ── Public API ────────────────────────────────────────────────────────────────

type ConfirmKind = 'default' | 'danger'

export type ConfirmOptions = {
    title: string
    description?: React.ReactNode
    confirmLabel?: string
    cancelLabel?: string
    kind?: ConfirmKind
    // Type-to-confirm phrase — user must type this literally before confirm is enabled
    confirmPhrase?: string
}

type ConfirmContextValue = {
    confirm: (options: ConfirmOptions) => Promise<boolean>
}

const ConfirmContext = createContext<ConfirmContextValue | null>(null)

export function useConfirm() {
    const ctx = useContext(ConfirmContext)
    if (!ctx) throw new Error('useConfirm must be used within ConfirmDialogProvider')
    return ctx.confirm
}

// ── Provider ──────────────────────────────────────────────────────────────────

type State = {
    open: boolean
    options: ConfirmOptions
    resolver: ((value: boolean) => void) | null
}

const EMPTY_OPTIONS: ConfirmOptions = { title: '' }

export function ConfirmDialogProvider({ children }: { children: React.ReactNode }) {
    const [state, setState] = useState<State>({ open: false, options: EMPTY_OPTIONS, resolver: null })
    const [phraseInput, setPhraseInput] = useState('')
    const confirmBtnRef = useRef<HTMLButtonElement>(null)
    const cancelBtnRef = useRef<HTMLButtonElement>(null)

    const confirm = useCallback((options: ConfirmOptions) => {
        return new Promise<boolean>((resolve) => {
            setPhraseInput('')
            setState({ open: true, options, resolver: resolve })
        })
    }, [])

    const close = useCallback((result: boolean) => {
        setState((prev) => {
            prev.resolver?.(result)
            return { open: false, options: prev.options, resolver: null }
        })
    }, [])

    useEffect(() => {
        if (!state.open) return
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'Escape') close(false)
            if (e.key === 'Enter' && !state.options.confirmPhrase) close(true)
        }
        document.addEventListener('keydown', handler)
        return () => document.removeEventListener('keydown', handler)
    }, [state.open, state.options.confirmPhrase, close])

    // Focus primary button on open (cancel for danger so user can't fat-finger)
    useEffect(() => {
        if (!state.open) return
        const target = state.options.kind === 'danger' ? cancelBtnRef.current : confirmBtnRef.current
        target?.focus()
    }, [state.open, state.options.kind])

    const phraseRequired = Boolean(state.options.confirmPhrase)
    const phraseMet = !phraseRequired || phraseInput.trim() === state.options.confirmPhrase
    const kind = state.options.kind ?? 'default'

    const confirmBtnClass =
        kind === 'danger'
            ? 'bg-red-500 hover:bg-red-600 text-white disabled:bg-red-500/30 disabled:text-red-200/40'
            : 'bg-brand-600 hover:bg-brand-700 text-white disabled:bg-brand-600/30'

    return (
        <ConfirmContext.Provider value={{ confirm }}>
            {children}
            <AnimatePresence>
                {state.open && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.12 }}
                        className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm px-4"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="confirm-dialog-title"
                        onClick={(e) => { if (e.target === e.currentTarget) close(false) }}
                    >
                        <motion.div
                            initial={{ opacity: 0, y: 12, scale: 0.97 }}
                            animate={{ opacity: 1, y: 0, scale: 1 }}
                            exit={{ opacity: 0, y: 12, scale: 0.97 }}
                            transition={{ duration: 0.14 }}
                            className="w-full max-w-md rounded-2xl bg-gray-950 border border-white/10 shadow-2xl"
                        >
                            <div className="flex items-start gap-3 p-5 border-b border-white/5">
                                {kind === 'danger' && (
                                    <div className="w-9 h-9 shrink-0 rounded-full bg-red-500/10 flex items-center justify-center">
                                        <AlertTriangle size={18} className="text-red-400" />
                                    </div>
                                )}
                                <div className="flex-1 min-w-0">
                                    <h2 id="confirm-dialog-title" className="text-base font-semibold text-white leading-tight">
                                        {state.options.title}
                                    </h2>
                                    {state.options.description && (
                                        <div className="text-sm text-gray-400 mt-1 leading-relaxed">
                                            {state.options.description}
                                        </div>
                                    )}
                                </div>
                                <button
                                    onClick={() => close(false)}
                                    aria-label="Close dialog"
                                    className="p-1 rounded-lg text-gray-500 hover:text-white hover:bg-white/5 transition-colors"
                                >
                                    <X size={16} />
                                </button>
                            </div>
                            {phraseRequired && (
                                <div className="px-5 pt-4">
                                    <label className="block text-xs text-gray-400 mb-1.5">
                                        Type <span className="font-mono text-red-400">{state.options.confirmPhrase}</span> to confirm
                                    </label>
                                    <input
                                        type="text"
                                        autoFocus
                                        value={phraseInput}
                                        onChange={(e) => setPhraseInput(e.target.value)}
                                        className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-red-500 transition-colors"
                                        aria-label="Type confirmation phrase"
                                    />
                                </div>
                            )}
                            <div className="flex items-center justify-end gap-2 p-4">
                                <button
                                    ref={cancelBtnRef}
                                    onClick={() => close(false)}
                                    className="px-4 py-2 rounded-lg text-sm text-gray-300 hover:bg-white/5 transition-colors"
                                >
                                    {state.options.cancelLabel ?? 'Cancel'}
                                </button>
                                <button
                                    ref={confirmBtnRef}
                                    onClick={() => close(true)}
                                    disabled={!phraseMet}
                                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:cursor-not-allowed ${confirmBtnClass}`}
                                >
                                    {state.options.confirmLabel ?? 'Confirm'}
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </ConfirmContext.Provider>
    )
}

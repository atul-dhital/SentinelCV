'use client'

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, AlertTriangle, Info, X, XCircle } from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────

type ToastKind = 'success' | 'error' | 'info' | 'warning'

export type ToastInput = {
    kind?: ToastKind
    title?: string
    message: string
    action?: { label: string; onClick: () => void }
    // Override default duration (ms). Errors stay indefinitely if they have an action.
    durationMs?: number
}

type Toast = ToastInput & {
    id: string
    kind: ToastKind
    durationMs: number
    createdAt: number
}

type ToastContextValue = {
    show: (t: ToastInput) => string
    dismiss: (id: string) => void
    success: (message: string, opts?: Partial<ToastInput>) => string
    error: (message: string, opts?: Partial<ToastInput>) => string
    info: (message: string, opts?: Partial<ToastInput>) => string
    warning: (message: string, opts?: Partial<ToastInput>) => string
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function useToast() {
    const ctx = useContext(ToastContext)
    if (!ctx) throw new Error('useToast must be used within ToastProvider')
    return ctx
}

// ── Durations ─────────────────────────────────────────────────────────────────

const DEFAULT_DURATIONS: Record<ToastKind, number> = {
    success: 5000,
    info: 5000,
    warning: 6000,
    error: 8000,
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function ToastProvider({ children }: { children: React.ReactNode }) {
    const [toasts, setToasts] = useState<Toast[]>([])
    const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
    const pausedSet = useRef<Set<string>>(new Set())

    const clearTimer = useCallback((id: string) => {
        const t = timers.current.get(id)
        if (t) {
            clearTimeout(t)
            timers.current.delete(id)
        }
    }, [])

    const dismiss = useCallback((id: string) => {
        clearTimer(id)
        pausedSet.current.delete(id)
        setToasts((prev) => prev.filter((t) => t.id !== id))
    }, [clearTimer])

    const scheduleDismiss = useCallback((id: string, durationMs: number) => {
        clearTimer(id)
        const timer = setTimeout(() => dismiss(id), durationMs)
        timers.current.set(id, timer)
    }, [clearTimer, dismiss])

    const show = useCallback((input: ToastInput): string => {
        const kind: ToastKind = input.kind ?? 'info'
        const durationMs = input.durationMs ?? DEFAULT_DURATIONS[kind]
        const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
        const toast: Toast = {
            ...input,
            id,
            kind,
            durationMs,
            createdAt: Date.now(),
        }
        setToasts((prev) => [...prev, toast])
        // Errors with an action stay until dismissed
        if (kind !== 'error' || !input.action) {
            scheduleDismiss(id, durationMs)
        }
        return id
    }, [scheduleDismiss])

    const success = useCallback((message: string, opts?: Partial<ToastInput>) =>
        show({ ...opts, message, kind: 'success' }), [show])
    const error = useCallback((message: string, opts?: Partial<ToastInput>) =>
        show({ ...opts, message, kind: 'error' }), [show])
    const info = useCallback((message: string, opts?: Partial<ToastInput>) =>
        show({ ...opts, message, kind: 'info' }), [show])
    const warning = useCallback((message: string, opts?: Partial<ToastInput>) =>
        show({ ...opts, message, kind: 'warning' }), [show])

    const handleMouseEnter = useCallback((id: string) => {
        pausedSet.current.add(id)
        clearTimer(id)
    }, [clearTimer])

    const handleMouseLeave = useCallback((id: string) => {
        if (!pausedSet.current.has(id)) return
        pausedSet.current.delete(id)
        const t = toasts.find((x) => x.id === id)
        if (t && (t.kind !== 'error' || !t.action)) {
            scheduleDismiss(id, Math.max(1500, Math.floor(t.durationMs / 2)))
        }
    }, [toasts, scheduleDismiss])

    useEffect(() => {
        return () => {
            timers.current.forEach((t) => clearTimeout(t))
            timers.current.clear()
        }
    }, [])

    return (
        <ToastContext.Provider value={{ show, dismiss, success, error, info, warning }}>
            {children}
            <div
                className="fixed top-4 right-4 z-[120] flex flex-col gap-2 pointer-events-none max-w-sm w-[calc(100vw-2rem)]"
                role="region"
                aria-label="Notifications"
                aria-live="polite"
            >
                <AnimatePresence initial={false}>
                    {toasts.map((toast) => (
                        <ToastItem
                            key={toast.id}
                            toast={toast}
                            onDismiss={() => dismiss(toast.id)}
                            onMouseEnter={() => handleMouseEnter(toast.id)}
                            onMouseLeave={() => handleMouseLeave(toast.id)}
                        />
                    ))}
                </AnimatePresence>
            </div>
        </ToastContext.Provider>
    )
}

// ── Toast Item ────────────────────────────────────────────────────────────────

const KIND_STYLES: Record<ToastKind, { icon: React.ElementType; color: string; bg: string; border: string }> = {
    success: { icon: CheckCircle2, color: 'text-green-400', bg: 'bg-green-500/5', border: 'border-green-500/20' },
    error: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/5', border: 'border-red-500/30' },
    warning: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/5', border: 'border-amber-500/20' },
    info: { icon: Info, color: 'text-blue-400', bg: 'bg-blue-500/5', border: 'border-blue-500/20' },
}

function ToastItem({
    toast,
    onDismiss,
    onMouseEnter,
    onMouseLeave,
}: {
    toast: Toast
    onDismiss: () => void
    onMouseEnter: () => void
    onMouseLeave: () => void
}) {
    const { icon: Icon, color, bg, border } = KIND_STYLES[toast.kind]
    return (
        <motion.div
            layout
            initial={{ opacity: 0, y: -12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, x: 40, transition: { duration: 0.18 } }}
            transition={{ duration: 0.16, ease: 'easeOut' }}
            onMouseEnter={onMouseEnter}
            onMouseLeave={onMouseLeave}
            role={toast.kind === 'error' ? 'alert' : 'status'}
            className={`pointer-events-auto rounded-xl border ${border} ${bg} backdrop-blur-xl bg-gray-950/90 shadow-2xl p-3 flex items-start gap-3`}
        >
            <Icon size={18} className={`${color} shrink-0 mt-0.5`} aria-hidden="true" />
            <div className="flex-1 min-w-0">
                {toast.title && (
                    <p className="text-sm font-semibold text-white leading-tight">{toast.title}</p>
                )}
                <p className={`text-sm text-gray-300 leading-relaxed ${toast.title ? 'mt-0.5' : ''}`}>
                    {toast.message}
                </p>
                {toast.action && (
                    <button
                        onClick={() => { toast.action?.onClick(); onDismiss() }}
                        className={`mt-2 text-xs font-semibold ${color} hover:underline`}
                    >
                        {toast.action.label}
                    </button>
                )}
            </div>
            <button
                onClick={onDismiss}
                aria-label="Dismiss notification"
                className="p-1 rounded-md text-gray-500 hover:text-white hover:bg-white/5 transition-colors shrink-0"
            >
                <X size={14} />
            </button>
        </motion.div>
    )
}

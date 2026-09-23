'use client'

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Users, Video, UserCheck, UserX, ArrowRight, Clock, AlertCircle, Camera, BarChart3, RefreshCw, Activity, LayoutGrid, MonitorUp, SlidersHorizontal, RotateCcw, WifiOff, CheckCircle2, X, Rocket, ChevronRight } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import Navbar from '@/components/Navbar'
import MediaImage from '@/components/MediaImage'
import { logService, authService, cameraService, analyticsService } from '@/services/api'
import { useRealtime } from '@/contexts/RealtimeContext'
import type { DashboardStats, VisitorLog, Camera as CameraType } from '@/services/api'
import { getStaticMediaUrl } from '@/lib/utils'
import { dedupeStreamLogs, getSourceLabel } from '@/lib/streamLogs'

const DASHBOARD_PREFS_KEY = 'sentinelcv-dashboard-prefs'
const ONBOARDING_DONE_KEY = 'sentinelcv-onboarding-done'

const DEFAULT_DASHBOARD_PREFS = {
    visibleStatCards: [
        'identified_count',
        'unidentified_count',
        'total_events',
        'total_visitors',
        'pending_review',
        'cameras_online',
    ],
    showStatsGrid: true,
    showActivityFeed: true,
    showQuickActions: true,
    showLivenessPanel: true,
    showSystemHealth: true,
    compactStats: false,
}

type DashboardPrefKey = keyof typeof DEFAULT_DASHBOARD_PREFS
type DashboardPrefs = typeof DEFAULT_DASHBOARD_PREFS

// ── Confidence badge with human-readable label ────────────────────────────────
function ConfidenceBadge({ status, confidence }: { status: string; confidence: number }) {
    const pct = Math.round(confidence * 100)
    const colorClass = pct >= 80 ? 'text-green-400 bg-green-400/10' : pct >= 60 ? 'text-yellow-400 bg-yellow-400/10' : 'text-red-400 bg-red-400/10'
    const humanLabel = pct >= 80 ? 'High' : pct >= 60 ? 'Review' : 'Low'

    switch (status) {
        case 'identified':
            return (
                <span className={`text-xs px-2 py-1 rounded flex items-center gap-1 ${colorClass}`}>
                    <CheckCircle2 size={10} />
                    {pct}% · {humanLabel}
                </span>
            )
        case 'unidentified':
            return <span className="text-xs text-red-400 bg-red-400/10 px-2 py-1 rounded">Unidentified</span>
        case 'reviewed':
            return <span className="text-xs text-blue-400 bg-blue-400/10 px-2 py-1 rounded">Reviewed</span>
        default:
            return <span className="text-xs text-yellow-400 bg-yellow-400/10 px-2 py-1 rounded">Detected</span>
    }
}

// ── Onboarding wizard ─────────────────────────────────────────────────────────
const ONBOARDING_STEPS = [
    {
        step: 1,
        title: 'Add a camera',
        desc: 'Connect an RTSP stream or test camera to start receiving live detections.',
        action: '/cameras',
        actionLabel: 'Add Camera',
        icon: Camera,
    },
    {
        step: 2,
        title: 'Enroll a visitor',
        desc: 'Upload face images or record via webcam to build your recognition database.',
        action: '/visitors',
        actionLabel: 'Add Visitor',
        icon: Users,
    },
    {
        step: 3,
        title: 'Process a video',
        desc: 'Upload a surveillance video to run AI detection and generate your first events.',
        action: '/upload',
        actionLabel: 'Upload Video',
        icon: Video,
    },
    {
        step: 4,
        title: 'Review detections',
        desc: 'Check the Detection Logs to see identified and unidentified visitors.',
        action: '/logs',
        actionLabel: 'View Logs',
        icon: BarChart3,
    },
]

function OnboardingWizard({ onDismiss }: { onDismiss: () => void }) {
    const [step, setStep] = useState(0)
    const current = ONBOARDING_STEPS[step]
    const isLast = step === ONBOARDING_STEPS.length - 1

    return (
        <AnimatePresence>
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center px-4"
            >
                <motion.div
                    initial={{ opacity: 0, scale: 0.94, y: 20 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.94, y: 20 }}
                    className="bg-gray-950 border border-white/10 rounded-3xl p-8 w-full max-w-lg shadow-2xl relative"
                >
                    <button
                        onClick={onDismiss}
                        className="absolute top-4 right-4 p-2 rounded-lg text-gray-500 hover:text-white hover:bg-white/5 transition-colors"
                    >
                        <X size={18} />
                    </button>

                    {/* Progress dots */}
                    <div className="flex items-center gap-2 mb-6">
                        {ONBOARDING_STEPS.map((_, i) => (
                            <button
                                key={i}
                                onClick={() => { if (i <= step) setStep(i) }}
                                className={`h-1 flex-1 rounded-full transition-colors ${
                                    i <= step ? 'bg-brand-500 cursor-pointer hover:bg-brand-400' : 'bg-white/10 cursor-default'
                                }`}
                            />
                        ))}
                    </div>

                    <div className="flex items-center gap-4 mb-4">
                        <div className="w-12 h-12 bg-brand-500/10 rounded-2xl flex items-center justify-center shrink-0">
                            <current.icon size={24} className="text-brand-400" />
                        </div>
                        <div>
                            <p className="text-xs font-bold text-brand-400 uppercase tracking-widest mb-0.5">
                                Step {step + 1} of {ONBOARDING_STEPS.length}
                            </p>
                            <h2 className="text-xl font-black text-white">{current.title}</h2>
                        </div>
                    </div>

                    <p className="text-gray-400 leading-relaxed mb-8">{current.desc}</p>

                    <div className="flex gap-3">
                        {step > 0 && (
                            <button
                                onClick={() => setStep(s => s - 1)}
                                className="px-5 py-3 rounded-xl border border-white/10 text-gray-400 hover:text-white text-sm font-medium transition-colors"
                            >
                                &larr; Back
                            </button>
                        )}
                        <Link
                            href={current.action}
                            onClick={onDismiss}
                            className="flex-1 bg-brand-600 hover:bg-brand-500 text-white py-3 rounded-xl font-bold text-sm transition-colors flex items-center justify-center gap-2"
                        >
                            {current.actionLabel}
                            <ArrowRight size={16} />
                        </Link>
                        {!isLast ? (
                            <button
                                onClick={() => setStep(s => s + 1)}
                                className="px-5 py-3 rounded-xl border border-white/10 text-gray-400 hover:text-white text-sm font-medium transition-colors"
                            >
                                Next
                            </button>
                        ) : (
                            <button
                                onClick={onDismiss}
                                className="px-5 py-3 rounded-xl border border-white/10 text-gray-400 hover:text-white text-sm font-medium transition-colors"
                            >
                                Done
                            </button>
                        )}
                    </div>

                    <button
                        onClick={onDismiss}
                        className="w-full mt-3 text-xs text-gray-600 hover:text-gray-400 transition-colors"
                    >
                        Skip setup — I&apos;ll explore on my own
                    </button>
                </motion.div>
            </motion.div>
        </AnimatePresence>
    )
}

// ── WebSocket disconnect banner ───────────────────────────────────────────────
function WsDisconnectBanner({ onRefresh }: { onRefresh: () => void }) {
    return (
        <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="flex items-center gap-3 bg-yellow-500/10 border border-yellow-500/30 text-yellow-400 text-sm px-5 py-3 rounded-xl mb-6"
        >
            <WifiOff size={16} className="shrink-0" />
            <span className="flex-1">
                <strong>Real-time connection lost</strong> — Dashboard may show stale data.
                Reconnecting automatically…
            </span>
            <button
                onClick={onRefresh}
                className="flex items-center gap-1.5 text-xs font-bold bg-yellow-500/20 hover:bg-yellow-500/30 px-3 py-1.5 rounded-lg transition-colors"
            >
                <RefreshCw size={12} /> Refresh now
            </button>
        </motion.div>
    )
}

// ── Main Dashboard ────────────────────────────────────────────────────────────
export default function Dashboard() {
    const router = useRouter()
    const lastRealtimeRefreshRef = useRef(0)
    const [stats, setStats] = useState<DashboardStats>({
        identified_count: 0,
        unidentified_count: 0,
        total_events: 0,
        total_visitors: 0,
        pending_review: 0,
        cameras_online: 0,
    })
    const [recentLogs, setRecentLogs] = useState<VisitorLog[]>([])
    const [cameras, setCameras] = useState<CameraType[]>([])
    const [systemHealth, setSystemHealth] = useState<{
        ai_service_status: string;
        avg_processing_time_ms: number;
        total_processed_today: number;
        error_rate: number;
        storage_used_mb: number;
        database_size_mb: number;
    } | null>(null)
    const [loading, setLoading] = useState(true)
    const [showCustomizer, setShowCustomizer] = useState(false)
    const [dashboardPrefs, setDashboardPrefs] = useState<DashboardPrefs>(DEFAULT_DASHBOARD_PREFS)

    // UX improvements — WS connection is managed by RealtimeContext (layout.tsx)
    const { connected: wsConnected } = useRealtime()
    const [showOnboarding, setShowOnboarding] = useState(false)
    const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null)
    const [refreshing, setRefreshing] = useState(false)
    const [fetchError, setFetchError] = useState<string | null>(null)

    const fetchData = useCallback(async () => {
        try {
            const results = await Promise.allSettled([
                logService.getDashboardStats(),
                logService.getLogs({ limit: 40 }),
                cameraService.getCameras(),
                analyticsService.getSystemHealth(),
            ])

            const [statsResult, logsResult, camerasResult, healthResult] = results
            const failedNames: string[] = []

            if (statsResult.status === 'fulfilled') {
                setStats(statsResult.value.data)
            } else {
                if ((statsResult.reason as any)?.response?.status === 401) { router.push('/login'); return }
                failedNames.push('dashboard stats')
            }

            if (logsResult.status === 'fulfilled') {
                setRecentLogs(dedupeStreamLogs(logsResult.value.data.items || [], 5))
            } else {
                failedNames.push('recent events')
            }

            if (camerasResult.status === 'fulfilled') {
                setCameras(camerasResult.value.data || [])
            } else {
                failedNames.push('cameras')
            }

            if (healthResult.status === 'fulfilled' && healthResult.value.data) {
                setSystemHealth(healthResult.value.data)
            } else if (healthResult.status === 'rejected') {
                failedNames.push('system health')
            }

            if (failedNames.length > 0) {
                setFetchError(`Could not load: ${failedNames.join(', ')}. Data may be stale.`)
            } else {
                setFetchError(null)
            }

            setLastRefreshed(new Date())
        } catch (err: any) {
            if (err.response?.status === 401) {
                router.push('/login')
                return
            }
            console.error('Failed to fetch dashboard data:', err)
            setFetchError('Failed to load dashboard data. Please refresh.')
        } finally {
            setLoading(false)
            setRefreshing(false)
        }
    }, [router])

    const handleManualRefresh = useCallback(() => {
        setRefreshing(true)
        void fetchData()
    }, [fetchData])

    useEffect(() => {
        let interval: ReturnType<typeof setInterval> | null = null
        let mounted = true

        const start = async () => {
            const ok = await authService.ensureSession()
            if (!mounted) return
            if (!ok) {
                router.push('/login')
                return
            }
            await fetchData()
            interval = setInterval(fetchData, 15000)
        }

        void start()
        return () => {
            mounted = false
            if (interval) clearInterval(interval)
        }
    }, [fetchData, router])

    // Show onboarding for first-time users (no events and no visitors)
    useEffect(() => {
        if (loading) return
        const done = localStorage.getItem(ONBOARDING_DONE_KEY)
        if (!done && stats.total_events === 0 && stats.total_visitors === 0) {
            setShowOnboarding(true)
        }
    }, [loading, stats.total_events, stats.total_visitors])

    const dismissOnboarding = () => {
        setShowOnboarding(false)
        localStorage.setItem(ONBOARDING_DONE_KEY, '1')
    }

    const refreshFromRealtime = useCallback((force = false) => {
        const now = Date.now()
        if (!force && now - lastRealtimeRefreshRef.current < 5000) return
        lastRealtimeRefreshRef.current = now
        void fetchData()
    }, [fetchData])

    const upsertCameraFromRealtime = useCallback((payload: any) => {
        if (!payload?.id) return
        setCameras((prev) => {
            const index = prev.findIndex((camera) => camera.id === payload.id)
            if (index === -1) return [payload as CameraType, ...prev]
            const next = [...prev]
            next[index] = { ...next[index], ...payload }
            return next
        })
    }, [])

    const removeCameraFromRealtime = useCallback((cameraId?: string) => {
        if (!cameraId) return
        setCameras((prev) => prev.filter((camera) => camera.id !== cameraId))
    }, [])

    // Listen to the global realtime event bus dispatched by RealtimeContext.
    // The single shared WebSocket connection lives in RealtimeContext (layout.tsx);
    // all pages receive events here without opening their own connections.
    useEffect(() => {
        const handler = (e: Event) => {
            const msg = (e as CustomEvent).detail
            if (!msg?.type) return
            try {
                switch (msg.type) {
                    case 'camera.status_changed':
                    case 'camera.created':
                    case 'camera.updated':
                        upsertCameraFromRealtime(msg.payload)
                        break
                    case 'camera.deleted':
                        removeCameraFromRealtime(msg.payload?.id)
                        break
                    case 'log.created':
                        if (msg.payload) {
                            setStats(prev => ({
                                ...prev,
                                total_events: prev.total_events + 1,
                                identified_count: msg.payload.identified
                                    ? prev.identified_count + 1
                                    : prev.identified_count,
                                unidentified_count: !msg.payload.identified
                                    ? prev.unidentified_count + 1
                                    : prev.unidentified_count,
                            }))
                        }
                        refreshFromRealtime(true)
                        break
                    case 'camera.frame_processed':
                        refreshFromRealtime(false)
                        break
                    default:
                        refreshFromRealtime(false)
                        break
                }
            } catch {
                refreshFromRealtime(false)
            }
        }

        window.addEventListener('sentinelcv:realtime', handler)
        return () => window.removeEventListener('sentinelcv:realtime', handler)
    }, [refreshFromRealtime, removeCameraFromRealtime, upsertCameraFromRealtime])

    useEffect(() => {
        const rawPrefs = localStorage.getItem(DASHBOARD_PREFS_KEY)
        if (!rawPrefs) return
        try {
            const parsed = JSON.parse(rawPrefs)
            setDashboardPrefs({
                ...DEFAULT_DASHBOARD_PREFS,
                ...parsed,
                visibleStatCards: Array.isArray(parsed.visibleStatCards) && parsed.visibleStatCards.length > 0
                    ? parsed.visibleStatCards
                    : DEFAULT_DASHBOARD_PREFS.visibleStatCards,
            })
        } catch {
            localStorage.removeItem(DASHBOARD_PREFS_KEY)
        }
    }, [])

    useEffect(() => {
        localStorage.setItem(DASHBOARD_PREFS_KEY, JSON.stringify(dashboardPrefs))
    }, [dashboardPrefs])

    const statCards = [
        { key: 'identified_count', label: 'Identified Visitors', value: stats.identified_count, icon: UserCheck, color: 'text-green-400', bg: 'bg-green-400/10' },
        { key: 'unidentified_count', label: 'Unidentified', value: stats.unidentified_count, icon: UserX, color: 'text-red-400', bg: 'bg-red-400/10' },
        { key: 'total_events', label: 'Total Events', value: stats.total_events, icon: Video, color: 'text-brand-500', bg: 'bg-brand-500/10' },
        { key: 'total_visitors', label: 'Known Visitors', value: stats.total_visitors, icon: Users, color: 'text-blue-400', bg: 'bg-blue-400/10' },
        { key: 'pending_review', label: 'Pending Review', value: stats.pending_review, icon: AlertCircle, color: 'text-yellow-400', bg: 'bg-yellow-400/10' },
        { key: 'cameras_online', label: 'Active Streams', value: stats.cameras_online, icon: Activity, color: 'text-purple-400', bg: 'bg-purple-400/10' },
    ]

    const visibleStatCards = statCards.filter((card) => dashboardPrefs.visibleStatCards.includes(card.key))
    const maxStatValue = Math.max(1, ...visibleStatCards.map(s => s.value ?? 0))
    const hasRightColumn = dashboardPrefs.showQuickActions || dashboardPrefs.showSystemHealth
    const leftColumnSpan = hasRightColumn ? 'lg:col-span-8' : 'lg:col-span-12'

    const toggleSection = (key: Exclude<DashboardPrefKey, 'visibleStatCards'>) => {
        setDashboardPrefs((prev) => ({ ...prev, [key]: !prev[key] }))
    }

    const toggleStatCard = (cardKey: string) => {
        setDashboardPrefs((prev) => {
            const isVisible = prev.visibleStatCards.includes(cardKey)
            const nextVisible = isVisible
                ? prev.visibleStatCards.filter((key) => key !== cardKey)
                : [...prev.visibleStatCards, cardKey]
            return { ...prev, visibleStatCards: nextVisible.length > 0 ? nextVisible : prev.visibleStatCards }
        })
    }

    const resetDashboardPrefs = () => { setDashboardPrefs(DEFAULT_DASHBOARD_PREFS) }

    const getStreamImageUrl = (log: VisitorLog) => getStaticMediaUrl(log.visitor_image_url || log.face_image_path)

    const getStreamSubjectLabel = (log: VisitorLog) => {
        const subjectCode = log.visitor_id ? `Subject PR-${log.visitor_id.slice(0, 8).toUpperCase()}` : null
        if (log.identified && log.visitor_name) return log.visitor_name
        if (log.visitor_name) return log.visitor_name
        if (subjectCode) return log.identified ? subjectCode : `${subjectCode}- unknown`
        return 'Unidentified Subject'
    }

    const timeAgo = (timestamp: string) => {
        const diff = Date.now() - new Date(timestamp).getTime()
        const mins = Math.floor(diff / 60000)
        if (mins < 1) return 'Just now'
        if (mins < 60) return `${mins}m ago`
        const hours = Math.floor(mins / 60)
        if (hours < 24) return `${hours}h ago`
        return `${Math.floor(hours / 24)}d ago`
    }

    const isEmpty = !loading && stats.total_events === 0 && stats.total_visitors === 0

    return (
        <div className="min-h-screen">
            <Navbar />
            {showOnboarding && <OnboardingWizard onDismiss={dismissOnboarding} />}

            <main className="pt-32 pb-20 px-6 container mx-auto">
                {/* Header */}
                <div className="flex flex-col md:flex-row justify-between items-start md:items-end mb-8 gap-6 relative">
                    <div className="absolute -top-10 -left-10 w-40 h-40 bg-brand-500/10 blur-[100px] -z-10" />
                    <div>
                        <motion.div
                            initial={{ opacity: 0, x: -20 }}
                            animate={{ opacity: 1, x: 0 }}
                            className="flex items-center gap-2 mb-2"
                        >
                            <span className="w-2 h-2 rounded-full bg-brand-500 animate-pulse" />
                            <span className="text-xs font-bold text-brand-400 uppercase tracking-widest leading-none">System Active</span>
                        </motion.div>
                        <motion.h1
                            initial={{ opacity: 0, y: 20 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="text-4xl md:text-6xl font-black mb-4 bg-gradient-to-b from-white via-white to-white/40 bg-clip-text text-transparent tracking-tight"
                        >
                            Intelligence Hub
                        </motion.h1>
                        <p className="text-gray-400 text-lg max-w-xl leading-relaxed">
                            Monitor real-time visitor streams and identification metrics with advanced computer vision insights.
                        </p>
                    </div>

                    {/* Refresh button with feedback */}
                    <div className="flex items-center gap-3">
                        <div className="text-right">
                            <button
                                onClick={handleManualRefresh}
                                disabled={refreshing}
                                className="flex items-center gap-2 px-4 py-2.5 rounded-xl border border-white/10 bg-white/5 text-sm font-medium text-gray-400 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-50"
                            >
                                <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
                                Refresh
                            </button>
                            {lastRefreshed && (
                                <p className="text-xs text-gray-600 mt-1">
                                    Updated {timeAgo(lastRefreshed.toISOString())}
                                </p>
                            )}
                        </div>
                        <Link
                            href="/upload"
                            className="bg-brand-600 hover:bg-brand-500 text-white px-6 py-3 rounded-2xl font-bold transition-all flex items-center gap-3 shadow-xl shadow-brand-600/20 hover:shadow-brand-600/40 group overflow-hidden relative"
                        >
                            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-1000" />
                            <Video size={18} className="group-hover:scale-110 transition-transform" />
                            <span>Process Stream</span>
                        </Link>
                    </div>
                </div>

                {/* WebSocket disconnect banner */}
                <AnimatePresence>
                    {!wsConnected && (
                        <WsDisconnectBanner onRefresh={handleManualRefresh} />
                    )}
                </AnimatePresence>

                {/* API fetch error banner */}
                <AnimatePresence>
                    {fetchError && (
                        <motion.div
                            initial={{ opacity: 0, y: -10 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -10 }}
                            className="mb-4 flex items-center gap-3 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300"
                        >
                            <AlertCircle size={16} className="shrink-0" />
                            <span className="flex-1">{fetchError}</span>
                            <button
                                onClick={() => setFetchError(null)}
                                className="ml-auto text-red-300/60 hover:text-red-300 transition-colors"
                                aria-label="Dismiss"
                            >
                                <X size={14} />
                            </button>
                        </motion.div>
                    )}
                </AnimatePresence>

                {/* Empty state with setup CTAs */}
                {isEmpty && (
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="glass-card p-10 mb-8 border-dashed border-2 border-white/10 bg-transparent text-center"
                    >
                        <div className="w-16 h-16 bg-brand-500/10 rounded-2xl flex items-center justify-center mx-auto mb-4">
                            <Rocket size={28} className="text-brand-400" />
                        </div>
                        <h2 className="text-2xl font-black text-white mb-2">Welcome to SentinelCV</h2>
                        <p className="text-gray-400 max-w-md mx-auto mb-6">
                            Your dashboard is empty. Get started by connecting a camera, enrolling visitors, or uploading a surveillance video.
                        </p>
                        <div className="flex flex-wrap justify-center gap-3">
                            {[
                                { href: '/cameras', label: 'Add Camera', icon: Camera },
                                { href: '/visitors', label: 'Enroll Visitors', icon: Users },
                                { href: '/upload', label: 'Upload Video', icon: Video },
                            ].map(item => (
                                <Link
                                    key={item.href}
                                    href={item.href}
                                    className="flex items-center gap-2 px-5 py-3 rounded-xl border border-white/10 bg-white/5 text-sm font-semibold text-gray-300 hover:text-white hover:bg-white/10 hover:border-brand-500/40 transition-all"
                                >
                                    <item.icon size={16} />
                                    {item.label}
                                    <ChevronRight size={14} className="text-gray-600" />
                                </Link>
                            ))}
                        </div>
                        <button
                            onClick={() => setShowOnboarding(true)}
                            className="mt-4 text-sm text-brand-400 hover:text-brand-300 transition-colors"
                        >
                            Show setup guide →
                        </button>
                    </motion.div>
                )}

                {/* Dashboard customizer */}
                <div className="glass-card p-5 mb-8">
                    <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
                        <div className="flex items-start gap-3">
                            <div className="p-3 rounded-2xl bg-brand-500/10 text-brand-400">
                                <LayoutGrid size={20} />
                            </div>
                            <div>
                                <h2 className="text-lg font-black text-white">Dashboard Customization</h2>
                                <p className="text-sm text-gray-400">Choose which widgets stay on your command surface. Preferences persist on this browser.</p>
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-3">
                            <button
                                onClick={() => setShowCustomizer((prev) => !prev)}
                                className="px-4 py-2.5 rounded-xl border border-white/10 bg-white/5 text-sm font-bold text-gray-200 hover:bg-white/10 transition-colors flex items-center gap-2"
                            >
                                <SlidersHorizontal size={16} />
                                {showCustomizer ? 'Hide Controls' : 'Customize Layout'}
                            </button>
                            <button
                                onClick={resetDashboardPrefs}
                                className="px-4 py-2.5 rounded-xl border border-white/10 bg-white/5 text-sm font-bold text-gray-400 hover:text-white hover:bg-white/10 transition-colors flex items-center gap-2"
                            >
                                <RotateCcw size={16} />
                                Reset
                            </button>
                        </div>
                    </div>

                    {showCustomizer && (
                        <div className="mt-5 pt-5 border-t border-white/5 grid grid-cols-1 xl:grid-cols-2 gap-6">
                            <div>
                                <p className="text-xs font-black uppercase tracking-widest text-gray-500 mb-3">Sections</p>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                    {[
                                        { key: 'showStatsGrid', label: 'Stats Grid' },
                                        { key: 'showActivityFeed', label: 'Activity Feed' },
                                        { key: 'showQuickActions', label: 'Quick Actions' },
                                        { key: 'showLivenessPanel', label: 'Liveness Panel' },
                                        { key: 'showSystemHealth', label: 'System Health' },
                                        { key: 'compactStats', label: 'Compact Stat Cards' },
                                    ].map((item) => {
                                        const enabled = dashboardPrefs[item.key as Exclude<DashboardPrefKey, 'visibleStatCards'>]
                                        return (
                                            <button
                                                key={item.key}
                                                onClick={() => toggleSection(item.key as Exclude<DashboardPrefKey, 'visibleStatCards'>)}
                                                className={`rounded-2xl border px-4 py-3 text-left transition-colors ${
                                                    enabled
                                                        ? 'border-brand-500/30 bg-brand-500/10 text-white'
                                                        : 'border-white/10 bg-white/5 text-gray-400 hover:text-white'
                                                }`}
                                            >
                                                <div className="flex items-center justify-between gap-3">
                                                    <span className="font-semibold">{item.label}</span>
                                                    <span className={`text-[10px] font-black uppercase tracking-widest ${enabled ? 'text-brand-300' : 'text-gray-500'}`}>
                                                        {enabled ? 'On' : 'Off'}
                                                    </span>
                                                </div>
                                            </button>
                                        )
                                    })}
                                </div>
                            </div>
                            <div>
                                <p className="text-xs font-black uppercase tracking-widest text-gray-500 mb-3">Stat Cards</p>
                                <div className="flex flex-wrap gap-3">
                                    {statCards.map((card) => {
                                        const enabled = dashboardPrefs.visibleStatCards.includes(card.key)
                                        return (
                                            <button
                                                key={card.key}
                                                onClick={() => toggleStatCard(card.key)}
                                                className={`px-4 py-2.5 rounded-full border text-sm font-semibold transition-colors ${
                                                    enabled
                                                        ? 'border-brand-500/30 bg-brand-500/10 text-white'
                                                        : 'border-white/10 bg-white/5 text-gray-400 hover:text-white'
                                                }`}
                                            >
                                                {card.label}
                                            </button>
                                        )
                                    })}
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* Stats Grid */}
                {dashboardPrefs.showStatsGrid && visibleStatCards.length > 0 && (
                    <div className={`grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 ${dashboardPrefs.compactStats ? 'xl:grid-cols-4' : 'xl:grid-cols-6'} gap-6 mb-12`}>
                        {visibleStatCards.map((stat, i) => (
                            <motion.div
                                key={stat.key}
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: i * 0.05 }}
                                className={`glass-card ${dashboardPrefs.compactStats ? 'p-5' : 'p-6'} flex flex-col items-start hover:glass-card-hover group cursor-default`}
                            >
                                <div className={`${dashboardPrefs.compactStats ? 'p-2.5 mb-4' : 'p-3 mb-6'} rounded-2xl ${stat.bg} ${stat.color} group-hover:scale-110 transition-transform`}>
                                    <stat.icon size={dashboardPrefs.compactStats ? 20 : 24} />
                                </div>
                                <div className={`${dashboardPrefs.compactStats ? 'text-2xl' : 'text-3xl'} font-black mb-1 tabular-nums`}>
                                    {loading ? '...' : (stat.value ?? 0).toLocaleString()}
                                </div>
                                <div className="text-gray-500 text-xs font-bold uppercase tracking-widest">{stat.label}</div>
                                <div className="mt-4 w-full h-1 bg-white/5 rounded-full overflow-hidden">
                                    <motion.div
                                        initial={{ width: 0 }}
                                        animate={{ width: `${Math.min(100, ((stat.value ?? 0) / maxStatValue) * 100)}%` }}
                                        transition={{ duration: 1, delay: 0.5 + i * 0.1 }}
                                        className={`h-full ${stat.color.replace('text', 'bg')}`}
                                    />
                                </div>
                            </motion.div>
                        ))}
                    </div>
                )}

                {/* Main content area */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
                    {/* Activity Feed */}
                    {dashboardPrefs.showActivityFeed && (
                        <div className={`${leftColumnSpan} space-y-6`}>
                            <div className="flex justify-between items-center px-2">
                                <div className="flex items-center gap-3">
                                    <RefreshCw className={`text-brand-500 ${loading ? 'animate-spin' : ''}`} size={20} />
                                    <h2 className="text-2xl font-black tracking-tight">Real-time Stream</h2>
                                </div>
                                <Link href="/logs" className="text-brand-400 text-sm font-bold flex items-center gap-2 hover:text-brand-300 transition-colors group">
                                    View Full Console <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />
                                </Link>
                            </div>

                            {loading ? (
                                <div className="space-y-4">
                                    {/* Correctly-sized skeletons matching actual card height */}
                                    {[1, 2, 3, 4].map((i) => (
                                        <div key={i} className="glass-card p-5 animate-pulse" style={{ minHeight: '96px' }}>
                                            <div className="flex items-center gap-6">
                                                <div className="w-20 h-20 rounded-2xl bg-white/5 shrink-0" />
                                                <div className="flex-1 space-y-2">
                                                    <div className="h-4 bg-white/5 rounded w-2/3" />
                                                    <div className="h-3 bg-white/5 rounded w-1/3" />
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            ) : recentLogs.length === 0 ? (
                                <div className="glass-card p-16 text-center border-dashed border-2 border-white/5 bg-transparent">
                                    <div className="w-20 h-20 bg-white/5 rounded-full flex items-center justify-center mx-auto mb-6">
                                        <Video size={40} className="text-gray-600" />
                                    </div>
                                    <h3 className="text-xl font-bold mb-2 text-white">No active feeds detected</h3>
                                    <p className="text-gray-500 max-w-xs mx-auto mb-6">
                                        Upload a video or open live activities to start receiving vision intelligence data.
                                    </p>
                                    <div className="flex flex-wrap justify-center gap-3">
                                        <Link href="/upload" className="flex items-center gap-2 px-4 py-2 rounded-xl bg-brand-600/20 text-brand-400 text-sm font-semibold hover:bg-brand-600/30 transition-colors border border-brand-500/20">
                                            <Video size={14} /> Upload Video
                                        </Link>
                                        <Link href="/live-activities" className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white/5 text-gray-400 text-sm font-semibold hover:bg-white/10 transition-colors">
                                            <Activity size={14} /> Live Activities
                                        </Link>
                                    </div>
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    {recentLogs.map((log, i) => (
                                        <motion.div
                                            key={log.id}
                                            initial={{ opacity: 0, x: -20 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            transition={{ delay: i * 0.05 }}
                                        >
                                            <Link
                                                href={`/logs/${log.id}`}
                                                className="glass-card p-5 flex items-center gap-6 hover:glass-card-hover group border-l-4 border-l-transparent hover:border-l-brand-500"
                                            >
                                                <div className="relative shrink-0">
                                                    <div className="w-20 h-20 rounded-2xl bg-gray-900 flex items-center justify-center overflow-hidden ring-1 ring-white/10 group-hover:ring-brand-500/50 transition-all shadow-2xl">
                                                        {getStreamImageUrl(log) ? (
                                                            <MediaImage
                                                                sources={[log.visitor_image_url, log.face_image_path]}
                                                                alt={getStreamSubjectLabel(log)}
                                                                className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-500"
                                                                fallback={<Users className="text-gray-700" size={32} />}
                                                            />
                                                        ) : (
                                                            <Users className="text-gray-700" size={32} />
                                                        )}
                                                    </div>
                                                    <div className="absolute -bottom-2 -right-2 bg-gray-950 p-1.5 rounded-lg border border-white/10 shadow-lg">
                                                        <Camera size={12} className="text-brand-400" />
                                                    </div>
                                                </div>
                                                <div className="flex-1 min-w-0">
                                                    <div className="flex justify-between items-start gap-4 mb-2">
                                                        <div>
                                                            <h3 className="font-bold text-lg text-white mb-0.5 group-hover:text-brand-400 transition-colors">
                                                                {getStreamSubjectLabel(log)}
                                                            </h3>
                                                            <div className="flex items-center gap-3">
                                                                <p className="text-sm text-gray-500 flex items-center gap-1.5 font-medium">
                                                                    <Clock size={14} /> {timeAgo(log.timestamp)}
                                                                </p>
                                                                <span className="w-1 h-1 rounded-full bg-gray-700" />
                                                                <p className="text-xs text-brand-500/60 font-bold uppercase tracking-tighter">
                                                                    {getSourceLabel(log, cameras)}
                                                                </p>
                                                            </div>
                                                        </div>
                                                        <ConfidenceBadge status={log.status} confidence={log.confidence} />
                                                    </div>
                                                </div>
                                                <div className="p-2 rounded-lg bg-white/5 text-gray-500 group-hover:text-brand-400 transition-colors opacity-0 group-hover:opacity-100 translate-x-4 group-hover:translate-x-0 transition-all">
                                                    <ArrowRight size={20} />
                                                </div>
                                            </Link>
                                        </motion.div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Right Column */}
                    {hasRightColumn && (
                        <div className="lg:col-span-4 space-y-8">
                            {dashboardPrefs.showQuickActions && (
                                <div>
                                    <h2 className="text-2xl font-black tracking-tight mb-6 px-2">Rapid Deployment</h2>
                                    <div className="grid grid-cols-1 gap-4">
                                        <Link href="/upload" className="glass-card p-6 border-dashed border-2 border-brand-500/20 flex items-center gap-6 group hover:border-brand-500/50 hover:bg-brand-500/5 transition-all">
                                            <div className="w-14 h-14 bg-brand-500/10 rounded-2xl flex items-center justify-center shrink-0 group-hover:scale-110 group-hover:bg-brand-500/20 transition-all">
                                                <Video className="text-brand-500" size={28} />
                                            </div>
                                            <div>
                                                <h3 className="font-bold text-lg mb-1">Inject Feed</h3>
                                                <p className="text-sm text-gray-500 leading-snug">Process raw video for vision intelligence analysis</p>
                                            </div>
                                        </Link>
                                        <Link href="/visitors" className="glass-card p-6 flex items-center gap-5 hover:glass-card-hover group">
                                            <div className="w-12 h-12 bg-blue-500/10 rounded-2xl flex items-center justify-center shrink-0 group-hover:bg-blue-500/20 transition-all">
                                                <Users className="text-blue-400" size={24} />
                                            </div>
                                            <div className="flex-1">
                                                <h3 className="font-bold">Database</h3>
                                                <p className="text-xs text-gray-500">Manage subject profiles</p>
                                            </div>
                                            <ArrowRight size={18} className="text-gray-700 group-hover:text-blue-400 transition-colors" />
                                        </Link>
                                        <Link href="/live-activities" className="glass-card p-6 flex items-center gap-5 hover:glass-card-hover group">
                                            <div className="w-12 h-12 bg-purple-500/10 rounded-2xl flex items-center justify-center shrink-0 group-hover:bg-purple-500/20 transition-all">
                                                <Activity className="text-purple-400" size={24} />
                                            </div>
                                            <div className="flex-1">
                                                <h3 className="font-bold">Live Activities</h3>
                                                <p className="text-xs text-gray-500">Watch real-time detection activity</p>
                                            </div>
                                            <ArrowRight size={18} className="text-gray-700 group-hover:text-purple-400 transition-colors" />
                                        </Link>
                                    </div>
                                </div>
                            )}

                            {dashboardPrefs.showLivenessPanel && (
                                <div className="glass-card p-8 bg-gradient-to-br from-indigo-500/10 via-white/[0.03] to-transparent border border-white/5 relative overflow-hidden">
                                    <div className="absolute -top-10 -right-10 w-28 h-28 rounded-full bg-indigo-500/20 blur-3xl" />
                                    <div className="flex items-start justify-between gap-4 mb-6">
                                        <div>
                                            <p className="text-xs font-black uppercase tracking-[0.3em] text-indigo-300 mb-2">Identity Check</p>
                                            <h3 className="text-lg font-black text-white">Liveness Verification</h3>
                                            <p className="text-sm text-gray-400 mt-2">Use blink, head-turn, and smile challenges for anti-spoofing.</p>
                                        </div>
                                        <div className="w-12 h-12 rounded-2xl bg-indigo-500/10 text-indigo-300 flex items-center justify-center shrink-0">
                                            <Activity size={22} />
                                        </div>
                                    </div>
                                    <div className="space-y-3 mb-6">
                                        {[
                                            { icon: '👁️', name: 'Blink Detection', time: '5-10 seconds' },
                                            { icon: '🔄', name: 'Head Turn Challenge', time: '10-15 seconds' },
                                            { icon: '😊', name: 'Smile Detection', time: '5-10 seconds' },
                                        ].map((challenge) => (
                                            <div key={challenge.name} className="flex items-center gap-4 rounded-2xl border border-white/5 bg-white/[0.03] px-4 py-3">
                                                <div className="text-2xl">{challenge.icon}</div>
                                                <div className="flex-1 min-w-0">
                                                    <div className="font-semibold text-white leading-tight">{challenge.name}</div>
                                                    <div className="text-xs text-gray-500">{challenge.time}</div>
                                                </div>
                                                <div className="text-xs font-black uppercase tracking-widest text-indigo-300">Ready</div>
                                            </div>
                                        ))}
                                    </div>
                                    <Link
                                        href="/liveness"
                                        className="w-full inline-flex items-center justify-center gap-2 rounded-2xl bg-indigo-500 hover:bg-indigo-400 text-white px-5 py-4 font-bold transition-colors shadow-lg shadow-indigo-500/20"
                                    >
                                        Open Liveness Flow <ArrowRight size={18} />
                                    </Link>
                                </div>
                            )}

                            {/* System Health */}
                            {dashboardPrefs.showSystemHealth && (
                                <div className="glass-card p-8 bg-gradient-to-br from-white/[0.03] to-transparent relative overflow-hidden">
                                    <div className="absolute top-0 right-0 w-32 h-32 bg-brand-500/5 blur-[50px] -z-10" />
                                    <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                        <BarChart3 size={18} className="text-brand-400" />
                                        Network Health
                                    </h3>
                                    <div className="space-y-6">
                                        <div>
                                            <div className="flex justify-between text-xs font-bold uppercase tracking-widest text-gray-500 mb-2">
                                                <span>Avg Processing Time</span>
                                                <span className="text-brand-400">{systemHealth ? `${systemHealth.avg_processing_time_ms.toFixed(0)}ms` : '...'}</span>
                                            </div>
                                            <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                                                <motion.div initial={{ width: 0 }} animate={{ width: systemHealth ? `${Math.min(100, (systemHealth.avg_processing_time_ms / 1000) * 100)}%` : '0%' }} className="h-full bg-brand-500 shadow-[0_0_10px_rgba(139,92,246,0.5)]" />
                                            </div>
                                        </div>
                                        <div>
                                            <div className="flex justify-between text-xs font-bold uppercase tracking-widest text-gray-500 mb-2">
                                                <span>Storage Used</span>
                                                <span className="text-green-400">{systemHealth ? `${systemHealth.storage_used_mb.toFixed(1)} MB` : '...'}</span>
                                            </div>
                                            <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                                                <motion.div initial={{ width: 0 }} animate={{ width: systemHealth ? `${Math.min(100, (systemHealth.storage_used_mb / 1024) * 100)}%` : '0%' }} className="h-full bg-green-500" />
                                            </div>
                                        </div>
                                        <div className="pt-4 border-t border-white/5 flex items-center justify-between text-xs">
                                            <span className="text-gray-500 font-medium">Processed today: {systemHealth?.total_processed_today ?? '...'}</span>
                                            <span className="flex items-center gap-1.5 font-bold" style={{ color: systemHealth?.ai_service_status === 'healthy' ? '#4ade80' : '#f87171' }}>
                                                <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ backgroundColor: systemHealth?.ai_service_status === 'healthy' ? '#4ade80' : '#f87171' }} />
                                                {systemHealth?.ai_service_status === 'healthy' ? 'Optimal' : systemHealth?.ai_service_status || 'Unknown'}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {!dashboardPrefs.showActivityFeed && !hasRightColumn && (
                    <div className="glass-card p-12 mt-8 text-center">
                        <div className="w-16 h-16 rounded-full bg-brand-500/10 text-brand-400 flex items-center justify-center mx-auto mb-4">
                            <MonitorUp size={28} />
                        </div>
                        <h3 className="text-xl font-black text-white mb-2">Dashboard Widgets Hidden</h3>
                        <p className="text-gray-500 max-w-md mx-auto">Use the customization panel above to re-enable widgets.</p>
                    </div>
                )}
            </main>
        </div>
    )
}

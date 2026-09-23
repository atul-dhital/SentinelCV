'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { BarChart3, TrendingUp, Users, Eye, Camera, ShieldCheck, AlertCircle, Activity, Target, Clock, Cpu, Smile, Map, Navigation } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { logService, DashboardStats, analyticsService, EmotionAnalyticsSummary, VisitorFlowAnalytics } from '@/services/api'
import {
    BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
    PieChart, Pie, Cell, Legend, AreaChart, Area, LineChart, Line
} from 'recharts'

const COLORS = ['#8b5cf6', '#6366f1', '#3b82f6', '#14b8a6', '#f59e0b', '#ef4444', '#ec4899', '#10b981']
const EMOTION_ORDER = ['happy', 'surprised', 'neutral', 'sad', 'angry', 'fearful', 'disgusted']

// Standardized chart empty state
function ChartEmptyState({
    message,
    hint,
    cta,
}: {
    message: string
    hint?: string
    cta?: { label: string; href: string }
}) {
    return (
        <div className="h-[280px] flex flex-col items-center justify-center text-gray-500 gap-3 px-6 text-center">
            <BarChart3 size={32} className="opacity-30" aria-hidden="true" />
            <p className="text-sm text-gray-400">{message}</p>
            <p className="text-xs text-gray-600 max-w-[280px] leading-relaxed">
                {hint ?? 'Data will appear here once detections are processed.'}
            </p>
            {cta && (
                <Link
                    href={cta.href}
                    className="text-xs text-brand-400 hover:text-brand-300 font-medium transition-colors underline-offset-2 hover:underline"
                >
                    {cta.label} →
                </Link>
            )}
        </div>
    )
}
const EMOTION_COLORS: Record<string, string> = {
    happy: '#10b981',
    surprised: '#f59e0b',
    neutral: '#6366f1',
    sad: '#3b82f6',
    angry: '#ef4444',
    fearful: '#8b5cf6',
    disgusted: '#14b8a6',
}

const heatColor = (value: number): string => {
    const clamped = Math.max(0, Math.min(1, value))
    const hue = 220 - clamped * 220
    const lightness = 22 + clamped * 40
    return `hsl(${hue}, 80%, ${lightness}%)`
}

interface AccuracyDashboard {
    overall_accuracy: number
    daily_accuracy: { date: string; total: number; identified: number; accuracy: number }[]
    confidence_distribution: Record<string, number>
    top_misidentified: { log_id: string; confidence: number; visitor_id: string | null }[]
}

interface VisitorPatterns {
    peak_hours: { hour: number; count: number }[]
    daily_trends: { date: string; total: number; identified: number; unidentified: number }[]
    frequent_visitors: { visitor_id: string; name: string; count: number }[]
    avg_daily_visitors: number
}

interface SystemHealth {
    ai_service_status: string
    avg_processing_time_ms: number
    total_processed_today: number
    error_rate: number
    storage_used_mb: number
    database_size_mb: number
}

interface UserSession {
    id: string
    visitor_id: string | null
    session_start: string
    session_end: string | null
    current_position: Record<string, any>
    path: Record<string, any>[]
    status: string
    last_updated: string
}

interface RealtimeTracking {
    active_sessions: UserSession[]
    total_active: number
    generated_at: string
}

export default function AnalyticsPage() {
    const router = useRouter()
    const [stats, setStats] = useState<DashboardStats | null>(null)
    const [accuracy, setAccuracy] = useState<AccuracyDashboard | null>(null)
    const [patterns, setPatterns] = useState<VisitorPatterns | null>(null)
    const [health, setHealth] = useState<SystemHealth | null>(null)
    const [emotionSummary, setEmotionSummary] = useState<EmotionAnalyticsSummary | null>(null)
    const [visitorFlow, setVisitorFlow] = useState<VisitorFlowAnalytics | null>(null)
    const [realtimeTracking, setRealtimeTracking] = useState<RealtimeTracking | null>(null)
    const [loading, setLoading] = useState(true)
    const [activeTab, setActiveTab] = useState<'overview' | 'accuracy' | 'patterns' | 'health' | 'behavior' | 'realtime'>('overview')

    useEffect(() => {
        fetchData()
    }, [])

    const fetchData = async () => {
        try {
            const [statsRes, accRes, patRes, healthRes, emotionRes, flowRes, realtimeRes] = await Promise.allSettled([
                logService.getDashboardStats(),
                analyticsService.getAccuracyDashboard(),
                analyticsService.getVisitorPatterns(),
                analyticsService.getSystemHealth(),
                analyticsService.getEmotionAnalytics(),
                analyticsService.getVisitorFlow(),
                analyticsService.getRealtimeTracking(),
            ])
            if (statsRes.status === 'fulfilled') setStats(statsRes.value.data)
            if (accRes.status === 'fulfilled') setAccuracy(accRes.value.data)
            if (patRes.status === 'fulfilled') setPatterns(patRes.value.data)
            if (healthRes.status === 'fulfilled') setHealth(healthRes.value.data)
            if (emotionRes.status === 'fulfilled') setEmotionSummary(emotionRes.value.data)
            if (flowRes.status === 'fulfilled') setVisitorFlow(flowRes.value.data)
            if (realtimeRes.status === 'fulfilled') setRealtimeTracking(realtimeRes.value.data)
        } catch (err: any) {
            if (err.response?.status === 401) {
                window.location.href = '/login'
                return
            }
            console.error('Failed to fetch analytics data:', err)
        } finally {
            setLoading(false)
        }
    }

    if (loading) {
        return (
            <div className="min-h-screen">
                <Navbar />
                <main className="pt-24 pb-20 px-6 container mx-auto">
                    <div className="animate-pulse space-y-6">
                        <div className="h-8 bg-gray-800 rounded w-48"></div>
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                            {[1, 2, 3].map((i) => (
                                <div key={i} className="h-32 bg-gray-800 rounded-xl" />
                            ))}
                        </div>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                            {[1, 2].map((i) => (
                                <div key={i} className="h-80 bg-gray-800 rounded-xl" />
                            ))}
                        </div>
                    </div>
                </main>
            </div>
        )
    }

    const identificationRate = stats && stats.total_events > 0
        ? ((stats.identified_count / stats.total_events) * 100).toFixed(1)
        : '0.0'

    const emotionDistribution = EMOTION_ORDER.map((emotion) => ({
        emotion,
        value: Number(((emotionSummary?.emotion_distribution?.[emotion] ?? 0) * 100).toFixed(2)),
        count: emotionSummary?.emotion_counts?.[emotion] ?? 0,
    }))

    const emotionTimeline = emotionSummary?.timeline ?? []
    const heatmapGrid = visitorFlow?.heatmap?.normalized_grid ?? []
    const heatmapRaw = visitorFlow?.heatmap?.raw_grid ?? []
    const heatmapPeak = visitorFlow?.heatmap?.peak_cell_events ?? 0

    const tabs = [
        { key: 'overview' as const, label: 'Overview', icon: BarChart3 },
        { key: 'accuracy' as const, label: 'Accuracy', icon: Target },
        { key: 'patterns' as const, label: 'Visitor Patterns', icon: Users },
        { key: 'behavior' as const, label: 'Emotion & Flow', icon: Smile },
        { key: 'realtime' as const, label: 'Real-Time Tracking', icon: Navigation },
        { key: 'health' as const, label: 'System Health', icon: Activity },
    ]

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-20 px-6 container mx-auto">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                >
                    <div className="mb-10">
                        <h1 className="text-4xl font-extrabold mb-3 bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
                            Analytics
                        </h1>
                        <p className="text-gray-400 text-lg">Insights and metrics for your visitor tracking system.</p>
                    </div>

                    {/* Tabs */}
                    <div className="flex gap-2 mb-8 overflow-x-auto pb-2">
                        {tabs.map(tab => (
                            <button
                                key={tab.key}
                                onClick={() => setActiveTab(tab.key)}
                                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${activeTab === tab.key
                                    ? 'bg-brand-600/20 text-brand-500'
                                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                                    }`}
                            >
                                <tab.icon size={16} />
                                {tab.label}
                            </button>
                        ))}
                    </div>

                    {/* Overview Tab */}
                    {activeTab === 'overview' && stats && (
                        <>
                            {/* KPI Cards */}
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                                {[
                                    { label: 'Total Events', value: stats.total_events.toLocaleString(), icon: Eye, color: 'text-brand-500', bg: 'bg-brand-500/10' },
                                    { label: 'Identification Rate', value: `${identificationRate}%`, icon: ShieldCheck, color: 'text-green-400', bg: 'bg-green-400/10' },
                                    { label: 'Total Visitors', value: stats.total_visitors.toLocaleString(), icon: Users, color: 'text-blue-400', bg: 'bg-blue-400/10' },
                                    { label: 'Active Streams', value: stats.cameras_online.toString(), icon: Camera, color: 'text-purple-400', bg: 'bg-purple-400/10' },
                                ].map((card, i) => (
                                    <motion.div
                                        key={card.label}
                                        initial={{ opacity: 0, y: 20 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        transition={{ delay: i * 0.05 }}
                                        className="glass-card p-6"
                                    >
                                        <div className="flex items-center gap-3 mb-3">
                                            <div className={`p-2 rounded-lg ${card.bg}`}>
                                                <card.icon size={20} className={card.color} />
                                            </div>
                                            <span className="text-sm text-gray-400">{card.label}</span>
                                        </div>
                                        <p className="text-3xl font-extrabold">{card.value}</p>
                                    </motion.div>
                                ))}
                            </div>

                            {/* Charts Row */}
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
                                {/* Identification Pie Chart */}
                                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="glass-card p-6">
                                    <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                        <TrendingUp size={20} className="text-brand-500" />
                                        Identification Breakdown
                                    </h3>
                                    {stats.total_events > 0 ? (
                                        <ResponsiveContainer width="100%" height={280}>
                                            <PieChart>
                                                <Pie
                                                    data={[
                                                        { name: 'Identified', value: stats.identified_count, color: '#10b981' },
                                                        { name: 'Unidentified', value: stats.unidentified_count, color: '#ef4444' },
                                                    ]}
                                                    cx="50%" cy="50%" innerRadius={60} outerRadius={100} paddingAngle={5} dataKey="value"
                                                    label={({ name, percent }: { name?: string; percent?: number }) => `${name ?? ''} ${((percent ?? 0) * 100).toFixed(0)}%`}
                                                >
                                                    <Cell fill="#10b981" />
                                                    <Cell fill="#ef4444" />
                                                </Pie>
                                                <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', color: '#fff' }} />
                                                <Legend />
                                            </PieChart>
                                        </ResponsiveContainer>
                                    ) : (
                                        <ChartEmptyState
                                            message="No detections yet."
                                            hint="Connect a camera or upload a video to see identification accuracy."
                                            cta={{ label: 'Connect a camera', href: '/live-activities' }}
                                        />
                                    )}
                                </motion.div>

                                {/* Overview Bar Chart */}
                                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="glass-card p-6">
                                    <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                        <BarChart3 size={20} className="text-brand-500" />
                                        Event Overview
                                    </h3>
                                    <ResponsiveContainer width="100%" height={280}>
                                        <BarChart data={[
                                            { name: 'Total Events', value: stats.total_events, fill: '#8b5cf6' },
                                            { name: 'Identified', value: stats.identified_count, fill: '#10b981' },
                                            { name: 'Unidentified', value: stats.unidentified_count, fill: '#ef4444' },
                                            { name: 'Pending', value: stats.pending_review, fill: '#f59e0b' },
                                        ]} barSize={48}>
                                            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                            <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 12 }} axisLine={{ stroke: '#4b5563' }} />
                                            <YAxis tick={{ fill: '#9ca3af', fontSize: 12 }} axisLine={{ stroke: '#4b5563' }} />
                                            <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', color: '#fff' }} />
                                            <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                                                {[{ fill: '#8b5cf6' }, { fill: '#10b981' }, { fill: '#ef4444' }, { fill: '#f59e0b' }].map((entry, index) => (
                                                    <Cell key={`cell-${index}`} fill={entry.fill} />
                                                ))}
                                            </Bar>
                                        </BarChart>
                                    </ResponsiveContainer>
                                </motion.div>
                            </div>

                            {/* Summary Cards */}
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.4 }} className="glass-card p-6">
                                    <h3 className="font-bold mb-4 text-gray-300">Detection Summary</h3>
                                    <div className="space-y-3">
                                        <div className="flex justify-between items-center">
                                            <span className="text-gray-400">Total Detections</span>
                                            <span className="font-semibold">{stats.total_events.toLocaleString()}</span>
                                        </div>
                                        <div className="flex justify-between items-center">
                                            <span className="text-green-400">Successfully Identified</span>
                                            <span className="font-semibold text-green-400">{stats.identified_count.toLocaleString()}</span>
                                        </div>
                                        <div className="flex justify-between items-center">
                                            <span className="text-red-400">Unidentified</span>
                                            <span className="font-semibold text-red-400">{stats.unidentified_count.toLocaleString()}</span>
                                        </div>
                                        <div className="border-t border-gray-700 pt-3 flex justify-between items-center">
                                            <span className="text-yellow-400">Pending Review</span>
                                            <span className="font-semibold text-yellow-400">{stats.pending_review}</span>
                                        </div>
                                    </div>
                                </motion.div>

                                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.45 }} className="glass-card p-6">
                                    <h3 className="font-bold mb-4 text-gray-300">System Health</h3>
                                    <div className="space-y-3">
                                        <div className="flex justify-between items-center">
                                            <span className="text-gray-400">Active Streams</span>
                                            <span className="font-semibold text-green-400">{stats.cameras_online}</span>
                                        </div>
                                        <div className="flex justify-between items-center">
                                            <span className="text-gray-400">Registered Visitors</span>
                                            <span className="font-semibold">{stats.total_visitors.toLocaleString()}</span>
                                        </div>
                                        <div className="flex justify-between items-center">
                                            <span className="text-gray-400">Identification Rate</span>
                                            <span className={`font-semibold ${parseFloat(identificationRate) >= 70 ? 'text-green-400' : parseFloat(identificationRate) >= 40 ? 'text-yellow-400' : 'text-red-400'}`}>
                                                {identificationRate}%
                                            </span>
                                        </div>
                                    </div>
                                </motion.div>

                                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }} className="glass-card p-6">
                                    <h3 className="font-bold mb-4 text-gray-300">Quick Actions</h3>
                                    <div className="space-y-2">
                                        <button onClick={() => router.push('/logs?status=unidentified')} className="w-full bg-yellow-500/10 hover:bg-yellow-500/20 text-yellow-400 px-4 py-3 rounded-lg text-sm font-medium transition-colors text-left flex items-center gap-2">
                                            <AlertCircle size={16} />
                                            Review {stats.pending_review} Pending Logs
                                        </button>
                                        <button onClick={() => router.push('/visitors')} className="w-full bg-brand-500/10 hover:bg-brand-500/20 text-brand-400 px-4 py-3 rounded-lg text-sm font-medium transition-colors text-left flex items-center gap-2">
                                            <Users size={16} />
                                            View All Visitors
                                        </button>
                                        <button onClick={() => router.push('/upload')} className="w-full bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 px-4 py-3 rounded-lg text-sm font-medium transition-colors text-left flex items-center gap-2">
                                            <Camera size={16} />
                                            Upload New Video
                                        </button>
                                    </div>
                                </motion.div>
                            </div>
                        </>
                    )}

                    {activeTab === 'overview' && !stats && (
                        <div className="glass-card p-12 text-center">
                            <AlertCircle size={48} className="text-red-400 mx-auto mb-4" />
                            <h2 className="text-2xl font-bold mb-2">Failed to Load Analytics</h2>
                            <p className="text-gray-400">Could not fetch analytics data. Please try again later.</p>
                        </div>
                    )}

                    {/* Accuracy Tab */}
                    {activeTab === 'accuracy' && (
                        <>
                            {accuracy ? (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                                        {[
                                            { label: 'Overall Accuracy', value: `${(accuracy.overall_accuracy * 100).toFixed(1)}%`, icon: Target, color: 'text-green-400', bg: 'bg-green-400/10' },
                                            { label: 'Daily Data Points', value: accuracy.daily_accuracy.length.toString(), icon: ShieldCheck, color: 'text-brand-500', bg: 'bg-brand-500/10' },
                                            { label: 'Misidentified', value: accuracy.top_misidentified.length.toString(), icon: AlertCircle, color: 'text-red-400', bg: 'bg-red-400/10' },
                                            { label: 'Confidence Ranges', value: Object.keys(accuracy.confidence_distribution).length.toString(), icon: Eye, color: 'text-blue-400', bg: 'bg-blue-400/10' },
                                        ].map((card, i) => (
                                            <motion.div key={card.label} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="glass-card p-6">
                                                <div className="flex items-center gap-3 mb-3">
                                                    <div className={`p-2 rounded-lg ${card.bg}`}><card.icon size={20} className={card.color} /></div>
                                                    <span className="text-sm text-gray-400">{card.label}</span>
                                                </div>
                                                <p className="text-3xl font-extrabold">{card.value}</p>
                                            </motion.div>
                                        ))}
                                    </div>

                                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
                                        {/* Accuracy Trend */}
                                        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="glass-card p-6">
                                            <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                                <TrendingUp size={20} className="text-brand-500" /> Accuracy Trend
                                            </h3>
                                            {accuracy.daily_accuracy && accuracy.daily_accuracy.length > 0 ? (
                                                <ResponsiveContainer width="100%" height={280}>
                                                    <LineChart data={accuracy.daily_accuracy.map(d => ({ ...d, accuracy_pct: +(d.accuracy * 100).toFixed(1) }))}>
                                                        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                                        <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 12 }} />
                                                        <YAxis tick={{ fill: '#9ca3af', fontSize: 12 }} domain={[0, 100]} />
                                                        <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', color: '#fff' }} />
                                                        <Line type="monotone" dataKey="accuracy_pct" name="Accuracy %" stroke="#8b5cf6" strokeWidth={2} dot={{ fill: '#8b5cf6' }} />
                                                    </LineChart>
                                                </ResponsiveContainer>
                                            ) : (
                                                <div className="h-[280px] flex items-center justify-center text-gray-500">
                                                    <ChartEmptyState
                                                        message="Not enough data for trends yet."
                                                        hint="Trends appear after ~24 hours of detections. Keep cameras running or enroll visitors to get started."
                                                        cta={{ label: 'Enroll a visitor', href: '/visitors' }}
                                                    />
                                                </div>
                                            )}
                                        </motion.div>

                                        {/* Accuracy by Camera */}
                                        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="glass-card p-6">
                                            <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                                <BarChart3 size={20} className="text-brand-500" /> Confidence Distribution
                                            </h3>
                                            {accuracy.confidence_distribution && Object.keys(accuracy.confidence_distribution).length > 0 ? (
                                                <ResponsiveContainer width="100%" height={280}>
                                                    <BarChart data={Object.entries(accuracy.confidence_distribution).map(([range, count]) => ({ range, count }))} barSize={36}>
                                                        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                                        <XAxis dataKey="range" tick={{ fill: '#9ca3af', fontSize: 11 }} label={{ value: 'Confidence Range', position: 'insideBottom', offset: -2, fill: '#6b7280', fontSize: 11 }} />
                                                        <YAxis tick={{ fill: '#9ca3af', fontSize: 12 }} label={{ value: 'Detection Count', angle: -90, position: 'insideLeft', fill: '#6b7280', fontSize: 11 }} />
                                                        <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', color: '#fff' }} />
                                                        <Legend formatter={() => 'Detections per confidence range'} />
                                                        <Bar dataKey="count" name="Detections" fill="#8b5cf6" radius={[6, 6, 0, 0]} />
                                                    </BarChart>
                                                </ResponsiveContainer>
                                            ) : (
                                                <div className="h-[280px] flex items-center justify-center text-gray-500">
                                                    <ChartEmptyState
                                                        message="No confidence data yet."
                                                        hint="Confidence distribution populates after your first identified detection."
                                                    />
                                                </div>
                                            )}
                                        </motion.div>
                                    </div>
                                </>
                            ) : (
                                <div className="glass-card p-12 text-center">
                                    <Target size={48} className="text-gray-600 mx-auto mb-4" />
                                    <h2 className="text-xl font-bold mb-2">Accuracy Data Not Available</h2>
                                    <p className="text-gray-400">Process some videos to start seeing accuracy metrics.</p>
                                </div>
                            )}
                        </>
                    )}

                    {/* Visitor Patterns Tab */}
                    {activeTab === 'patterns' && (
                        <>
                            {patterns ? (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                                        {[
                                            { label: 'Avg Daily Visitors', value: patterns.avg_daily_visitors.toFixed(1), icon: Users, color: 'text-blue-400', bg: 'bg-blue-400/10' },
                                            { label: 'Peak Hours Tracked', value: patterns.peak_hours.length.toString(), icon: TrendingUp, color: 'text-green-400', bg: 'bg-green-400/10' },
                                            { label: 'Days Tracked', value: patterns.daily_trends.length.toString(), icon: Clock, color: 'text-yellow-400', bg: 'bg-yellow-400/10' },
                                            { label: 'Frequent Visitors', value: patterns.frequent_visitors.length.toString(), icon: Eye, color: 'text-purple-400', bg: 'bg-purple-400/10' },
                                        ].map((card, i) => (
                                            <motion.div key={card.label} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="glass-card p-6">
                                                <div className="flex items-center gap-3 mb-3">
                                                    <div className={`p-2 rounded-lg ${card.bg}`}><card.icon size={20} className={card.color} /></div>
                                                    <span className="text-sm text-gray-400">{card.label}</span>
                                                </div>
                                                <p className="text-2xl font-extrabold">{card.value}</p>
                                            </motion.div>
                                        ))}
                                    </div>

                                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                        {/* Peak Hours */}
                                        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="glass-card p-6">
                                            <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                                <Clock size={20} className="text-brand-500" /> Peak Hours
                                            </h3>
                                            {patterns.peak_hours && patterns.peak_hours.length > 0 ? (
                                                <ResponsiveContainer width="100%" height={280}>
                                                    <AreaChart data={patterns.peak_hours}>
                                                        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                                        <XAxis dataKey="hour" tick={{ fill: '#9ca3af', fontSize: 12 }} tickFormatter={(h) => `${h}:00`} />
                                                        <YAxis tick={{ fill: '#9ca3af', fontSize: 12 }} />
                                                        <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', color: '#fff' }} labelFormatter={(h) => `${h}:00`} />
                                                        <Area type="monotone" dataKey="count" stroke="#8b5cf6" fill="#8b5cf6" fillOpacity={0.2} />
                                                    </AreaChart>
                                                </ResponsiveContainer>
                                            ) : (
                                                <div className="h-[280px] flex items-center justify-center text-gray-500">
                                                    <ChartEmptyState
                                                        message="Not enough data for peak hour analysis."
                                                        hint="Peak-hour patterns emerge after several days of continuous detections."
                                                    />
                                                </div>
                                            )}
                                        </motion.div>

                                        {/* Daily Distribution */}
                                        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="glass-card p-6">
                                            <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                                <BarChart3 size={20} className="text-brand-500" /> Daily Trends
                                            </h3>
                                            {patterns.daily_trends && patterns.daily_trends.length > 0 ? (
                                                <ResponsiveContainer width="100%" height={280}>
                                                    <BarChart data={patterns.daily_trends} barSize={36}>
                                                        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                                        <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 12 }} />
                                                        <YAxis tick={{ fill: '#9ca3af', fontSize: 12 }} />
                                                        <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', color: '#fff' }} />
                                                        <Bar dataKey="total" fill="#14b8a6" radius={[6, 6, 0, 0]} name="Total" />
                                                    </BarChart>
                                                </ResponsiveContainer>
                                            ) : (
                                                <div className="h-[280px] flex items-center justify-center text-gray-500">
                                                    <ChartEmptyState
                                                        message="Not enough data for daily analysis."
                                                        hint="We need at least a few days of detections before daily patterns become meaningful."
                                                    />
                                                </div>
                                            )}
                                        </motion.div>
                                    </div>
                                </>
                            ) : (
                                <div className="glass-card p-12 text-center">
                                    <Users size={48} className="text-gray-600 mx-auto mb-4" />
                                    <h2 className="text-xl font-bold mb-2">Visitor Pattern Data Not Available</h2>
                                    <p className="text-gray-400">Process some videos to start seeing visitor pattern insights.</p>
                                </div>
                            )}
                        </>
                    )}

                    {/* Emotion & Flow Tab */}
                    {activeTab === 'behavior' && (
                        <>
                            {emotionSummary ? (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                                        {[
                                            { label: 'Emotion Events', value: emotionSummary.total_events.toLocaleString(), icon: Smile, color: 'text-pink-400', bg: 'bg-pink-400/10' },
                                            { label: 'Dominant Emotion', value: emotionSummary.dominant_emotion, icon: TrendingUp, color: 'text-purple-400', bg: 'bg-purple-400/10', capitalize: true },
                                            { label: 'Avg Valence', value: emotionSummary.avg_valence.toFixed(2), icon: Activity, color: 'text-green-400', bg: 'bg-green-400/10' },
                                            { label: 'Avg Arousal', value: emotionSummary.avg_arousal.toFixed(2), icon: Target, color: 'text-amber-400', bg: 'bg-amber-400/10' },
                                        ].map((card, i) => (
                                            <motion.div key={card.label} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="glass-card p-6">
                                                <div className="flex items-center gap-3 mb-3">
                                                    <div className={`p-2 rounded-lg ${card.bg}`}><card.icon size={20} className={card.color} /></div>
                                                    <span className="text-sm text-gray-400">{card.label}</span>
                                                </div>
                                                <p className={`text-2xl font-extrabold ${card.capitalize ? 'capitalize' : ''}`}>{card.value}</p>
                                            </motion.div>
                                        ))}
                                    </div>

                                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
                                        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="glass-card p-6">
                                            <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                                <Smile size={20} className="text-brand-500" /> Emotion Distribution
                                            </h3>
                                            {emotionSummary.total_events > 0 ? (
                                                <ResponsiveContainer width="100%" height={280}>
                                                    <BarChart data={emotionDistribution} barSize={32}>
                                                        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                                        <XAxis dataKey="emotion" tick={{ fill: '#9ca3af', fontSize: 12 }} />
                                                        <YAxis tick={{ fill: '#9ca3af', fontSize: 12 }} domain={[0, 100]} />
                                                        <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', color: '#fff' }} formatter={(value) => value != null ? `${Number(value).toFixed(1)}%` : ''} />
                                                        <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                                                            {emotionDistribution.map((entry) => (
                                                                <Cell key={entry.emotion} fill={EMOTION_COLORS[entry.emotion] || '#8b5cf6'} />
                                                            ))}
                                                        </Bar>
                                                    </BarChart>
                                                </ResponsiveContainer>
                                            ) : (
                                                <div className="h-[280px] flex items-center justify-center text-gray-500">
                                                    <p>No emotion detections available yet.</p>
                                                </div>
                                            )}
                                        </motion.div>

                                        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="glass-card p-6">
                                            <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                                <TrendingUp size={20} className="text-brand-500" /> Valence & Arousal Trend
                                            </h3>
                                            {emotionTimeline.length > 0 ? (
                                                <ResponsiveContainer width="100%" height={280}>
                                                    <LineChart data={emotionTimeline}>
                                                        <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                                        <XAxis dataKey="date" tick={{ fill: '#9ca3af', fontSize: 12 }} />
                                                        <YAxis tick={{ fill: '#9ca3af', fontSize: 12 }} domain={[-1, 1]} />
                                                        <Tooltip contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', color: '#fff' }} />
                                                        <Line type="monotone" dataKey="avg_valence" stroke="#10b981" strokeWidth={2} dot={{ fill: '#10b981' }} name="Valence" />
                                                        <Line type="monotone" dataKey="avg_arousal" stroke="#f59e0b" strokeWidth={2} dot={{ fill: '#f59e0b' }} name="Arousal" />
                                                    </LineChart>
                                                </ResponsiveContainer>
                                            ) : (
                                                <div className="h-[280px] flex items-center justify-center text-gray-500">
                                                    <p>No emotion trends available yet.</p>
                                                </div>
                                            )}
                                        </motion.div>
                                    </div>
                                </>
                            ) : (
                                <div className="glass-card p-12 text-center mb-8">
                                    <Smile size={48} className="text-gray-600 mx-auto mb-4" />
                                    <h2 className="text-xl font-bold mb-2">Emotion Analytics Not Available</h2>
                                    <p className="text-gray-400">Run emotion detection to populate analytics insights.</p>
                                </div>
                            )}

                            {visitorFlow ? (
                                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                                    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="glass-card p-6 lg:col-span-2">
                                        <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                            <Map size={20} className="text-brand-500" /> Movement Heatmap
                                        </h3>
                                        {heatmapGrid.length > 0 ? (
                                            <div className="space-y-4">
                                                <div className="grid grid-cols-10 gap-1">
                                                    {heatmapGrid.map((row, rowIndex) =>
                                                        row.map((value, colIndex) => {
                                                            const rawValue = heatmapRaw[rowIndex]?.[colIndex] ?? 0
                                                            return (
                                                                <div
                                                                    key={`${rowIndex}-${colIndex}`}
                                                                    className="w-full rounded-sm border border-white/5"
                                                                    style={{ backgroundColor: heatColor(value), aspectRatio: '1 / 1' }}
                                                                    title={`Cell ${rowIndex + 1},${colIndex + 1}: ${rawValue} events`}
                                                                />
                                                            )
                                                        })
                                                    )}
                                                </div>
                                                <div className="flex items-center justify-between text-xs text-gray-400">
                                                    <span>Low density</span>
                                                    <span>Peak cell events: {heatmapPeak}</span>
                                                    <span>High density</span>
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="h-[220px] flex items-center justify-center text-gray-500">
                                                <ChartEmptyState
                                                    message="No movement data yet."
                                                    hint="Heatmaps render once cameras are actively tracking movement across frames."
                                                    cta={{ label: 'Set up cameras', href: '/live-activities' }}
                                                />
                                            </div>
                                        )}
                                    </motion.div>

                                    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="glass-card p-6">
                                        <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                            <Activity size={20} className="text-brand-500" /> Flow Summary
                                        </h3>
                                        <div className="space-y-3 text-sm text-gray-400">
                                            <div className="flex justify-between"><span>Total events</span><span className="text-gray-200">{visitorFlow.totals.total_events.toLocaleString()}</span></div>
                                            <div className="flex justify-between"><span>Unique visitors</span><span className="text-gray-200">{visitorFlow.totals.unique_visitors.toLocaleString()}</span></div>
                                            <div className="flex justify-between"><span>Identified rate</span><span className="text-gray-200">{(visitorFlow.totals.identified_rate * 100).toFixed(1)}%</span></div>
                                            <div className="flex justify-between"><span>Median dwell</span><span className="text-gray-200">{visitorFlow.dwell_time.median_seconds.toFixed(0)}s</span></div>
                                            <div className="flex justify-between"><span>Avg dwell</span><span className="text-gray-200">{visitorFlow.dwell_time.average_seconds.toFixed(0)}s</span></div>
                                            <div className="flex justify-between"><span>Peak camera</span><span className="text-gray-200">{visitorFlow.peak_camera.camera_name || 'Unknown'}</span></div>
                                            <div className="flex justify-between"><span>Peak events</span><span className="text-gray-200">{visitorFlow.peak_camera.events}</span></div>
                                        </div>
                                        {visitorFlow.camera_density.length > 0 && (
                                            <div className="mt-6">
                                                <p className="text-xs text-gray-500 mb-2">Top cameras</p>
                                                <div className="space-y-2">
                                                    {visitorFlow.camera_density.slice(0, 3).map((camera) => (
                                                        <div key={camera.camera_id} className="flex justify-between text-xs text-gray-400">
                                                            <span>{camera.camera_name}</span>
                                                            <span>{camera.events} events</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </motion.div>
                                </div>
                            ) : (
                                <div className="glass-card p-12 text-center">
                                    <Map size={48} className="text-gray-600 mx-auto mb-4" />
                                    <h2 className="text-xl font-bold mb-2">Visitor Flow Not Available</h2>
                                    <p className="text-gray-400">Movement heatmaps will appear once detection logs are available.</p>
                                </div>
                            )}
                        </>
                    )}

                    {/* Real-Time Tracking Tab */}
                    {activeTab === 'realtime' && (
                        <>
                            {realtimeTracking ? (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                                        {[
                                            { label: 'Active Sessions', value: realtimeTracking.total_active.toString(), icon: Users, color: 'text-green-400', bg: 'bg-green-400/10' },
                                            { label: 'Tracked Visitors', value: new Set(realtimeTracking.active_sessions.map(s => s.visitor_id).filter(Boolean)).size.toString(), icon: Eye, color: 'text-blue-400', bg: 'bg-blue-400/10' },
                                            { label: 'Cameras Active', value: new Set(realtimeTracking.active_sessions.map(s => s.current_position?.camera_id).filter(Boolean)).size.toString(), icon: Camera, color: 'text-purple-400', bg: 'bg-purple-400/10' },
                                            { label: 'Last Updated', value: new Date(realtimeTracking.generated_at).toLocaleTimeString(), icon: Clock, color: 'text-yellow-400', bg: 'bg-yellow-400/10' },
                                        ].map((card, i) => (
                                            <motion.div key={card.label} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="glass-card p-6">
                                                <div className="flex items-center gap-3 mb-3">
                                                    <div className={`p-2 rounded-lg ${card.bg}`}><card.icon size={20} className={card.color} /></div>
                                                    <span className="text-sm text-gray-400">{card.label}</span>
                                                </div>
                                                <p className="text-2xl font-extrabold">{card.value}</p>
                                            </motion.div>
                                        ))}
                                    </div>

                                    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="glass-card p-6">
                                        <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
                                            <Navigation size={20} className="text-brand-500" /> Active User Sessions
                                        </h3>
                                        {realtimeTracking.active_sessions.length > 0 ? (
                                            <div className="space-y-4">
                                                {realtimeTracking.active_sessions.map((session) => (
                                                    <div key={session.id} className="border border-gray-700 rounded-lg p-4">
                                                        <div className="flex justify-between items-start mb-2">
                                                            <span className="font-medium">Session {session.id.slice(-8)}</span>
                                                            <span className={`px-2 py-1 rounded text-xs ${session.status === 'active' ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'}`}>
                                                                {session.status}
                                                            </span>
                                                        </div>
                                                        <div className="text-sm text-gray-400 space-y-1">
                                                            <div>Visitor: {session.visitor_id ? session.visitor_id.slice(-8) : 'Unknown'}</div>
                                                            <div>Camera: {session.current_position?.camera_id || 'N/A'}</div>
                                                            <div>Position: ({session.current_position?.x?.toFixed(2) || 'N/A'}, {session.current_position?.y?.toFixed(2) || 'N/A'})</div>
                                                            <div>Started: {new Date(session.session_start).toLocaleString()}</div>
                                                            <div>Last Updated: {new Date(session.last_updated).toLocaleString()}</div>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        ) : (
                                            <div className="text-center py-8 text-gray-500">
                                                <Navigation size={32} className="mx-auto mb-2 opacity-30" />
                                                <p>No active sessions currently.</p>
                                            </div>
                                        )}
                                    </motion.div>
                                </>
                            ) : (
                                <div className="glass-card p-12 text-center">
                                    <Navigation size={48} className="text-gray-600 mx-auto mb-4" />
                                    <h2 className="text-xl font-bold mb-2">Real-Time Tracking Not Available</h2>
                                    <p className="text-gray-400">No active user sessions to display.</p>
                                </div>
                            )}
                        </>
                    )}

                    {/* System Health Tab */}
                    {activeTab === 'health' && (
                        <>
                            {health ? (
                                <>
                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
                                        {[
                                            { label: 'AI Service', value: health.ai_service_status === 'online' ? 'Online' : 'Offline', icon: Activity, color: health.ai_service_status === 'online' ? 'text-green-400' : 'text-red-400', bg: health.ai_service_status === 'online' ? 'bg-green-400/10' : 'bg-red-400/10' },
                                            { label: 'Processed Today', value: health.total_processed_today.toLocaleString(), icon: Eye, color: 'text-blue-400', bg: 'bg-blue-400/10' },
                                            { label: 'Error Rate', value: `${(health.error_rate * 100).toFixed(2)}%`, icon: AlertCircle, color: health.error_rate > 0.05 ? 'text-red-400' : 'text-green-400', bg: health.error_rate > 0.05 ? 'bg-red-400/10' : 'bg-green-400/10' },
                                        ].map((card, i) => (
                                            <motion.div key={card.label} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }} className="glass-card p-6">
                                                <div className="flex items-center gap-3 mb-3">
                                                    <div className={`p-2 rounded-lg ${card.bg}`}><card.icon size={20} className={card.color} /></div>
                                                    <span className="text-sm text-gray-400">{card.label}</span>
                                                </div>
                                                <p className="text-2xl font-extrabold">{card.value}</p>
                                            </motion.div>
                                        ))}
                                    </div>

                                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                                        {[
                                            { label: 'Avg Processing Time', value: health.avg_processing_time_ms, unit: 'ms', max: 5000, color: health.avg_processing_time_ms > 3000 ? '#ef4444' : health.avg_processing_time_ms > 1000 ? '#f59e0b' : '#10b981', icon: Clock },
                                            { label: 'Storage Used', value: health.storage_used_mb, unit: 'MB', max: 10000, color: health.storage_used_mb > 8000 ? '#ef4444' : health.storage_used_mb > 4000 ? '#f59e0b' : '#10b981', icon: Activity },
                                            { label: 'Database Size', value: health.database_size_mb, unit: 'MB', max: 5000, color: health.database_size_mb > 4000 ? '#ef4444' : health.database_size_mb > 2000 ? '#f59e0b' : '#10b981', icon: Cpu },
                                        ].map((resource, i) => (
                                            <motion.div key={resource.label} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 + i * 0.05 }} className="glass-card p-6">
                                                <div className="flex items-center gap-2 mb-4">
                                                    <resource.icon size={20} className="text-gray-400" />
                                                    <h3 className="font-bold text-gray-300">{resource.label}</h3>
                                                </div>
                                                <div className="relative pt-1">
                                                    <div className="flex justify-between mb-2">
                                                        <span className="text-sm text-gray-400">{resource.value.toFixed(1)} {resource.unit}</span>
                                                    </div>
                                                    <div className="w-full bg-gray-800 rounded-full h-3">
                                                        <div
                                                            className="h-3 rounded-full transition-all duration-500"
                                                            style={{ width: `${Math.min((resource.value / resource.max) * 100, 100)}%`, backgroundColor: resource.color }}
                                                        />
                                                    </div>
                                                </div>
                                            </motion.div>
                                        ))}
                                    </div>

                                </>
                            ) : (
                                <div className="glass-card p-12 text-center">
                                    <Activity size={48} className="text-gray-600 mx-auto mb-4" />
                                    <h2 className="text-xl font-bold mb-2">System Health Data Not Available</h2>
                                    <p className="text-gray-400">Health metrics will appear once the system is running.</p>
                                </div>
                            )}
                        </>
                    )}
                </motion.div>
            </main>
        </div>
    )
}

'use client'

import React, { useState, useEffect, useCallback, Suspense, useRef } from 'react'
import { motion } from 'framer-motion'
import { FileText, UserCheck, UserX, Eye, LinkIcon, Clock, Download, ChevronLeft, ChevronRight, UserPlus, X, Search, CheckCircle2, AlertTriangle } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import Navbar from '@/components/Navbar'
import MediaImage from '@/components/MediaImage'
import { logService, visitorService, cameraService } from '@/services/api'
import type { VisitorLog, Visitor, Camera } from '@/services/api'
import { getStaticMediaUrl } from '@/lib/utils'

// ── Date preset shortcuts ─────────────────────────────────────────────────────
const DATE_PRESETS = [
    { label: 'Today', getDates: () => { const d = new Date().toISOString().slice(0, 10); return { from: d, to: d } } },
    { label: 'Yesterday', getDates: () => { const d = new Date(Date.now() - 86400000).toISOString().slice(0, 10); return { from: d, to: d } } },
    { label: 'Last 7 days', getDates: () => { const to = new Date().toISOString().slice(0, 10); const from = new Date(Date.now() - 6 * 86400000).toISOString().slice(0, 10); return { from, to } } },
    { label: 'Last 30 days', getDates: () => { const to = new Date().toISOString().slice(0, 10); const from = new Date(Date.now() - 29 * 86400000).toISOString().slice(0, 10); return { from, to } } },
]

// ── Confidence badge with human label ────────────────────────────────────────
function ConfidencePill({ confidence }: { confidence: number }) {
    if (confidence <= 0) return null
    const pct = Math.round(confidence * 100)
    const cls = pct >= 80
        ? 'text-green-400 bg-green-400/10'
        : pct >= 60
        ? 'text-yellow-400 bg-yellow-400/10'
        : 'text-red-400 bg-red-400/10'
    const label = pct >= 80 ? 'High' : pct >= 60 ? 'Review' : 'Low'
    return (
        <span className={`text-xs px-2 py-0.5 rounded font-medium ${cls}`} title={`Confidence: ${pct}%`}>
            {pct}% · {label}
        </span>
    )
}

// ── Breadcrumb ────────────────────────────────────────────────────────────────
function Breadcrumb() {
    return (
        <nav className="flex items-center gap-2 text-xs text-gray-500 mb-6">
            <Link href="/" className="hover:text-white transition-colors">Dashboard</Link>
            <span>/</span>
            <span className="text-gray-300">Detection Logs</span>
        </nav>
    )
}

// ── Inner page (needs useSearchParams, wrapped in Suspense) ───────────────────
function LogsPageContent() {
    const router = useRouter()
    const pathname = usePathname()
    const searchParams = useSearchParams()

    // Initialise all filter state from URL so filters survive refresh + are shareable
    const [logs, setLogs] = useState<VisitorLog[]>([])
    const [visitors, setVisitors] = useState<Visitor[]>([])
    const [total, setTotal] = useState(0)
    const [page, setPage] = useState(Number(searchParams.get('page')) || 1)
    const [pages, setPages] = useState(1)
    const [loading, setLoading] = useState(true)
    const [statusFilter, setStatusFilter] = useState<string>(searchParams.get('status') || '')
    const [searchQuery, setSearchQuery] = useState(searchParams.get('search') || '')
    const [dateFrom, setDateFrom] = useState(searchParams.get('from') || '')
    const [dateTo, setDateTo] = useState(searchParams.get('to') || '')
    const [cameraFilter, setCameraFilter] = useState(searchParams.get('camera_id') || '')
    const [cameras, setCameras] = useState<Camera[]>([])
    const [assigningId, setAssigningId] = useState<string | null>(null)
    const [selectedVisitorId, setSelectedVisitorId] = useState('')
    const [visitorSearchQuery, setVisitorSearchQuery] = useState('')
    const [visitorSearchResults, setVisitorSearchResults] = useState<Visitor[]>([])
    const [visitorSearchLoading, setVisitorSearchLoading] = useState(false)
    const [showCreateVisitor, setShowCreateVisitor] = useState<string | null>(null)
    const [newVisitorName, setNewVisitorName] = useState('')
    const [activePreset, setActivePreset] = useState<string | null>(null)
    const searchDebounceRef = useRef<NodeJS.Timeout | null>(null)
    const [debouncedSearch, setDebouncedSearch] = useState(searchQuery)
    const [searchPending, setSearchPending] = useState(false)
    const [exportingCsv, setExportingCsv] = useState(false)
    const [exportingExcel, setExportingExcel] = useState(false)
    const [exportToast, setExportToast] = useState<string | null>(null)
    const [nextCursor, setNextCursor] = useState<string | null>(null)
    const [loadingMore, setLoadingMore] = useState(false)

    // ── Sync filter state → URL params ───────────────────────────────────────
    const syncUrl = useCallback((overrides: Record<string, string | number | null> = {}) => {
        const params = new URLSearchParams()
        const current = { status: statusFilter, search: searchQuery, from: dateFrom, to: dateTo, camera_id: cameraFilter, page: String(page) }
        const merged = { ...current, ...overrides }
        Object.entries(merged).forEach(([k, v]) => {
            if (v && v !== '1') params.set(k, String(v))
            else if (v === '1' && k === 'page') { /* omit default page */ }
        })
        router.replace(`${pathname}?${params.toString()}`, { scroll: false })
    }, [statusFilter, searchQuery, dateFrom, dateTo, cameraFilter, page, pathname, router])

    const fetchLogs = useCallback(async (p: number, status?: string) => {
        setLoading(true)
        setNextCursor(null)
        try {
            const params: any = { page: p, limit: 20 }
            if (status) params.status = status
            if (dateFrom) params.date_from = dateFrom
            if (dateTo) params.date_to = dateTo
            if (cameraFilter) params.camera_id = cameraFilter
            if (searchQuery.trim()) params.search = searchQuery.trim()
            const res = await logService.getLogs(params)
            setLogs(res.data.items)
            setTotal(res.data.total)
            setPages(res.data.pages)
            setNextCursor(res.data.next_cursor ?? null)
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            console.error('Failed to fetch logs:', err)
        } finally {
            setLoading(false)
        }
    }, [router, dateFrom, dateTo, cameraFilter, searchQuery])

    const loadMoreLogs = async () => {
        if (!nextCursor || loadingMore) return
        setLoadingMore(true)
        try {
            const params: any = { after_cursor: nextCursor, limit: 20 }
            if (statusFilter) params.status = statusFilter
            if (dateFrom) params.date_from = dateFrom
            if (dateTo) params.date_to = dateTo
            if (cameraFilter) params.camera_id = cameraFilter
            if (searchQuery.trim()) params.search = searchQuery.trim()
            const res = await logService.getLogs(params)
            setLogs(prev => [...prev, ...res.data.items])
            setNextCursor(res.data.next_cursor ?? null)
        } catch (err) {
            console.error('Load more logs failed:', err)
        } finally {
            setLoadingMore(false)
        }
    }

    const fetchVisitors = useCallback(async () => {
        try {
            const res = await visitorService.getVisitors({ limit: 100 })
            setVisitors(res.data.items)
        } catch (err) { console.error('Failed to fetch visitors:', err) }
    }, [])

    const fetchCameras = useCallback(async () => {
        try {
            const res = await cameraService.getCameras()
            setCameras(res.data || [])
        } catch (err) { console.error('Failed to fetch cameras:', err) }
    }, [])

    useEffect(() => {
        fetchLogs(page, statusFilter)
        fetchVisitors()
        fetchCameras()
    }, [fetchLogs, fetchVisitors, fetchCameras, page, statusFilter])

    // Keep URL in sync whenever any filter changes
    useEffect(() => { syncUrl() }, [statusFilter, searchQuery, dateFrom, dateTo, cameraFilter, page]) // eslint-disable-line

    const applyPreset = (preset: typeof DATE_PRESETS[0]) => {
        const { from, to } = preset.getDates()
        setDateFrom(from)
        setDateTo(to)
        setPage(1)
        setActivePreset(preset.label)
    }

    const clearDates = () => {
        setDateFrom('')
        setDateTo('')
        setActivePreset(null)
        setPage(1)
    }

    const handleFilterChange = (status: string) => { setStatusFilter(status); setPage(1) }

    const handleAssign = async (logId: string) => {
        if (!selectedVisitorId) return
        try {
            await logService.assignLog(logId, selectedVisitorId)
            setAssigningId(null)
            setSelectedVisitorId('')
            fetchLogs(page, statusFilter)
        } catch (err) { console.error('Failed to assign log:', err) }
    }

    const handleCreateVisitorFromLog = async (logId: string) => {
        if (!newVisitorName) return
        try {
            await logService.createVisitorFromLog(logId, { name: newVisitorName })
            setShowCreateVisitor(null)
            setNewVisitorName('')
            fetchLogs(page, statusFilter)
            fetchVisitors()
        } catch (err) { console.error('Failed to create visitor from log:', err) }
    }

    const handleExportCsv = async () => {
        setExportingCsv(true)
        try {
            const params: any = {}
            if (statusFilter) params.status = statusFilter
            if (cameraFilter) params.camera_id = cameraFilter
            if (dateFrom) params.date_from = dateFrom
            if (dateTo) params.date_to = dateTo
            if (searchQuery.trim()) params.search = searchQuery.trim()
            const res = await logService.exportCsv(params)
            const url = window.URL.createObjectURL(new Blob([res.data]))
            const link = document.createElement('a')
            link.href = url
            link.setAttribute('download', 'visitor_logs.csv')
            document.body.appendChild(link)
            link.click()
            link.remove()
            window.URL.revokeObjectURL(url)
            setExportToast('CSV exported successfully')
            setTimeout(() => setExportToast(null), 3000)
        } catch (err) {
            console.error('Failed to export CSV:', err)
            setExportToast('CSV export failed')
            setTimeout(() => setExportToast(null), 3000)
        } finally { setExportingCsv(false) }
    }

    const handleExportExcel = async () => {
        setExportingExcel(true)
        try {
            const params: any = {}
            if (statusFilter) params.status = statusFilter
            if (cameraFilter) params.camera_id = cameraFilter
            if (dateFrom) params.date_from = dateFrom
            if (dateTo) params.date_to = dateTo
            if (searchQuery.trim()) params.search = searchQuery.trim()
            const res = await logService.exportExcel(params)
            const url = window.URL.createObjectURL(new Blob([res.data]))
            const link = document.createElement('a')
            link.href = url
            link.setAttribute('download', 'visitor_logs.xlsx')
            document.body.appendChild(link)
            link.click()
            link.remove()
            window.URL.revokeObjectURL(url)
            setExportToast('Excel exported successfully')
            setTimeout(() => setExportToast(null), 3000)
        } catch (err) {
            console.error('Failed to export Excel:', err)
            setExportToast('Excel export failed')
            setTimeout(() => setExportToast(null), 3000)
        } finally { setExportingExcel(false) }
    }

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'identified': return 'bg-green-400/10 text-green-400'
            case 'unidentified': return 'bg-red-400/10 text-red-400'
            case 'reviewed': return 'bg-blue-400/10 text-blue-400'
            default: return 'bg-yellow-400/10 text-yellow-400'
        }
    }

    const timeAgo = (timestamp: string) => {
        const diff = Date.now() - new Date(timestamp).getTime()
        const mins = Math.floor(diff / 60000)
        if (mins < 1) return 'Just now'
        if (mins < 60) return `${mins}m ago`
        const hours = Math.floor(mins / 60)
        if (hours < 24) return `${hours}h ago`
        return new Date(timestamp).toLocaleDateString()
    }

    const filters = [
        { value: '', label: 'All' },
        { value: 'identified', label: 'Identified' },
        { value: 'unidentified', label: 'Unidentified' },
        { value: 'reviewed', label: 'Reviewed' },
        { value: 'detected', label: 'Detected' },
    ]

    const hasDateFilter = dateFrom || dateTo

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-24 px-6 container mx-auto">
                <Breadcrumb />

                <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4">
                    <div>
                        <h1 className="text-3xl font-bold mb-1">Detection Logs</h1>
                        <p className="text-gray-400">Review, filter, and assign visitor detections ({total} total)</p>
                    </div>
                    <div className="flex gap-2 items-center">
                        <button
                            onClick={handleExportCsv}
                            disabled={exportingCsv}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 text-gray-400 hover:text-white text-xs font-medium transition-colors disabled:opacity-50"
                        >
                            {exportingCsv ? <div className="w-3.5 h-3.5 border-2 border-gray-400/50 border-t-gray-400 rounded-full animate-spin" /> : <Download size={14} />} Export CSV
                        </button>
                        <button
                            onClick={handleExportExcel}
                            disabled={exportingExcel}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 text-gray-400 hover:text-white text-xs font-medium transition-colors disabled:opacity-50"
                        >
                            {exportingExcel ? <div className="w-3.5 h-3.5 border-2 border-gray-400/50 border-t-gray-400 rounded-full animate-spin" /> : <Download size={14} />} Export Excel
                        </button>
                    </div>
                </div>

                {/* ── Filters ──────────────────────────────────────────────── */}
                <div className="glass-card p-4 mb-6 space-y-4">
                    {/* Status filter pills */}
                    <div className="flex flex-wrap gap-2 items-center">
                        <span className="text-xs text-gray-500 font-medium mr-1">Status:</span>
                        {filters.map((f) => (
                            <button
                                key={f.value}
                                onClick={() => handleFilterChange(f.value)}
                                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                                    statusFilter === f.value
                                        ? 'bg-brand-600 text-white'
                                        : 'bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white'
                                }`}
                            >
                                {f.label}
                            </button>
                        ))}
                    </div>

                    {/* Date presets + range */}
                    <div className="flex flex-wrap gap-2 items-center">
                        <span className="text-xs text-gray-500 font-medium mr-1">Date:</span>
                        {DATE_PRESETS.map((preset) => (
                            <button
                                key={preset.label}
                                onClick={() => applyPreset(preset)}
                                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                                    activePreset === preset.label
                                        ? 'bg-brand-600 text-white'
                                        : 'bg-white/5 text-gray-400 hover:bg-white/10 hover:text-white'
                                }`}
                            >
                                {preset.label}
                            </button>
                        ))}
                        <div className="flex items-center gap-2">
                            <input
                                type="date"
                                value={dateFrom}
                                onChange={(e) => { setDateFrom(e.target.value); setActivePreset(null); setPage(1) }}
                                className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500"
                            />
                            <span className="text-gray-500 text-xs">to</span>
                            <input
                                type="date"
                                value={dateTo}
                                onChange={(e) => { setDateTo(e.target.value); setActivePreset(null); setPage(1) }}
                                className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500"
                            />
                            {hasDateFilter && (
                                <button onClick={clearDates} className="text-gray-500 hover:text-white transition-colors" title="Clear dates">
                                    <X size={14} />
                                </button>
                            )}
                        </div>
                    </div>

                    {/* Search + camera */}
                    <div className="flex flex-wrap gap-2 items-center">
                        <span className="text-xs text-gray-500 font-medium mr-1">Search:</span>
                        <div className="relative">
                            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
                            <input
                                type="text"
                                value={searchQuery}
                                onChange={(e) => {
                                    const val = e.target.value
                                    setSearchQuery(val)
                                    setSearchPending(true)
                                    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current)
                                    searchDebounceRef.current = setTimeout(() => {
                                        setDebouncedSearch(val)
                                        setPage(1)
                                        setSearchPending(false)
                                    }, 300)
                                }}
                                className="bg-white/5 border border-white/10 rounded-lg pl-8 pr-8 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500 w-52"
                                placeholder="Search name or ID…"
                            />
                            {searchPending && (
                                <div className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 border-2 border-brand-400/50 border-t-brand-400 rounded-full animate-spin" />
                            )}
                            {searchQuery && !searchPending && (
                                <button
                                    onClick={() => { setSearchQuery(''); setPage(1) }}
                                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white"
                                >
                                    <X size={12} />
                                </button>
                            )}
                        </div>
                        {cameras.length > 0 && (
                            <select
                                value={cameraFilter}
                                onChange={(e) => { setCameraFilter(e.target.value); setPage(1) }}
                                className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-brand-500"
                            >
                                <option value="">All Sources</option>
                                {cameras.map((cam) => (
                                    <option key={cam.id} value={cam.id}>{cam.name}</option>
                                ))}
                            </select>
                        )}

                        {/* Active filter summary */}
                        {(statusFilter || searchQuery || hasDateFilter || cameraFilter) && (
                            <button
                                onClick={() => { setStatusFilter(''); setSearchQuery(''); setDateFrom(''); setDateTo(''); setCameraFilter(''); setActivePreset(null); setPage(1) }}
                                className="ml-auto flex items-center gap-1.5 text-xs text-red-400 hover:text-red-300 transition-colors"
                            >
                                <X size={12} /> Clear all filters
                            </button>
                        )}
                    </div>
                </div>

                {/* ── Active filter chips ───────────────────────────────── */}
                {(statusFilter || searchQuery || hasDateFilter || cameraFilter) && (
                    <div className="flex flex-wrap gap-2 mb-4">
                        {statusFilter && (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-brand-500/10 text-brand-400 text-xs font-medium">
                                Status: {statusFilter}
                                <button onClick={() => { setStatusFilter(''); setPage(1) }} className="hover:text-white"><X size={11} /></button>
                            </span>
                        )}
                        {searchQuery && (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-brand-500/10 text-brand-400 text-xs font-medium">
                                Search: &ldquo;{searchQuery}&rdquo;
                                <button onClick={() => { setSearchQuery(''); setPage(1) }} className="hover:text-white"><X size={11} /></button>
                            </span>
                        )}
                        {hasDateFilter && (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-brand-500/10 text-brand-400 text-xs font-medium">
                                Date: {dateFrom || '…'} → {dateTo || '…'}
                                <button onClick={clearDates} className="hover:text-white"><X size={11} /></button>
                            </span>
                        )}
                        {cameraFilter && (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-brand-500/10 text-brand-400 text-xs font-medium">
                                Camera: {cameras.find(c => c.id === cameraFilter)?.name || cameraFilter.slice(0, 8)}
                                <button onClick={() => { setCameraFilter(''); setPage(1) }} className="hover:text-white"><X size={11} /></button>
                            </span>
                        )}
                    </div>
                )}

                {/* Result count */}
                {!loading && logs.length > 0 && (
                    <div className="text-xs text-gray-500 mb-3">
                        Showing {Math.min((page - 1) * 20 + 1, total)}&ndash;{Math.min(page * 20, total)} of {total.toLocaleString()} detections
                    </div>
                )}

                {/* Export toast */}
                {exportToast && (
                    <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-lg bg-gray-900 border border-white/10 text-sm text-white shadow-xl flex items-center gap-2">
                        {exportToast.includes('failed') ? <AlertTriangle size={14} className="text-red-400" /> : <CheckCircle2 size={14} className="text-green-400" />}
                        {exportToast}
                    </div>
                )}

                {/* ── Results ──────────────────────────────────────────────── */}
                {loading ? (
                    <div className="space-y-3">
                        {[1, 2, 3, 4, 5].map((i) => (
                            <div key={i} className="glass-card p-4 animate-pulse" style={{ minHeight: '80px' }}>
                                <div className="flex items-center gap-4">
                                    <div className="w-14 h-14 rounded-xl bg-white/5 shrink-0" />
                                    <div className="flex-1 space-y-2">
                                        <div className="h-3 bg-white/5 rounded w-1/2" />
                                        <div className="h-3 bg-white/5 rounded w-1/3" />
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                ) : logs.length === 0 ? (
                    <div className="glass-card p-12 text-center">
                        <FileText size={40} className="text-gray-600 mx-auto mb-4" />
                        <h3 className="text-lg font-bold mb-2">No Logs Found</h3>
                        <p className="text-gray-400 mb-4">
                            {(statusFilter || searchQuery || hasDateFilter || cameraFilter)
                                ? 'No results match your current filters. Try adjusting or clearing them.'
                                : 'Upload a video to generate detection events.'}
                        </p>
                        {(statusFilter || searchQuery || hasDateFilter || cameraFilter) && (
                            <button
                                onClick={() => { setStatusFilter(''); setSearchQuery(''); setDateFrom(''); setDateTo(''); setCameraFilter(''); setActivePreset(null); setPage(1) }}
                                className="text-sm text-brand-400 hover:text-brand-300 transition-colors"
                            >
                                Clear all filters
                            </button>
                        )}
                    </div>
                ) : (
                    <>
                        <div className="space-y-3">
                            {logs.map((log, i) => (
                                <motion.div
                                    key={log.id}
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={{ delay: i * 0.03 }}
                                    className="glass-card p-4"
                                >
                                    <div className="flex items-center gap-4">
                                        {/* Thumbnail */}
                                        <Link
                                            href={`/logs/${log.id}`}
                                            className="relative w-14 h-14 rounded-xl bg-gray-800 flex items-center justify-center shrink-0 overflow-hidden border border-white/5 hover:border-brand-500/40 transition-colors"
                                        >
                                            {getStaticMediaUrl(log.visitor_image_url || log.face_image_path) ? (
                                                <MediaImage
                                                    sources={[log.visitor_image_url, log.face_image_path]}
                                                    alt={log.visitor_name || 'Detection'}
                                                    className="w-full h-full object-cover"
                                                    fallback={<Eye className="text-gray-600" size={20} />}
                                                />
                                            ) : (
                                                <Eye className="text-gray-600" size={20} />
                                            )}
                                            <span className={`absolute -bottom-1 -right-1 px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                                                log.visitor_id ? 'bg-green-500/90 text-white border-green-400/30' : 'bg-yellow-500/90 text-white border-yellow-400/30'
                                            }`}>
                                                {log.visitor_id ? 'ID' : 'UN'}
                                            </span>
                                        </Link>

                                        {/* Info */}
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-1 flex-wrap">
                                                <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(log.status)}`}>
                                                    {log.status}
                                                </span>
                                                <span className="text-sm font-semibold text-white truncate">
                                                    {log.visitor_name || 'Unidentified'}
                                                </span>
                                                <ConfidencePill confidence={log.confidence} />
                                            </div>
                                            <p className="text-sm text-gray-400 flex items-center gap-1">
                                                <Clock size={12} />
                                                {timeAgo(log.timestamp)}
                                                {log.visitor_id && (
                                                    <Link href={`/visitors/${log.visitor_id}`} className="text-brand-500 ml-2 hover:underline">
                                                        {log.visitor_name || `Visitor ${log.visitor_id.slice(0, 8)}…`}
                                                    </Link>
                                                )}
                                            </p>
                                        </div>

                                        {/* Actions */}
                                        <div className="flex items-center gap-2 shrink-0">
                                            <Link href={`/logs/${log.id}`} className="text-gray-400 hover:text-brand-500 transition-colors">
                                                <Eye size={16} />
                                            </Link>

                                            {(log.status === 'unidentified' || log.status === 'detected') && (
                                                <>
                                                    {assigningId === log.id ? (
                                                        <div className="flex items-center gap-2">
                                                            <div className="relative">
                                                                <input
                                                                    type="text"
                                                                    value={visitorSearchQuery}
                                                                    onChange={async (e) => {
                                                                        const q = e.target.value
                                                                        setVisitorSearchQuery(q)
                                                                        if (q.trim().length < 1) { setVisitorSearchResults([]); return }
                                                                        setVisitorSearchLoading(true)
                                                                        try {
                                                                            const res = await visitorService.getVisitors({ search: q.trim(), limit: 10 })
                                                                            setVisitorSearchResults(res.data.items.filter((v: Visitor) => v.is_known))
                                                                        } catch { setVisitorSearchResults([]) }
                                                                        finally { setVisitorSearchLoading(false) }
                                                                    }}
                                                                    placeholder="Search visitor…"
                                                                    className="bg-white/5 border border-white/10 rounded px-2 py-1.5 text-sm text-white focus:outline-none w-40"
                                                                />
                                                                {visitorSearchResults.length > 0 && (
                                                                    <div className="absolute top-full left-0 mt-1 w-56 bg-gray-950 border border-white/10 rounded-lg shadow-xl z-50 max-h-40 overflow-y-auto">
                                                                        {visitorSearchResults.map(v => (
                                                                            <button
                                                                                key={v.id}
                                                                                onClick={() => { setSelectedVisitorId(v.id); setVisitorSearchQuery(v.name || v.id.slice(0, 8)); setVisitorSearchResults([]) }}
                                                                                className="w-full text-left px-3 py-2 text-sm text-gray-300 hover:bg-white/10 flex items-center gap-2"
                                                                            >
                                                                                <UserPlus size={12} className="text-gray-500 shrink-0" />
                                                                                <span className="truncate">{v.name || v.id.slice(0, 8)}</span>
                                                                            </button>
                                                                        ))}
                                                                    </div>
                                                                )}
                                                                {visitorSearchLoading && (
                                                                    <div className="absolute right-2 top-1/2 -translate-y-1/2 w-3 h-3 border-2 border-brand-400/50 border-t-brand-400 rounded-full animate-spin" />
                                                                )}
                                                            </div>
                                                            <button onClick={() => handleAssign(log.id)} disabled={!selectedVisitorId} className="bg-brand-600 disabled:opacity-40 text-white px-3 py-1.5 rounded text-xs font-medium">Assign</button>
                                                            <button onClick={() => { setAssigningId(null); setVisitorSearchQuery(''); setVisitorSearchResults([]) }} className="text-gray-400 hover:text-white text-xs">Cancel</button>
                                                        </div>
                                                    ) : showCreateVisitor === log.id ? (
                                                        <div className="flex items-center gap-2">
                                                            <input
                                                                value={newVisitorName}
                                                                onChange={(e) => setNewVisitorName(e.target.value)}
                                                                placeholder="Visitor name"
                                                                className="bg-white/5 border border-white/10 rounded px-2 py-1.5 text-sm text-white focus:outline-none w-32"
                                                            />
                                                            <button onClick={() => handleCreateVisitorFromLog(log.id)} className="bg-green-600 text-white px-3 py-1.5 rounded text-xs font-medium">Create</button>
                                                            <button onClick={() => setShowCreateVisitor(null)} className="text-gray-400 hover:text-white"><X size={14} /></button>
                                                        </div>
                                                    ) : (
                                                        <div className="flex gap-1">
                                                            <button
                                                                onClick={() => setAssigningId(log.id)}
                                                                className="text-brand-500 hover:text-brand-400 text-xs font-medium flex items-center gap-1"
                                                            >
                                                                <LinkIcon size={14} /> Assign
                                                            </button>
                                                            <button
                                                                onClick={() => { setShowCreateVisitor(log.id); setNewVisitorName('') }}
                                                                className="text-green-500 hover:text-green-400 text-xs font-medium flex items-center gap-1 ml-2"
                                                            >
                                                                <UserPlus size={14} /> New
                                                            </button>
                                                        </div>
                                                    )}
                                                </>
                                            )}
                                        </div>
                                    </div>
                                </motion.div>
                            ))}
                        </div>

                        {/* Pagination — offset mode */}
                        {pages > 1 && (
                            <div className="flex items-center justify-center gap-4 mt-8">
                                <button
                                    onClick={() => setPage(Math.max(1, page - 1))}
                                    disabled={page <= 1}
                                    className="flex items-center gap-1 px-3 py-2 rounded-lg bg-white/5 text-gray-400 hover:text-white disabled:opacity-30 text-sm transition-colors"
                                >
                                    <ChevronLeft size={16} /> Previous
                                </button>
                                <span className="text-sm text-gray-400">
                                    Showing {Math.min((page - 1) * 20 + 1, total)}–{Math.min(page * 20, total)} of {total.toLocaleString()} · Page {page} of {pages}
                                </span>
                                <button
                                    onClick={() => setPage(Math.min(pages, page + 1))}
                                    disabled={page >= pages}
                                    className="flex items-center gap-1 px-3 py-2 rounded-lg bg-white/5 text-gray-400 hover:text-white disabled:opacity-30 text-sm transition-colors"
                                >
                                    Next <ChevronRight size={16} />
                                </button>
                            </div>
                        )}

                        {/* Load More — cursor mode (no OFFSET scan penalty) */}
                        {nextCursor && (
                            <div className="flex justify-center mt-6">
                                <button
                                    onClick={loadMoreLogs}
                                    disabled={loadingMore}
                                    className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white disabled:opacity-40 text-sm transition-colors"
                                >
                                    {loadingMore
                                        ? <><span className="w-4 h-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" /> Loading…</>
                                        : <><ChevronRight size={15} /> Load More</>
                                    }
                                </button>
                            </div>
                        )}
                    </>
                )}
            </main>
        </div>
    )
}

export default function LogsPage() {
    return (
        <Suspense fallback={
            <div className="min-h-screen flex items-center justify-center">
                <div className="text-white">Loading…</div>
            </div>
        }>
            <LogsPageContent />
        </Suspense>
    )
}

'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Shield, Search, ChevronLeft, ChevronRight, Clock, User, FileText, Download } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { auditLogService, authService } from '@/services/api'
import type { AuditLog } from '@/services/api'

const actionOptions = [
    { value: '', label: 'All Actions' },
    { value: 'login', label: 'Login' },
    { value: 'login_failed', label: 'Login Failed' },
    { value: 'create', label: 'Create' },
    { value: 'update', label: 'Update' },
    { value: 'delete', label: 'Delete' },
    { value: 'bulk_import', label: 'Bulk Import' },
    { value: 'export_visitors', label: 'Export Visitors' },
]

export default function AuditLogsPage() {
    const [logs, setLogs] = useState<AuditLog[]>([])
    const [loading, setLoading] = useState(true)
    const [exporting, setExporting] = useState(false)
    const [total, setTotal] = useState(0)
    const [page, setPage] = useState(1)
    const [viewMode, setViewMode] = useState<'audit' | 'login'>('audit')
    const [search, setSearch] = useState('')
    const [debouncedSearch, setDebouncedSearch] = useState('')
    const [actionFilter, setActionFilter] = useState('')
    const [userFilter, setUserFilter] = useState('')
    const [includeFailedLogins, setIncludeFailedLogins] = useState(true)
    const [dateFrom, setDateFrom] = useState('')
    const [dateTo, setDateTo] = useState('')
    const limit = 25

    const toIsoOrUndefined = useCallback((value: string) => {
        if (!value) return undefined
        const parsed = new Date(value)
        return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString()
    }, [])

    const fetchLogs = useCallback(async (p: number, q?: string) => {
        try {
            setLoading(true)

            if (viewMode === 'login') {
                const res = await authService.getLoginHistory({
                    page: p,
                    limit,
                    user_id: userFilter || undefined,
                    include_failed: includeFailedLogins,
                    date_from: toIsoOrUndefined(dateFrom),
                    date_to: toIsoOrUndefined(dateTo),
                })
                setLogs(res.data.items)
                setTotal(res.data.total)
                return
            }

            const skip = (p - 1) * limit
            const res = await auditLogService.getAuditLogs({
                skip,
                limit,
                search: q || undefined,
                action: actionFilter || undefined,
                user_id: userFilter || undefined,
                date_from: toIsoOrUndefined(dateFrom),
                date_to: toIsoOrUndefined(dateTo),
            })
            setLogs(res.data.items)
            setTotal(res.data.total)
        } catch (err: any) {
            if (err.response?.status === 401) {
                window.location.href = '/login'
                return
            }
            if (err.response?.status === 403) {
                setLogs([])
                setTotal(0)
            }
            console.error('Failed to fetch audit logs:', err)
        } finally {
            setLoading(false)
        }
    }, [viewMode, actionFilter, userFilter, includeFailedLogins, dateFrom, dateTo, toIsoOrUndefined])

    // Debounce search
    useEffect(() => {
        if (viewMode === 'login') {
            setDebouncedSearch('')
            return
        }

        const timer = setTimeout(() => {
            setDebouncedSearch(search)
            setPage(1)
        }, 300)
        return () => clearTimeout(timer)
    }, [search, viewMode])

    useEffect(() => {
        fetchLogs(page, debouncedSearch)
    }, [fetchLogs, page, debouncedSearch])

    const totalPages = Math.ceil(total / limit) || 1

    const formatAction = (action: string) => {
        return action
            .replace(/_/g, ' ')
            .replace(/\b\w/g, (c) => c.toUpperCase())
    }

    const formatTimestamp = (ts: string) => {
        const d = new Date(ts)
        return d.toLocaleString()
    }

    const formatDetails = (log: AuditLog) => {
        const details = log.details || {}
        const ipAddress = details.ip_address as string | undefined
        const userAgent = details.user_agent as string | undefined
        if (ipAddress || userAgent) {
            return `${ipAddress || 'ip: n/a'}${userAgent ? ` | ${userAgent}` : ''}`
        }
        return log.details ? JSON.stringify(log.details) : '—'
    }

    const clearFilters = () => {
        setSearch('')
        setDebouncedSearch('')
        setActionFilter('')
        setUserFilter('')
        setIncludeFailedLogins(true)
        setDateFrom('')
        setDateTo('')
        setPage(1)
    }

    const handleExport = async () => {
        setExporting(true)
        try {
            const res = await auditLogService.exportCsv({
                search: debouncedSearch || undefined,
                action: actionFilter || undefined,
                user_id: userFilter || undefined,
                date_from: toIsoOrUndefined(dateFrom),
                date_to: toIsoOrUndefined(dateTo),
            })
            const url = URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }))
            const a = document.createElement('a')
            a.href = url
            a.download = `audit_logs_${new Date().toISOString().slice(0, 10)}.csv`
            a.click()
            URL.revokeObjectURL(url)
        } catch {
            console.error('Export failed')
        } finally {
            setExporting(false)
        }
    }

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-20 px-6 container mx-auto max-w-6xl">
                <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
                    {/* Header */}
                    <div className="flex items-center justify-between mb-8">
                        <div className="flex items-center gap-3">
                            <div className="w-10 h-10 bg-brand-500/20 rounded-xl flex items-center justify-center">
                                <Shield className="text-brand-400" size={20} />
                            </div>
                            <div>
                                <h1 className="text-2xl font-bold">Audit Logs</h1>
                                <p className="text-sm text-gray-400">
                                    {viewMode === 'login' ? 'Login activity history' : 'Organization audit history'} ({total} total entries)
                                </p>
                            </div>
                        </div>
                        {viewMode === 'audit' && (
                            <button
                                onClick={handleExport}
                                disabled={exporting || loading}
                                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-600 hover:bg-brand-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors"
                            >
                                <Download size={15} />
                                {exporting ? 'Exporting…' : 'Export CSV'}
                            </button>
                        )}
                    </div>

                    {/* Search + Filters */}
                    <div className="mb-6 space-y-3">
                        <div className="relative max-w-md">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
                            <input
                                type="text"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                disabled={viewMode === 'login'}
                                placeholder={viewMode === 'login' ? 'Search is disabled in login history mode' : 'Search audit logs...'}
                                className="w-full pl-10 pr-4 py-2.5 bg-gray-900/50 border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40 disabled:opacity-60 disabled:cursor-not-allowed"
                            />
                        </div>

                        <div className="flex flex-wrap items-center gap-3">
                            <select
                                value={viewMode}
                                onChange={(e) => {
                                    const mode = e.target.value as 'audit' | 'login'
                                    setViewMode(mode)
                                    setPage(1)
                                }}
                                className="px-3 py-2.5 bg-gray-900/50 border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40"
                            >
                                <option value="audit">All Audit Logs</option>
                                <option value="login">Login History</option>
                            </select>

                            <select
                                value={actionFilter}
                                onChange={(e) => {
                                    setActionFilter(e.target.value)
                                    setPage(1)
                                }}
                                disabled={viewMode === 'login'}
                                className="px-3 py-2.5 bg-gray-900/50 border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40 disabled:opacity-60 disabled:cursor-not-allowed"
                            >
                                {actionOptions.map((option) => (
                                    <option key={option.value || 'all'} value={option.value}>
                                        {option.label}
                                    </option>
                                ))}
                            </select>

                            <input
                                type="text"
                                value={userFilter}
                                onChange={(e) => {
                                    setUserFilter(e.target.value)
                                    setPage(1)
                                }}
                                placeholder="Filter by user ID"
                                className="px-3 py-2.5 bg-gray-900/50 border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40"
                            />

                            {viewMode === 'login' && (
                                <label className="flex items-center gap-2 px-3 py-2.5 bg-gray-900/50 border border-gray-800 rounded-lg text-sm text-gray-300">
                                    <input
                                        type="checkbox"
                                        checked={includeFailedLogins}
                                        onChange={(e) => {
                                            setIncludeFailedLogins(e.target.checked)
                                            setPage(1)
                                        }}
                                        className="accent-brand-500"
                                    />
                                    Include failed logins
                                </label>
                            )}

                            <input
                                type="datetime-local"
                                value={dateFrom}
                                onChange={(e) => {
                                    setDateFrom(e.target.value)
                                    setPage(1)
                                }}
                                className="px-3 py-2.5 bg-gray-900/50 border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40"
                            />

                            <input
                                type="datetime-local"
                                value={dateTo}
                                onChange={(e) => {
                                    setDateTo(e.target.value)
                                    setPage(1)
                                }}
                                className="px-3 py-2.5 bg-gray-900/50 border border-gray-800 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40"
                            />

                            <button
                                onClick={clearFilters}
                                className="px-3 py-2.5 bg-gray-800 rounded-lg text-sm hover:bg-gray-700 transition-colors"
                            >
                                Clear Filters
                            </button>
                        </div>
                    </div>

                    {/* Table */}
                    {loading ? (
                        <div className="space-y-3">
                            {[1, 2, 3, 4, 5].map((i) => (
                                <div key={i} className="h-16 bg-gray-800/40 rounded-lg animate-pulse" />
                            ))}
                        </div>
                    ) : logs.length === 0 ? (
                        <div className="text-center py-20 text-gray-400">
                            <Shield size={48} className="mx-auto mb-4 opacity-30" />
                            <p className="text-lg font-medium">No audit logs found</p>
                            <p className="text-sm mt-1">Actions will appear here as they occur</p>
                        </div>
                    ) : (
                        <div className="glass-card overflow-hidden">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-gray-800 text-gray-400">
                                        <th className="text-left px-4 py-3 font-medium">Timestamp</th>
                                        <th className="text-left px-4 py-3 font-medium">Action</th>
                                        <th className="text-left px-4 py-3 font-medium">Entity</th>
                                        <th className="text-left px-4 py-3 font-medium">User</th>
                                        <th className="text-left px-4 py-3 font-medium">Details</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {logs.map((log) => (
                                        <tr key={log.id} className="border-b border-gray-800/50 hover:bg-gray-800/30 transition-colors">
                                            <td className="px-4 py-3 whitespace-nowrap">
                                                <div className="flex items-center gap-2 text-gray-300">
                                                    <Clock size={14} className="text-gray-500" />
                                                    {formatTimestamp(log.timestamp)}
                                                </div>
                                            </td>
                                            <td className="px-4 py-3">
                                                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-brand-500/10 text-brand-400">
                                                    {formatAction(log.action)}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3">
                                                {log.entity_type && (
                                                    <div className="flex items-center gap-2">
                                                        <FileText size={14} className="text-gray-500" />
                                                        <span className="text-gray-300">{log.entity_type}</span>
                                                        {log.entity_id && (
                                                            <span className="text-gray-500 text-xs font-mono">
                                                                {log.entity_id.substring(0, 8)}...
                                                            </span>
                                                        )}
                                                    </div>
                                                )}
                                            </td>
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-2">
                                                    <User size={14} className="text-gray-500" />
                                                    <span className="text-gray-300 text-xs font-mono">
                                                        {log.user_id ? log.user_id.substring(0, 8) + '...' : 'System'}
                                                    </span>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3 max-w-xs truncate text-gray-400 text-xs">
                                                {formatDetails(log)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {/* Pagination */}
                    {totalPages > 1 && (
                        <div className="flex items-center justify-between mt-6 text-sm text-gray-400">
                            <span>Page {page} of {totalPages}</span>
                            <div className="flex gap-2">
                                <button
                                    disabled={page <= 1}
                                    onClick={() => setPage((p) => p - 1)}
                                    className="px-3 py-1.5 bg-gray-800 rounded-lg hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                    <ChevronLeft size={16} />
                                </button>
                                <button
                                    disabled={page >= totalPages}
                                    onClick={() => setPage((p) => p + 1)}
                                    className="px-3 py-1.5 bg-gray-800 rounded-lg hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                    <ChevronRight size={16} />
                                </button>
                            </div>
                        </div>
                    )}
                </motion.div>
            </main>
        </div>
    )
}

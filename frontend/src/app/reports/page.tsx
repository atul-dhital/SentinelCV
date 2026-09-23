'use client'

import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { FileText, Download, Calendar, RefreshCw, AlertCircle, CheckCircle, TableProperties } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { analyticsService } from '@/services/api'

const reportTypes = [
    { value: 'accuracy', label: 'Accuracy Report', desc: 'Identification accuracy metrics and trends' },
    { value: 'visitor_activity', label: 'Visitor Activity', desc: 'Visitor visit patterns and frequency analysis' },
    { value: 'system_health', label: 'System Health', desc: 'Camera uptime, processing performance, errors' },
    { value: 'comprehensive', label: 'Comprehensive', desc: 'Full system report with all metrics' },
]

export default function ReportsPage() {
    const [reportType, setReportType] = useState('comprehensive')
    const [format, setFormat] = useState<'json' | 'csv'>('json')
    const [dateFrom, setDateFrom] = useState('')
    const [dateTo, setDateTo] = useState('')
    const [generating, setGenerating] = useState(false)
    const [report, setReport] = useState<any>(null)
    const [reportGeneratedAt, setReportGeneratedAt] = useState<string | null>(null)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

    const handleGenerate = async () => {
        setGenerating(true)
        setMessage(null)
        try {
            const params: any = { report_type: reportType, format }
            if (dateFrom) params.date_from = dateFrom
            if (dateTo) params.date_to = dateTo

            if (format === 'csv') {
                const res = await analyticsService.generateReport(params, { responseType: 'blob' })
                const url = URL.createObjectURL(res.data)
                const anchor = document.createElement('a')
                anchor.href = url
                anchor.download = `sentinelcv-${reportType}-report-${new Date().toISOString().split('T')[0]}.csv`
                anchor.click()
                URL.revokeObjectURL(url)
                setReportGeneratedAt(new Date().toLocaleString())
                setMessage({ type: 'success', text: 'CSV report downloaded successfully!' })
                return
            }

            setReport(null)
            const res = await analyticsService.generateReport(params)
            setReport(res.data)
            setReportGeneratedAt(new Date().toLocaleString())
            setMessage({ type: 'success', text: 'Report generated successfully!' })
        } catch (err: any) {
            if (err.response?.status === 401) {
                window.location.href = '/login'
                return
            }
            setMessage({ type: 'error', text: 'Failed to generate report' })
        } finally {
            setGenerating(false)
        }
    }

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-20 px-6 container mx-auto">
                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
                    <div className="mb-10">
                        <h1 className="text-4xl font-extrabold mb-3 bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
                            Reports
                        </h1>
                        <p className="text-gray-400 text-lg">Generate and download comprehensive system reports.</p>
                    </div>

                    {message && (
                        <div className={`mb-6 p-4 rounded-lg flex items-center gap-3 ${
                            message.type === 'success'
                                ? 'bg-green-500/10 text-green-400 border border-green-500/20'
                                : 'bg-red-500/10 text-red-400 border border-red-500/20'
                        }`}>
                            {message.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
                            {message.text}
                        </div>
                    )}

                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                        {/* Report Config */}
                        <div className="lg:col-span-1 space-y-6">
                            <div className="glass-card p-6 space-y-6">
                                <div className="flex items-center gap-3 mb-2">
                                    <div className="p-2 bg-brand-500/10 rounded-lg">
                                        <FileText className="text-brand-500" size={24} />
                                    </div>
                                    <h2 className="text-xl font-bold">Configure Report</h2>
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-gray-300 mb-2">Report Type</label>
                                    <div className="space-y-2">
                                        {reportTypes.map(rt => (
                                            <label
                                                key={rt.value}
                                                className={`flex items-start gap-3 p-3 rounded-lg cursor-pointer transition-colors border ${
                                                    reportType === rt.value
                                                        ? 'bg-brand-600/10 border-brand-500/30'
                                                        : 'bg-gray-900/30 border-gray-800 hover:border-gray-700'
                                                }`}
                                            >
                                                <input
                                                    type="radio"
                                                    name="report_type"
                                                    value={rt.value}
                                                    checked={reportType === rt.value}
                                                    onChange={e => setReportType(e.target.value)}
                                                    className="mt-1 accent-brand-500"
                                                />
                                                <div>
                                                    <p className="text-sm font-medium text-gray-200">{rt.label}</p>
                                                    <p className="text-xs text-gray-500">{rt.desc}</p>
                                                </div>
                                            </label>
                                        ))}
                                    </div>
                                </div>

                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">
                                            <Calendar size={14} className="inline mr-1" />From
                                        </label>
                                        <input
                                            type="date"
                                            value={dateFrom}
                                            onChange={e => setDateFrom(e.target.value)}
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-brand-500 outline-none"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">
                                            <Calendar size={14} className="inline mr-1" />To
                                        </label>
                                        <input
                                            type="date"
                                            value={dateTo}
                                            onChange={e => setDateTo(e.target.value)}
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:border-brand-500 outline-none"
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label className="block text-sm font-medium text-gray-300 mb-2">Export Format</label>
                                    <div className="grid grid-cols-2 gap-3">
                                        <button
                                            type="button"
                                            onClick={() => setFormat('json')}
                                            className={`rounded-lg border px-4 py-3 text-sm font-medium transition-colors ${
                                                format === 'json'
                                                    ? 'bg-brand-600/10 border-brand-500/30 text-white'
                                                    : 'bg-gray-900/30 border-gray-800 text-gray-400 hover:border-gray-700'
                                            }`}
                                        >
                                            <div className="flex items-center justify-center gap-2">
                                                <FileText size={16} />
                                                JSON Preview
                                            </div>
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setFormat('csv')}
                                            className={`rounded-lg border px-4 py-3 text-sm font-medium transition-colors ${
                                                format === 'csv'
                                                    ? 'bg-brand-600/10 border-brand-500/30 text-white'
                                                    : 'bg-gray-900/30 border-gray-800 text-gray-400 hover:border-gray-700'
                                            }`}
                                        >
                                            <div className="flex items-center justify-center gap-2">
                                                <TableProperties size={16} />
                                                CSV Download
                                            </div>
                                        </button>
                                    </div>
                                </div>

                                <button
                                    onClick={handleGenerate}
                                    disabled={generating}
                                    className="w-full bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-6 py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
                                >
                                    {generating ? (
                                        <><RefreshCw size={18} className="animate-spin" /> Generating...</>
                                    ) : (
                                        <><FileText size={18} /> {format === 'csv' ? 'Generate And Download CSV' : 'Generate Report'}</>
                                    )}
                                </button>
                            </div>
                        </div>

                        {/* Report Results */}
                        <div className="lg:col-span-2">
                            {report ? (
                                <div className="glass-card p-6 space-y-6">
                                    <div className="flex items-center justify-between">
                                        <h2 className="text-xl font-bold">Report Results</h2>
                                        <div className="flex items-center gap-4">
                                            <span className="text-sm text-gray-500">
                                                Generated: {reportGeneratedAt}
                                            </span>
                                            <button
                                                onClick={() => {
                                                    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
                                                    const url = URL.createObjectURL(blob)
                                                    const a = document.createElement('a')
                                                    a.href = url
                                                    a.download = `sentinelcv-${reportType}-report-${new Date().toISOString().split('T')[0]}.json`
                                                    a.click()
                                                    URL.revokeObjectURL(url)
                                                }}
                                                className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-700 text-white rounded-lg text-sm font-medium transition-colors"
                                            >
                                                <Download size={16} /> Download JSON
                                            </button>
                                        </div>
                                    </div>

                                    {report.summary && (
                                        <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
                                            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                                                <p className="text-xs uppercase tracking-widest text-gray-500 mb-2">Total Events</p>
                                                <p className="text-2xl font-black text-white">{report.summary.total_events ?? 0}</p>
                                            </div>
                                            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                                                <p className="text-xs uppercase tracking-widest text-gray-500 mb-2">Accuracy</p>
                                                <p className="text-2xl font-black text-emerald-400">
                                                    {((report.summary.accuracy ?? 0) * 100).toFixed(1)}%
                                                </p>
                                            </div>
                                            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                                                <p className="text-xs uppercase tracking-widest text-gray-500 mb-2">Identified</p>
                                                <p className="text-2xl font-black text-sky-400">{report.summary.identified ?? 0}</p>
                                            </div>
                                            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
                                                <p className="text-xs uppercase tracking-widest text-gray-500 mb-2">Known Visitors</p>
                                                <p className="text-2xl font-black text-brand-400">{report.summary.known_visitors ?? 0}</p>
                                            </div>
                                        </div>
                                    )}

                                    <div className="bg-gray-900/50 rounded-lg p-4 overflow-auto max-h-[600px]">
                                        <pre className="text-sm text-gray-300 whitespace-pre-wrap">
                                            {JSON.stringify(report, null, 2)}
                                        </pre>
                                    </div>
                                </div>
                            ) : (
                                <div className="glass-card p-12 text-center">
                                    <FileText size={48} className="text-gray-600 mx-auto mb-4" />
                                    <h2 className="text-xl font-bold mb-2 text-gray-400">No Report Generated</h2>
                                    <p className="text-gray-500">Configure and generate a report to see results here.</p>
                                </div>
                            )}
                        </div>
                    </div>
                </motion.div>
            </main>
        </div>
    )
}

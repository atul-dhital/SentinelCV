'use client'

import React, { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { Shield, AlertTriangle, CheckCircle, RefreshCw, PlayCircle, Copy, ImageOff, Scale, Gauge } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { dataQualityService } from '@/services/api'

interface QualityReport {
    uniqueness_score: number
    quality_score: number
    balance_score: number
    overall_health_score: number
    duplicate_count: number
    low_quality_count: number
    total_issues: number
    last_audited_at: string | null
}

interface QualityFinding {
    id: string
    finding_type: string
    severity: string
    recommendation: string | null
    confidence_score: number
}

interface AuditJob {
    id: string
    status: 'pending' | 'running' | 'completed' | 'failed'
    progress_percentage: number
    total_images: number
    findings?: QualityFinding[]
}

const DATASET_NAME = 'visitor_faces'

export default function DataQualityPage() {
    const [report, setReport] = useState<QualityReport | null>(null)
    const [loading, setLoading] = useState(true)
    const [job, setJob] = useState<AuditJob | null>(null)
    const [starting, setStarting] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

    useEffect(() => {
        fetchReport()
        return () => {
            if (pollRef.current) clearInterval(pollRef.current)
        }
    }, [])

    const fetchReport = async () => {
        setLoading(true)
        try {
            const res = await dataQualityService.getReport()
            setReport(res.data)
        } catch (err: any) {
            if (err.response?.status === 401) {
                window.location.href = '/login'
                return
            }
            console.error('Failed to load data quality report', err)
        } finally {
            setLoading(false)
        }
    }

    const pollJob = (jobId: string) => {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(async () => {
            try {
                const res = await dataQualityService.getAuditJob(jobId)
                setJob(res.data)
                if (res.data.status === 'completed' || res.data.status === 'failed') {
                    if (pollRef.current) clearInterval(pollRef.current)
                    setStarting(false)
                    if (res.data.status === 'completed') {
                        setMessage({ type: 'success', text: 'Audit complete — scores refreshed below.' })
                        fetchReport()
                    } else {
                        setMessage({ type: 'error', text: 'Audit failed. Check server logs for details.' })
                    }
                }
            } catch {
                if (pollRef.current) clearInterval(pollRef.current)
                setStarting(false)
            }
        }, 2000)
    }

    const handleStartAudit = async () => {
        setStarting(true)
        setMessage(null)
        setJob(null)
        try {
            const res = await dataQualityService.startAudit(DATASET_NAME)
            setJob(res.data)
            pollJob(res.data.id)
        } catch {
            setMessage({ type: 'error', text: 'Could not start audit' })
            setStarting(false)
        }
    }

    const scoreColor = (score: number) => {
        if (score >= 80) return 'text-green-400'
        if (score >= 60) return 'text-yellow-400'
        return 'text-red-400'
    }

    if (loading) {
        return (
            <div className="min-h-screen">
                <Navbar />
                <main className="pt-24 pb-20 px-6 container mx-auto">
                    <div className="animate-pulse space-y-4">
                        <div className="h-8 bg-gray-800 rounded w-48"></div>
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                            {[1, 2, 3, 4].map(i => (
                                <div key={i} className="h-24 bg-gray-800 rounded-xl" />
                            ))}
                        </div>
                    </div>
                </main>
            </div>
        )
    }

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-20 px-6 container mx-auto">
                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
                    <div className="flex items-center justify-between mb-10">
                        <div>
                            <h1 className="text-4xl font-extrabold mb-3 bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
                                Data Quality
                            </h1>
                            <p className="text-gray-400 text-lg">Monitor and improve the quality of your training data.</p>
                        </div>
                        <div className="flex gap-3">
                            <button
                                onClick={handleStartAudit}
                                disabled={starting}
                                className="bg-brand-500/10 hover:bg-brand-500/20 text-brand-400 px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 disabled:opacity-60"
                            >
                                {starting ? <RefreshCw size={16} className="animate-spin" /> : <PlayCircle size={16} />}
                                {starting ? 'Auditing…' : 'Run Audit'}
                            </button>
                            <button
                                onClick={fetchReport}
                                className="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                            >
                                <RefreshCw size={16} /> Refresh
                            </button>
                        </div>
                    </div>

                    {message && (
                        <div className={`mb-6 p-4 rounded-lg flex items-center gap-3 ${
                            message.type === 'success'
                                ? 'bg-green-500/10 text-green-400 border border-green-500/20'
                                : 'bg-red-500/10 text-red-400 border border-red-500/20'
                        }`}>
                            {message.type === 'success' ? <CheckCircle size={20} /> : <AlertTriangle size={20} />}
                            {message.text}
                        </div>
                    )}

                    {job && (job.status === 'pending' || job.status === 'running') && (
                        <div className="glass-card p-6 mb-8">
                            <div className="flex items-center justify-between mb-3">
                                <div className="flex items-center gap-2 text-sm text-gray-300">
                                    <RefreshCw size={16} className="animate-spin text-brand-400" />
                                    Auditing {job.total_images || 0} images…
                                </div>
                                <span className="text-sm text-gray-400">{Math.round(job.progress_percentage)}%</span>
                            </div>
                            <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-brand-500 transition-all duration-500"
                                    style={{ width: `${job.progress_percentage}%` }}
                                />
                            </div>
                        </div>
                    )}

                    {report && (
                        <>
                            {/* Score + KPI Cards */}
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
                                <motion.div
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    className="glass-card p-6 text-center"
                                >
                                    <p className="text-sm text-gray-400 mb-2">Overall Health</p>
                                    <p className={`text-4xl font-extrabold ${scoreColor(report.overall_health_score)}`}>
                                        {report.overall_health_score.toFixed(0)}%
                                    </p>
                                </motion.div>
                                {[
                                    { label: 'Uniqueness', value: report.uniqueness_score, icon: Copy, color: 'text-blue-400' },
                                    { label: 'Image Quality', value: report.quality_score, icon: ImageOff, color: 'text-green-400' },
                                    { label: 'Demographic Balance', value: report.balance_score, icon: Scale, color: 'text-purple-400' },
                                ].map((card, i) => (
                                    <motion.div
                                        key={card.label}
                                        initial={{ opacity: 0, y: 10 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        transition={{ delay: (i + 1) * 0.05 }}
                                        className="glass-card p-6"
                                    >
                                        <div className="flex items-center gap-2 mb-2">
                                            <card.icon size={16} className={card.color} />
                                            <span className="text-sm text-gray-400">{card.label}</span>
                                        </div>
                                        <p className={`text-2xl font-bold ${scoreColor(card.value)}`}>{card.value.toFixed(0)}%</p>
                                    </motion.div>
                                ))}
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
                                <div className="glass-card p-6">
                                    <div className="flex items-center gap-2 mb-2">
                                        <Copy size={16} className="text-yellow-400" />
                                        <span className="text-sm text-gray-400">Duplicate Clusters</span>
                                    </div>
                                    <p className="text-2xl font-bold">{report.duplicate_count}</p>
                                </div>
                                <div className="glass-card p-6">
                                    <div className="flex items-center gap-2 mb-2">
                                        <Gauge size={16} className="text-red-400" />
                                        <span className="text-sm text-gray-400">Low Quality Images</span>
                                    </div>
                                    <p className="text-2xl font-bold">{report.low_quality_count}</p>
                                </div>
                                <div className="glass-card p-6">
                                    <div className="flex items-center gap-2 mb-2">
                                        <AlertTriangle size={16} className="text-orange-400" />
                                        <span className="text-sm text-gray-400">Total Issues</span>
                                    </div>
                                    <p className="text-2xl font-bold">{report.total_issues}</p>
                                </div>
                            </div>

                            <p className="text-sm text-gray-500 mb-8">
                                {report.last_audited_at
                                    ? `Last audited ${new Date(report.last_audited_at).toLocaleString()}`
                                    : 'No audit has run yet — scores reflect a baseline scan. Run an audit for a full report.'}
                            </p>

                            {/* Findings from the most recent completed job */}
                            {job?.findings && job.findings.length > 0 && (
                                <div className="glass-card p-6">
                                    <div className="flex items-center gap-3 mb-4">
                                        <div className="p-2 bg-brand-500/10 rounded-lg">
                                            <Shield className="text-brand-500" size={24} />
                                        </div>
                                        <h2 className="text-xl font-bold">Findings ({job.findings.length})</h2>
                                    </div>
                                    <div className="space-y-3">
                                        {job.findings.map((finding) => (
                                            <div key={finding.id} className="flex items-start gap-3 p-3 bg-gray-900/30 rounded-lg">
                                                <AlertTriangle
                                                    size={16}
                                                    className={`shrink-0 mt-0.5 ${
                                                        finding.severity === 'high' ? 'text-red-400' : 'text-yellow-400'
                                                    }`}
                                                />
                                                <div>
                                                    <p className="text-sm text-gray-300">{finding.recommendation || finding.finding_type}</p>
                                                    <p className="text-xs text-gray-500 mt-1 uppercase tracking-wide">{finding.finding_type} · {finding.severity}</p>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </>
                    )}
                </motion.div>
            </main>
        </div>
    )
}

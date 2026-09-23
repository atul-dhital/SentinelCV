'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { motion, AnimatePresence } from 'framer-motion'
import { Lock, Server, KeyRound, ShieldCheck, FileText, CheckCircle, AlertCircle, Loader2, RefreshCw, ArrowRight, Trash2, Plus } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { complianceService, reportService, type EncryptionVerification, type RetentionPolicy } from '@/services/api'

const tabs = ['LDAP Config', 'Encryption Verification', 'Retention & GDPR', 'Audit Report'] as const
type Tab = typeof tabs[number]

export default function SecurityPage() {
    const router = useRouter()
    const [activeTab, setActiveTab] = useState<Tab>('Encryption Verification')
    const [loading, setLoading] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

    const [encryption, setEncryption] = useState<EncryptionVerification | null>(null)
    const [policies, setPolicies] = useState<RetentionPolicy[] | null>(null)
    const [newPolicy, setNewPolicy] = useState({ entity_type: 'face_data', retention_days: 365, auto_delete: false })
    const [auditForm, setAuditForm] = useState({ start_date: '', end_date: '' })

    const flash = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 5000)
    }

    const handleAuthError = (err: any) => {
        if (err.response?.status === 401) { router.push('/login'); return true }
        return false
    }

    useEffect(() => {
        if (activeTab === 'Encryption Verification') fetchEncryption()
        if (activeTab === 'Retention & GDPR') fetchPolicies()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeTab])

    const fetchEncryption = async () => {
        setLoading(true)
        try {
            const res = await complianceService.verifyEncryption()
            setEncryption(res.data)
        } catch (err: any) {
            if (!handleAuthError(err)) flash('error', err.response?.data?.detail || 'Failed to verify encryption')
        } finally { setLoading(false) }
    }

    const fetchPolicies = async () => {
        setLoading(true)
        try {
            const res = await complianceService.getRetentionPolicies()
            setPolicies(res.data)
        } catch (err: any) {
            if (!handleAuthError(err)) flash('error', err.response?.data?.detail || 'Failed to load retention policies')
        } finally { setLoading(false) }
    }

    const handleCreatePolicy = async (e: React.FormEvent) => {
        e.preventDefault()
        setLoading(true)
        try {
            await complianceService.createRetentionPolicy(newPolicy)
            flash('success', 'Retention policy saved')
            fetchPolicies()
        } catch (err: any) {
            if (!handleAuthError(err)) flash('error', err.response?.data?.detail || 'Failed to save policy')
        } finally { setLoading(false) }
    }

    const handleRunCleanup = async () => {
        setLoading(true)
        try {
            const res = await complianceService.runRetentionCleanup()
            const total = res.data.reduce((sum, r) => sum + r.records_deleted, 0)
            flash('success', `Retention cleanup complete — ${total} record(s) removed`)
            fetchPolicies()
        } catch (err: any) {
            if (!handleAuthError(err)) flash('error', err.response?.data?.detail || 'Retention cleanup failed')
        } finally { setLoading(false) }
    }

    const handleAuditReport = async (e: React.FormEvent) => {
        e.preventDefault()
        setLoading(true)
        try {
            const res = await reportService.getAuditPdf(
                auditForm.start_date && auditForm.end_date ? auditForm : undefined
            )
            const url = window.URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
            const link = document.createElement('a')
            link.href = url
            link.download = 'audit_report.pdf'
            document.body.appendChild(link)
            link.click()
            link.remove()
            window.URL.revokeObjectURL(url)
            flash('success', 'Audit report downloaded')
        } catch (err: any) {
            if (!handleAuthError(err)) flash('error', err.response?.data?.detail || 'Failed to generate report')
        } finally { setLoading(false) }
    }

    const statusColor = (status: string) => status === 'passed' ? 'green' : status === 'warning' ? 'yellow' : 'red'

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <div className="mb-8">
                    <h1 className="text-3xl font-bold flex items-center gap-3"><Lock className="w-8 h-8 text-red-400" /> Security & Compliance</h1>
                    <p className="text-gray-400 mt-2">LDAP integration, encryption verification, retention/GDPR, and audit reporting — backed by stable production routes.</p>
                </div>

                <AnimatePresence>
                    {message && (
                        <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                            className={`mb-6 p-4 rounded-xl border flex items-center gap-2 ${message.type === 'success' ? 'bg-green-500/10 border-green-500/30 text-green-300' : 'bg-red-500/10 border-red-500/30 text-red-300'}`}>
                            {message.type === 'success' ? <CheckCircle className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
                            {message.text}
                        </motion.div>
                    )}
                </AnimatePresence>

                <div className="flex gap-2 mb-8 flex-wrap">
                    {tabs.map(tab => (
                        <button key={tab} onClick={() => setActiveTab(tab)}
                            className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${activeTab === tab ? 'bg-brand-500/20 text-brand-200 border border-brand-500/30' : 'bg-white/5 text-gray-400 border border-white/10 hover:bg-white/10'}`}>
                            {tab}
                        </button>
                    ))}
                </div>

                {activeTab === 'LDAP Config' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Server className="w-5 h-5" /> LDAP / Active Directory Configuration</h2>
                        <p className="text-gray-400 mb-4">LDAP configuration, connection testing, and sync history are managed on the dedicated LDAP settings page.</p>
                        <Link href="/settings/ldap"
                            className="inline-flex items-center gap-2 px-6 py-2.5 bg-red-600 hover:bg-red-700 rounded-xl font-medium transition-colors">
                            Open LDAP Settings <ArrowRight className="w-4 h-4" />
                        </Link>
                    </motion.div>
                )}

                {activeTab === 'Encryption Verification' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-xl font-semibold flex items-center gap-2"><KeyRound className="w-5 h-5" /> Face Embedding Encryption Verification</h2>
                            <button onClick={fetchEncryption} disabled={loading} className="text-sm text-brand-400 hover:text-brand-300 flex items-center gap-1 disabled:opacity-50">
                                {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />} Refresh
                            </button>
                        </div>
                        {encryption ? (
                            <div className="space-y-4">
                                <div className={`bg-${statusColor(encryption.verification_status)}-500/10 border border-${statusColor(encryption.verification_status)}-500/20 rounded-xl p-4`}>
                                    <span className={`text-xs px-2 py-0.5 rounded-full bg-${statusColor(encryption.verification_status)}-500/20 text-${statusColor(encryption.verification_status)}-300 capitalize font-medium`}>
                                        {encryption.verification_status}
                                    </span>
                                </div>
                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                                    <div className="bg-black/40 rounded-xl p-4">
                                        <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Total embeddings</p>
                                        <p className="text-2xl font-bold">{encryption.total_embeddings}</p>
                                    </div>
                                    <div className="bg-black/40 rounded-xl p-4">
                                        <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Encrypted</p>
                                        <p className="text-2xl font-bold text-green-400">{encryption.encrypted_count}</p>
                                    </div>
                                    <div className="bg-black/40 rounded-xl p-4">
                                        <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Unencrypted</p>
                                        <p className="text-2xl font-bold text-red-400">{encryption.unencrypted_count}</p>
                                    </div>
                                </div>
                            </div>
                        ) : (
                            <div className="text-center py-12 text-gray-500">{loading ? 'Verifying...' : 'No data'}</div>
                        )}
                    </motion.div>
                )}

                {activeTab === 'Retention & GDPR' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
                        <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
                            <div className="flex items-center justify-between mb-4">
                                <h2 className="text-xl font-semibold flex items-center gap-2"><ShieldCheck className="w-5 h-5" /> Retention Policies</h2>
                                <button onClick={handleRunCleanup} disabled={loading}
                                    className="text-sm px-3 py-1.5 bg-red-600 hover:bg-red-700 rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5">
                                    <Trash2 className="w-3.5 h-3.5" /> Run cleanup now
                                </button>
                            </div>
                            {policies && policies.length > 0 ? (
                                <div className="space-y-2 mb-4">
                                    {policies.map(p => (
                                        <div key={p.id} className="flex items-center justify-between bg-black/40 rounded-xl p-3 text-sm">
                                            <span className="font-medium">{p.entity_type}</span>
                                            <span className="text-gray-400">{p.retention_days} days{p.auto_delete ? ' · auto-delete' : ''}</span>
                                            <span className="text-gray-500 text-xs">{p.last_cleanup_at ? `Last cleanup: ${new Date(p.last_cleanup_at).toLocaleDateString()}` : 'Never cleaned'}</span>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <div className="text-center py-6 text-gray-500 mb-4">{loading ? 'Loading...' : 'No retention policies configured'}</div>
                            )}
                            <form onSubmit={handleCreatePolicy} className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
                                <div>
                                    <label className="block text-xs text-gray-400 mb-1">Entity type</label>
                                    <input value={newPolicy.entity_type} onChange={e => setNewPolicy({ ...newPolicy, entity_type: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-white text-sm" placeholder="face_data" />
                                </div>
                                <div>
                                    <label className="block text-xs text-gray-400 mb-1">Retention days</label>
                                    <input type="number" min={1} value={newPolicy.retention_days}
                                        onChange={e => setNewPolicy({ ...newPolicy, retention_days: parseInt(e.target.value) || 1 })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-white text-sm" />
                                </div>
                                <label className="flex items-center gap-2 text-sm text-gray-400">
                                    <input type="checkbox" checked={newPolicy.auto_delete} onChange={e => setNewPolicy({ ...newPolicy, auto_delete: e.target.checked })} />
                                    Auto-delete
                                </label>
                                <button type="submit" disabled={loading}
                                    className="px-4 py-2 bg-white/10 hover:bg-white/20 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center justify-center gap-1.5 text-sm">
                                    <Plus className="w-4 h-4" /> Add policy
                                </button>
                            </form>
                        </div>
                        <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
                            <h2 className="text-lg font-semibold mb-2">GDPR export / delete</h2>
                            <p className="text-gray-400 text-sm mb-3">Per-visitor GDPR export and deletion is handled from each visitor's detail page, and from the dedicated consent portal.</p>
                            <Link href="/settings/consent" className="inline-flex items-center gap-2 text-sm text-brand-400 hover:text-brand-300">
                                Open Consent Portal <ArrowRight className="w-3.5 h-3.5" />
                            </Link>
                        </div>
                    </motion.div>
                )}

                {activeTab === 'Audit Report' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><FileText className="w-5 h-5" /> Generate Audit Report</h2>
                        <form onSubmit={handleAuditReport} className="space-y-4">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Start Date (optional)</label>
                                    <input type="date" value={auditForm.start_date} onChange={e => setAuditForm({ ...auditForm, start_date: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">End Date (optional)</label>
                                    <input type="date" value={auditForm.end_date} onChange={e => setAuditForm({ ...auditForm, end_date: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" />
                                </div>
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-red-600 hover:bg-red-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />} Download PDF
                            </button>
                        </form>
                    </motion.div>
                )}
            </main>
        </div>
    )
}

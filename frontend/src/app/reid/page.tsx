'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { GitBranch, MapPin, ArrowRight, CheckCircle, AlertCircle, Loader2, Activity, Eye } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { reidService } from '@/services/api'

const tabs = ['Track Transition', 'Movement Summary'] as const
type Tab = typeof tabs[number]

export default function ReIDPage() {
    const router = useRouter()
    const [activeTab, setActiveTab] = useState<Tab>('Track Transition')
    const [loading, setLoading] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [result, setResult] = useState<any>(null)

    const [transitionForm, setTransitionForm] = useState({
        visitor_id: '', from_camera_id: '', to_camera_id: '',
        from_detection_log_id: '', to_detection_log_id: '',
        transition_time_seconds: 15.0, reid_confidence: 0.85,
    })
    const [summaryVisitorId, setSummaryVisitorId] = useState('')

    const flash = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 5000)
    }

    const handleTrackTransition = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!transitionForm.visitor_id || !transitionForm.from_camera_id || !transitionForm.to_camera_id) {
            flash('error', 'Visitor ID and both camera IDs are required'); return
        }
        setLoading(true); setResult(null)
        try {
            const res = await reidService.trackTransition(transitionForm)
            setResult(res.data)
            flash('success', 'Camera transition recorded')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Failed to track transition')
        } finally { setLoading(false) }
    }

    const handleGetSummary = async () => {
        if (!summaryVisitorId) { flash('error', 'Visitor ID required'); return }
        setLoading(true); setResult(null)
        try {
            const res = await reidService.getMovementSummary(summaryVisitorId)
            setResult(res.data)
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Failed to fetch movement summary')
        } finally { setLoading(false) }
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <div className="mb-8">
                    <h1 className="text-3xl font-bold flex items-center gap-3"><GitBranch className="w-8 h-8 text-cyan-400" /> Cross-Camera Re-Identification</h1>
                    <p className="text-gray-400 mt-2">Track visitors across multiple cameras and visualize movement patterns.</p>
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

                <div className="flex gap-2 mb-8">
                    {tabs.map(tab => (
                        <button key={tab} onClick={() => { setActiveTab(tab); setResult(null) }}
                            className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${activeTab === tab ? 'bg-brand-500/20 text-brand-200 border border-brand-500/30' : 'bg-white/5 text-gray-400 border border-white/10 hover:bg-white/10'}`}>
                            {tab}
                        </button>
                    ))}
                </div>

                {activeTab === 'Track Transition' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><MapPin className="w-5 h-5" /> Record Camera Transition</h2>
                        <form onSubmit={handleTrackTransition} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Visitor ID</label>
                                <input value={transitionForm.visitor_id} onChange={e => setTransitionForm({ ...transitionForm, visitor_id: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">From Camera ID</label>
                                    <input value={transitionForm.from_camera_id} onChange={e => setTransitionForm({ ...transitionForm, from_camera_id: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">To Camera ID</label>
                                    <input value={transitionForm.to_camera_id} onChange={e => setTransitionForm({ ...transitionForm, to_camera_id: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                                </div>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">From Detection Log ID</label>
                                    <input value={transitionForm.from_detection_log_id} onChange={e => setTransitionForm({ ...transitionForm, from_detection_log_id: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">To Detection Log ID</label>
                                    <input value={transitionForm.to_detection_log_id} onChange={e => setTransitionForm({ ...transitionForm, to_detection_log_id: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                                </div>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Transition Time (seconds)</label>
                                    <input type="number" step={0.1} value={transitionForm.transition_time_seconds}
                                        onChange={e => setTransitionForm({ ...transitionForm, transition_time_seconds: parseFloat(e.target.value) || 0 })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Re-ID Confidence</label>
                                    <input type="number" step={0.01} min={0} max={1} value={transitionForm.reid_confidence}
                                        onChange={e => setTransitionForm({ ...transitionForm, reid_confidence: parseFloat(e.target.value) || 0 })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" />
                                </div>
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-cyan-600 hover:bg-cyan-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />} Track Transition
                            </button>
                        </form>
                    </motion.div>
                )}

                {activeTab === 'Movement Summary' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Eye className="w-5 h-5" /> Visitor Movement Path</h2>
                        <div className="flex gap-3 mb-6">
                            <input value={summaryVisitorId} onChange={e => setSummaryVisitorId(e.target.value)}
                                className="flex-1 bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="Enter Visitor ID" />
                            <button onClick={handleGetSummary} disabled={loading}
                                className="px-6 py-2.5 bg-cyan-600 hover:bg-cyan-700 rounded-xl font-medium transition-colors disabled:opacity-50">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Get Summary'}
                            </button>
                        </div>

                        {result?.movements && Array.isArray(result.movements) && (
                            <div className="space-y-3">
                                {result.movements.map((m: any, i: number) => (
                                    <div key={i} className="flex items-center gap-3 bg-black/30 rounded-xl p-3">
                                        <div className="flex items-center gap-2 text-cyan-300">
                                            <MapPin className="w-4 h-4" />
                                            <span className="text-sm font-mono">{m.from_camera_id?.slice(0, 8)}...</span>
                                        </div>
                                        <ArrowRight className="w-4 h-4 text-gray-500" />
                                        <div className="flex items-center gap-2 text-cyan-300">
                                            <MapPin className="w-4 h-4" />
                                            <span className="text-sm font-mono">{m.to_camera_id?.slice(0, 8)}...</span>
                                        </div>
                                        <span className="ml-auto text-sm text-gray-400">{m.transition_count} transitions</span>
                                        <span className="text-sm text-gray-500">{(m.average_confidence * 100).toFixed(0)}% conf</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </motion.div>
                )}

                {result && !result.movements && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h3 className="text-lg font-semibold mb-3 flex items-center gap-2"><Activity className="w-5 h-5 text-brand-400" /> Result</h3>
                        <pre className="bg-black/40 p-4 rounded-xl text-sm text-gray-300 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>
                    </motion.div>
                )}
            </main>
        </div>
    )
}

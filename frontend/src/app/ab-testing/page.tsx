'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { FlaskConical, Play, BarChart3, Trophy, CheckCircle, AlertCircle, Loader2, Activity } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { abTestingService } from '@/services/api'

const tabs = ['Start Experiment', 'View Results'] as const
type Tab = typeof tabs[number]

export default function ABTestingPage() {
    const router = useRouter()
    const [activeTab, setActiveTab] = useState<Tab>('Start Experiment')
    const [loading, setLoading] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [result, setResult] = useState<any>(null)

    const [experimentForm, setExperimentForm] = useState({
        name: '', model_a_id: '', model_b_id: '', traffic_split_percent: 50,
    })
    const [resultsId, setResultsId] = useState('')

    const flash = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 5000)
    }

    const handleStartExperiment = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!experimentForm.name || !experimentForm.model_a_id || !experimentForm.model_b_id) {
            flash('error', 'Name and both model IDs are required'); return
        }
        setLoading(true); setResult(null)
        try {
            const res = await abTestingService.startExperiment(experimentForm)
            setResult(res.data)
            flash('success', `Experiment started: ${res.data.experiment_id || 'created'}`)
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Failed to start experiment')
        } finally { setLoading(false) }
    }

    const handleGetResults = async () => {
        if (!resultsId) { flash('error', 'Enter Experiment ID'); return }
        setLoading(true); setResult(null)
        try {
            const res = await abTestingService.getResults(resultsId)
            setResult(res.data)
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Failed to fetch results')
        } finally { setLoading(false) }
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <div className="mb-8">
                    <h1 className="text-3xl font-bold flex items-center gap-3"><FlaskConical className="w-8 h-8 text-emerald-400" /> A/B Testing & Model Versioning</h1>
                    <p className="text-gray-400 mt-2">Compare model versions with controlled traffic splitting and statistical significance testing.</p>
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

                {activeTab === 'Start Experiment' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Play className="w-5 h-5" /> Start A/B Test</h2>
                        <form onSubmit={handleStartExperiment} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Experiment Name</label>
                                <input value={experimentForm.name} onChange={e => setExperimentForm({ ...experimentForm, name: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="e.g., ArcFace v2 vs AdaFace" />
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Model A ID (Control)</label>
                                    <input value={experimentForm.model_a_id} onChange={e => setExperimentForm({ ...experimentForm, model_a_id: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Model B ID (Challenger)</label>
                                    <input value={experimentForm.model_b_id} onChange={e => setExperimentForm({ ...experimentForm, model_b_id: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                                </div>
                            </div>
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Traffic Split (% to Model B)</label>
                                <input type="range" min={5} max={95} step={5} value={experimentForm.traffic_split_percent}
                                    onChange={e => setExperimentForm({ ...experimentForm, traffic_split_percent: parseInt(e.target.value) })}
                                    className="w-full" />
                                <div className="flex justify-between text-sm text-gray-500 mt-1">
                                    <span>Model A: {100 - experimentForm.traffic_split_percent}%</span>
                                    <span>Model B: {experimentForm.traffic_split_percent}%</span>
                                </div>
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FlaskConical className="w-4 h-4" />} Start Experiment
                            </button>
                        </form>
                    </motion.div>
                )}

                {activeTab === 'View Results' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><BarChart3 className="w-5 h-5" /> Experiment Results</h2>
                        <div className="flex gap-3 mb-6">
                            <input value={resultsId} onChange={e => setResultsId(e.target.value)}
                                className="flex-1 bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="Enter Experiment ID" />
                            <button onClick={handleGetResults} disabled={loading}
                                className="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-700 rounded-xl font-medium transition-colors disabled:opacity-50">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Get Results'}
                            </button>
                        </div>
                    </motion.div>
                )}

                {result && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h3 className="text-lg font-semibold mb-3 flex items-center gap-2"><Activity className="w-5 h-5 text-emerald-400" /> Result</h3>
                        {result.winner && (
                            <div className="mb-4 p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex items-center gap-3">
                                <Trophy className="w-6 h-6 text-emerald-400" />
                                <div>
                                    <div className="font-semibold text-emerald-300">Winner: Model {result.winner}</div>
                                    {result.p_value && <div className="text-sm text-gray-400">p-value: {result.p_value.toFixed(4)} | Significant: {result.is_significant ? 'Yes' : 'No'}</div>}
                                </div>
                            </div>
                        )}
                        {result.model_a_stats && result.model_b_stats && (
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                                {['model_a_stats', 'model_b_stats'].map((key, i) => (
                                    <div key={key} className="bg-black/30 rounded-xl p-4">
                                        <div className="font-semibold mb-2 text-gray-300">Model {i === 0 ? 'A' : 'B'}</div>
                                        <div className="space-y-1 text-sm">
                                            <div className="flex justify-between"><span className="text-gray-500">Accuracy</span><span>{((result[key].accuracy || 0) * 100).toFixed(1)}%</span></div>
                                            <div className="flex justify-between"><span className="text-gray-500">Latency</span><span>{(result[key].avg_latency_ms || 0).toFixed(0)}ms</span></div>
                                            <div className="flex justify-between"><span className="text-gray-500">Requests</span><span>{result[key].total_requests || 0}</span></div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                        <pre className="bg-black/40 p-4 rounded-xl text-sm text-gray-300 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>
                    </motion.div>
                )}
            </main>
        </div>
    )
}

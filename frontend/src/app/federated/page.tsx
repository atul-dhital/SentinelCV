'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Network, Play, Upload, BarChart3, CheckCircle, AlertCircle, Loader2, Users, Activity } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { federatedService } from '@/services/api'

const tabs = ['Start Round', 'Submit Update', 'Round Status'] as const
type Tab = typeof tabs[number]

export default function FederatedPage() {
    const router = useRouter()
    const [activeTab, setActiveTab] = useState<Tab>('Start Round')
    const [loading, setLoading] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [result, setResult] = useState<any>(null)

    const [roundForm, setRoundForm] = useState({ model_type: 'face_recognition', num_participants: 5 })
    const [updateForm, setUpdateForm] = useState({ round_id: '', participant_id: '', local_accuracy: 0.85, num_samples: 1000 })
    const [statusRoundId, setStatusRoundId] = useState('')

    const flash = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 5000)
    }

    const handleStartRound = async (e: React.FormEvent) => {
        e.preventDefault()
        setLoading(true); setResult(null)
        try {
            const res = await federatedService.startRound(roundForm)
            setResult(res.data)
            flash('success', `Federated round started: ${res.data.round_id}`)
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Failed to start round')
        } finally { setLoading(false) }
    }

    const handleSubmitUpdate = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!updateForm.round_id) { flash('error', 'Round ID is required'); return }
        setLoading(true); setResult(null)
        try {
            const res = await federatedService.submitUpdate(updateForm)
            setResult(res.data)
            flash('success', 'Client update submitted')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Failed to submit update')
        } finally { setLoading(false) }
    }

    const handleGetStatus = async () => {
        if (!statusRoundId) { flash('error', 'Enter a Round ID'); return }
        setLoading(true); setResult(null)
        try {
            const res = await federatedService.getRoundStatus(statusRoundId)
            setResult(res.data)
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Failed to fetch status')
        } finally { setLoading(false) }
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <div className="mb-8">
                    <h1 className="text-3xl font-bold flex items-center gap-3"><Network className="w-8 h-8 text-brand-400" /> Federated Learning</h1>
                    <p className="text-gray-400 mt-2">Train models across organizations without sharing raw data using Federated Averaging.</p>
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

                {/* Tabs */}
                <div className="flex gap-2 mb-8">
                    {tabs.map(tab => (
                        <button key={tab} onClick={() => { setActiveTab(tab); setResult(null) }}
                            className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${activeTab === tab ? 'bg-brand-500/20 text-brand-200 border border-brand-500/30' : 'bg-white/5 text-gray-400 border border-white/10 hover:bg-white/10'}`}>
                            {tab}
                        </button>
                    ))}
                </div>

                {/* Start Round Tab */}
                {activeTab === 'Start Round' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Play className="w-5 h-5" /> Start Federated Round</h2>
                        <form onSubmit={handleStartRound} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Model Type</label>
                                <select value={roundForm.model_type} onChange={e => setRoundForm({ ...roundForm, model_type: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white">
                                    <option value="face_recognition">Face Recognition</option>
                                    <option value="liveness_detection">Liveness Detection</option>
                                    <option value="emotion_detection">Emotion Detection</option>
                                </select>
                            </div>
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Number of Participants</label>
                                <input type="number" min={2} max={100} value={roundForm.num_participants}
                                    onChange={e => setRoundForm({ ...roundForm, num_participants: parseInt(e.target.value) || 5 })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" />
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-brand-500 hover:bg-brand-600 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />} Start Round
                            </button>
                        </form>
                    </motion.div>
                )}

                {/* Submit Update Tab */}
                {activeTab === 'Submit Update' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Upload className="w-5 h-5" /> Submit Client Update</h2>
                        <form onSubmit={handleSubmitUpdate} className="space-y-4">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Round ID</label>
                                    <input value={updateForm.round_id} onChange={e => setUpdateForm({ ...updateForm, round_id: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Participant ID</label>
                                    <input value={updateForm.participant_id} onChange={e => setUpdateForm({ ...updateForm, participant_id: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="org-001" />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Local Accuracy</label>
                                    <input type="number" step={0.01} min={0} max={1} value={updateForm.local_accuracy}
                                        onChange={e => setUpdateForm({ ...updateForm, local_accuracy: parseFloat(e.target.value) || 0 })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Num Samples</label>
                                    <input type="number" min={1} value={updateForm.num_samples}
                                        onChange={e => setUpdateForm({ ...updateForm, num_samples: parseInt(e.target.value) || 0 })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" />
                                </div>
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-brand-500 hover:bg-brand-600 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />} Submit Update
                            </button>
                        </form>
                    </motion.div>
                )}

                {/* Round Status Tab */}
                {activeTab === 'Round Status' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><BarChart3 className="w-5 h-5" /> Round Status</h2>
                        <div className="flex gap-3 mb-6">
                            <input value={statusRoundId} onChange={e => setStatusRoundId(e.target.value)}
                                className="flex-1 bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="Enter Round ID" />
                            <button onClick={handleGetStatus} disabled={loading}
                                className="px-6 py-2.5 bg-brand-500 hover:bg-brand-600 rounded-xl font-medium transition-colors disabled:opacity-50">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Get Status'}
                            </button>
                        </div>
                    </motion.div>
                )}

                {/* Results */}
                {result && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h3 className="text-lg font-semibold mb-3 flex items-center gap-2"><Activity className="w-5 h-5 text-brand-400" /> Result</h3>
                        <pre className="bg-black/40 p-4 rounded-xl text-sm text-gray-300 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>
                    </motion.div>
                )}
            </main>
        </div>
    )
}

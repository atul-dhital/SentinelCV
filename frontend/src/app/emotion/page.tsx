'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Smile, Camera, Video, BarChart3, CheckCircle, AlertCircle, Loader2, Activity, FlaskRound } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { emotionService } from '@/services/api'

const isUnavailable = (err: any) => err?.response?.status === 404

const tabs = ['Detect Emotion', 'Detect Action', 'Emotion Summary'] as const
type Tab = typeof tabs[number]

const EMOTIONS = ['neutral', 'happy', 'sad', 'angry', 'fearful', 'disgusted', 'surprised']
const EMOTION_COLORS: Record<string, string> = {
    neutral: 'bg-gray-500', happy: 'bg-yellow-500', sad: 'bg-blue-500',
    angry: 'bg-red-500', fearful: 'bg-purple-500', disgusted: 'bg-green-500', surprised: 'bg-orange-500',
}

export default function EmotionPage() {
    const router = useRouter()
    const [activeTab, setActiveTab] = useState<Tab>('Detect Emotion')
    const [loading, setLoading] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [result, setResult] = useState<any>(null)

    const [emotionForm, setEmotionForm] = useState({ detection_log_id: '', image_path: '' })
    const [actionForm, setActionForm] = useState({ detection_log_id: '', video_path: '' })
    const [summaryForm, setSummaryForm] = useState({ visitor_id: '', days: 7 })
    const [unavailable, setUnavailable] = useState(false)

    const flash = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 5000)
    }

    const handleDetectEmotion = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!emotionForm.detection_log_id || !emotionForm.image_path) { flash('error', 'All fields required'); return }
        setLoading(true); setResult(null)
        try {
            const res = await emotionService.detectEmotion(emotionForm)
            setResult(res.data)
            flash('success', `Dominant emotion: ${res.data.dominant_emotion || 'detected'}`)
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            if (isUnavailable(err)) { setUnavailable(true); flash('error', 'Emotion recognition is not enabled in this environment.'); return }
            flash('error', err.response?.data?.detail || 'Detection failed')
        } finally { setLoading(false) }
    }

    const handleDetectAction = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!actionForm.detection_log_id || !actionForm.video_path) { flash('error', 'All fields required'); return }
        setLoading(true); setResult(null)
        try {
            const res = await emotionService.detectAction(actionForm)
            setResult(res.data)
            flash('success', 'Actions detected successfully')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            if (isUnavailable(err)) { setUnavailable(true); flash('error', 'Action recognition is not enabled in this environment.'); return }
            flash('error', err.response?.data?.detail || 'Action detection failed')
        } finally { setLoading(false) }
    }

    const handleGetSummary = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!summaryForm.visitor_id) { flash('error', 'Visitor ID required'); return }
        setLoading(true); setResult(null)
        try {
            const res = await emotionService.getSummary(summaryForm.visitor_id, summaryForm.days)
            setResult(res.data)
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            if (isUnavailable(err)) { setUnavailable(true); flash('error', 'Emotion recognition is not enabled in this environment.'); return }
            flash('error', err.response?.data?.detail || 'Failed to fetch summary')
        } finally { setLoading(false) }
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <div className="mb-8">
                    <h1 className="text-3xl font-bold flex items-center gap-3">
                        <Smile className="w-8 h-8 text-yellow-400" /> Emotion & Action Recognition
                        <span className="text-[10px] font-black uppercase tracking-widest text-amber-400 bg-amber-400/10 px-2 py-1 rounded-full border border-amber-400/20">Experimental</span>
                    </h1>
                    <p className="text-gray-400 mt-2">Detect facial emotions (7-class), gestures, and compute behavioral trajectories.</p>
                </div>

                <div className="mb-6 p-4 rounded-xl border bg-amber-500/10 border-amber-500/20 text-amber-200 flex items-start gap-2 text-sm">
                    <FlaskRound className="w-4 h-4 mt-0.5 shrink-0" />
                    <span>This module requires <code className="bg-black/30 px-1.5 py-0.5 rounded">ENABLE_PHASE3_FEATURES=1</code> on the backend and is disabled by default in production. Actions below will fail with an unavailable state if the flag is off.</span>
                </div>

                {unavailable && (
                    <div className="mb-6 p-4 rounded-xl border bg-red-500/10 border-red-500/30 text-red-200 text-sm">
                        Backend reports this feature as unavailable (404) — <code className="bg-black/30 px-1.5 py-0.5 rounded">ENABLE_PHASE3_FEATURES</code> is likely off in this environment. Contact an administrator to enable it, or use a supported core feature instead.
                    </div>
                )}

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

                {activeTab === 'Detect Emotion' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Camera className="w-5 h-5" /> Detect Emotion from Image</h2>
                        <form onSubmit={handleDetectEmotion} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Detection Log ID</label>
                                <input value={emotionForm.detection_log_id} onChange={e => setEmotionForm({ ...emotionForm, detection_log_id: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                            </div>
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Image Path</label>
                                <input value={emotionForm.image_path} onChange={e => setEmotionForm({ ...emotionForm, image_path: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="/path/to/face.jpg" />
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-yellow-600 hover:bg-yellow-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Smile className="w-4 h-4" />} Detect Emotion
                            </button>
                        </form>
                    </motion.div>
                )}

                {activeTab === 'Detect Action' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Video className="w-5 h-5" /> Detect Action from Video</h2>
                        <form onSubmit={handleDetectAction} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Detection Log ID</label>
                                <input value={actionForm.detection_log_id} onChange={e => setActionForm({ ...actionForm, detection_log_id: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                            </div>
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Video Path</label>
                                <input value={actionForm.video_path} onChange={e => setActionForm({ ...actionForm, video_path: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="/path/to/video.mp4" />
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-yellow-600 hover:bg-yellow-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Video className="w-4 h-4" />} Detect Action
                            </button>
                        </form>
                    </motion.div>
                )}

                {activeTab === 'Emotion Summary' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><BarChart3 className="w-5 h-5" /> Emotion Summary</h2>
                        <form onSubmit={handleGetSummary} className="space-y-4">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Visitor ID</label>
                                    <input value={summaryForm.visitor_id} onChange={e => setSummaryForm({ ...summaryForm, visitor_id: e.target.value })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1">Days</label>
                                    <input type="number" min={1} max={365} value={summaryForm.days}
                                        onChange={e => setSummaryForm({ ...summaryForm, days: parseInt(e.target.value) || 7 })}
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" />
                                </div>
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-yellow-600 hover:bg-yellow-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />} Get Summary
                            </button>
                        </form>
                    </motion.div>
                )}

                {/* Emotion bar chart when result has emotions */}
                {result?.emotions && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h3 className="text-lg font-semibold mb-4">Emotion Distribution</h3>
                        <div className="space-y-3">
                            {EMOTIONS.map(emotion => {
                                const value = result.emotions[emotion] ?? 0
                                return (
                                    <div key={emotion} className="flex items-center gap-3">
                                        <span className="w-24 text-sm text-gray-400 capitalize">{emotion}</span>
                                        <div className="flex-1 bg-black/40 rounded-full h-6 overflow-hidden">
                                            <div className={`h-full ${EMOTION_COLORS[emotion]} rounded-full transition-all`} style={{ width: `${(value * 100).toFixed(0)}%` }} />
                                        </div>
                                        <span className="w-14 text-right text-sm text-gray-300">{(value * 100).toFixed(1)}%</span>
                                    </div>
                                )
                            })}
                        </div>
                    </motion.div>
                )}

                {result && !result.emotions && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h3 className="text-lg font-semibold mb-3 flex items-center gap-2"><Activity className="w-5 h-5 text-brand-400" /> Result</h3>
                        <pre className="bg-black/40 p-4 rounded-xl text-sm text-gray-300 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>
                    </motion.div>
                )}
            </main>
        </div>
    )
}

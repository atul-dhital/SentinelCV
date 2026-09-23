'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Layers, Send, Settings2, GitCompare, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { multimodalService } from '@/services/api'

const tabs = ['Extract', 'Fusion Config', 'Compare'] as const
type Tab = typeof tabs[number]

export default function MultimodalPage() {
    const router = useRouter()
    const [activeTab, setActiveTab] = useState<Tab>('Extract')
    const [loading, setLoading] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [result, setResult] = useState<any>(null)

    // Extract form
    const [extractForm, setExtractForm] = useState({
        visitor_id: '',
        face_image_path: '',
        audio_path: '',
        text: '',
    })

    // Fusion config form
    const [fusionForm, setFusionForm] = useState({
        face_weight: 0.5,
        voice_weight: 0.3,
        text_weight: 0.2,
        strategy: 'weighted_average',
    })

    // Compare form
    const [compareForm, setCompareForm] = useState({
        id1: '',
        id2: '',
    })

    const flash = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 5000)
    }

    const handleExtract = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!extractForm.visitor_id) { flash('error', 'Visitor ID is required'); return }
        setLoading(true)
        setResult(null)
        try {
            const res = await multimodalService.extract(extractForm)
            setResult(res.data)
            flash('success', 'Multimodal features extracted successfully')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Extraction failed')
        } finally {
            setLoading(false)
        }
    }

    const handleFusionConfig = async (e: React.FormEvent) => {
        e.preventDefault()
        setLoading(true)
        setResult(null)
        try {
            const res = await multimodalService.configureFusion({
                face_weight: fusionForm.face_weight,
                audio_weight: fusionForm.voice_weight,
                text_weight: fusionForm.text_weight,
                sensor_weight: 0.0,
                strategy: fusionForm.strategy,
            })
            setResult(res.data)
            flash('success', 'Fusion configuration updated')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Configuration failed')
        } finally {
            setLoading(false)
        }
    }

    const handleCompare = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!compareForm.id1 || !compareForm.id2) { flash('error', 'Both IDs are required'); return }
        setLoading(true)
        setResult(null)
        try {
            const res = await multimodalService.compare(compareForm.id1, compareForm.id2)
            setResult(res.data)
            flash('success', 'Comparison complete')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Comparison failed')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
                    {/* Header */}
                    <div className="flex items-center gap-4 mb-8">
                        <div className="w-14 h-14 bg-gradient-to-br from-violet-500 to-purple-700 rounded-2xl flex items-center justify-center shadow-lg shadow-violet-500/20">
                            <Layers size={28} className="text-white" />
                        </div>
                        <div>
                            <h1 className="text-3xl font-bold tracking-tight">Multimodal Learning</h1>
                            <p className="text-gray-400 mt-1">Extract, fuse, and compare multimodal biometric features</p>
                        </div>
                    </div>

                    {/* Message */}
                    <AnimatePresence>
                        {message && (
                            <motion.div
                                initial={{ opacity: 0, y: -10 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: -10 }}
                                className={`mb-6 p-4 rounded-xl border flex items-center gap-3 ${message.type === 'success' ? 'bg-green-500/10 border-green-500/20 text-green-300' : 'bg-red-500/10 border-red-500/20 text-red-300'}`}
                            >
                                {message.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
                                {message.text}
                            </motion.div>
                        )}
                    </AnimatePresence>

                    {/* Tabs */}
                    <div className="flex gap-2 mb-8">
                        {tabs.map((tab) => (
                            <button
                                key={tab}
                                onClick={() => { setActiveTab(tab); setResult(null) }}
                                className={`px-5 py-2.5 rounded-xl text-sm font-medium transition-all ${activeTab === tab ? 'bg-violet-500/20 text-violet-300 border border-violet-500/30' : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'}`}
                            >
                                {tab}
                            </button>
                        ))}
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                        {/* Form Panel */}
                        <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
                            {activeTab === 'Extract' && (
                                <form onSubmit={handleExtract} className="space-y-5">
                                    <h2 className="text-lg font-semibold flex items-center gap-2"><Send size={18} /> Extract Embeddings</h2>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Visitor ID *</label>
                                        <input type="text" value={extractForm.visitor_id} onChange={(e) => setExtractForm({ ...extractForm, visitor_id: e.target.value })} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500/50 transition-colors" placeholder="Enter visitor ID" required />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Face Image Path</label>
                                        <input type="text" value={extractForm.face_image_path} onChange={(e) => setExtractForm({ ...extractForm, face_image_path: e.target.value })} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500/50 transition-colors" placeholder="/path/to/face.jpg" />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Audio Path</label>
                                        <input type="text" value={extractForm.audio_path} onChange={(e) => setExtractForm({ ...extractForm, audio_path: e.target.value })} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500/50 transition-colors" placeholder="/path/to/voice.wav" />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Text</label>
                                        <textarea value={extractForm.text} onChange={(e) => setExtractForm({ ...extractForm, text: e.target.value })} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500/50 transition-colors h-24 resize-none" placeholder="Optional text data..." />
                                    </div>
                                    <button type="submit" disabled={loading} className="w-full py-3 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 rounded-xl font-medium transition-colors flex items-center justify-center gap-2">
                                        {loading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
                                        Extract Features
                                    </button>
                                </form>
                            )}

                            {activeTab === 'Fusion Config' && (
                                <form onSubmit={handleFusionConfig} className="space-y-5">
                                    <h2 className="text-lg font-semibold flex items-center gap-2"><Settings2 size={18} /> Fusion Configuration</h2>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Face Weight: {fusionForm.face_weight}</label>
                                        <input type="range" min="0" max="1" step="0.05" value={fusionForm.face_weight} onChange={(e) => setFusionForm({ ...fusionForm, face_weight: parseFloat(e.target.value) })} className="w-full accent-violet-500" />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Voice Weight: {fusionForm.voice_weight}</label>
                                        <input type="range" min="0" max="1" step="0.05" value={fusionForm.voice_weight} onChange={(e) => setFusionForm({ ...fusionForm, voice_weight: parseFloat(e.target.value) })} className="w-full accent-violet-500" />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Text Weight: {fusionForm.text_weight}</label>
                                        <input type="range" min="0" max="1" step="0.05" value={fusionForm.text_weight} onChange={(e) => setFusionForm({ ...fusionForm, text_weight: parseFloat(e.target.value) })} className="w-full accent-violet-500" />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Fusion Strategy</label>
                                        <select value={fusionForm.strategy} onChange={(e) => setFusionForm({ ...fusionForm, strategy: e.target.value })} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white focus:outline-none focus:border-violet-500/50 transition-colors">
                                            <option value="weighted_average">Weighted Average</option>
                                            <option value="concatenation">Concatenation</option>
                                            <option value="attention">Attention-Based</option>
                                            <option value="bilinear">Bilinear Fusion</option>
                                        </select>
                                    </div>
                                    <button type="submit" disabled={loading} className="w-full py-3 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 rounded-xl font-medium transition-colors flex items-center justify-center gap-2">
                                        {loading ? <Loader2 size={18} className="animate-spin" /> : <Settings2 size={18} />}
                                        Save Configuration
                                    </button>
                                </form>
                            )}

                            {activeTab === 'Compare' && (
                                <form onSubmit={handleCompare} className="space-y-5">
                                    <h2 className="text-lg font-semibold flex items-center gap-2"><GitCompare size={18} /> Compare Embeddings</h2>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Visitor / Embedding ID 1 *</label>
                                        <input type="text" value={compareForm.id1} onChange={(e) => setCompareForm({ ...compareForm, id1: e.target.value })} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500/50 transition-colors" placeholder="First ID" required />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Visitor / Embedding ID 2 *</label>
                                        <input type="text" value={compareForm.id2} onChange={(e) => setCompareForm({ ...compareForm, id2: e.target.value })} className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500/50 transition-colors" placeholder="Second ID" required />
                                    </div>
                                    <button type="submit" disabled={loading} className="w-full py-3 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 rounded-xl font-medium transition-colors flex items-center justify-center gap-2">
                                        {loading ? <Loader2 size={18} className="animate-spin" /> : <GitCompare size={18} />}
                                        Compare
                                    </button>
                                </form>
                            )}
                        </div>

                        {/* Results Panel */}
                        <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
                            <h2 className="text-lg font-semibold mb-4">Results</h2>
                            {loading ? (
                                <div className="flex items-center justify-center py-16">
                                    <Loader2 size={32} className="animate-spin text-violet-400" />
                                </div>
                            ) : result ? (
                                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
                                    {result.similarity_score !== undefined && (
                                        <div className="bg-violet-500/10 border border-violet-500/20 rounded-xl p-4 text-center">
                                            <p className="text-sm text-gray-400 mb-1">Similarity Score</p>
                                            <p className="text-4xl font-bold text-violet-300">{(result.similarity_score * 100).toFixed(1)}%</p>
                                        </div>
                                    )}
                                    {result.embedding_id && (
                                        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                                            <p className="text-sm text-gray-400 mb-1">Embedding ID</p>
                                            <p className="font-mono text-sm text-white break-all">{result.embedding_id}</p>
                                        </div>
                                    )}
                                    {result.modalities && (
                                        <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                                            <p className="text-sm text-gray-400 mb-2">Extracted Modalities</p>
                                            <div className="flex flex-wrap gap-2">
                                                {(Array.isArray(result.modalities) ? result.modalities : Object.keys(result.modalities)).map((m: string) => (
                                                    <span key={m} className="px-3 py-1 bg-violet-500/20 text-violet-300 rounded-full text-xs font-medium border border-violet-500/20">{m}</span>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                    <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                                        <p className="text-sm text-gray-400 mb-2">Raw Response</p>
                                        <pre className="text-xs text-gray-300 overflow-auto max-h-64 whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>
                                    </div>
                                </motion.div>
                            ) : (
                                <div className="flex flex-col items-center justify-center py-16 text-gray-500">
                                    <Layers size={48} className="mb-4 opacity-30" />
                                    <p>Submit a request to see results</p>
                                </div>
                            )}
                        </div>
                    </div>
                </motion.div>
            </main>
        </div>
    )
}

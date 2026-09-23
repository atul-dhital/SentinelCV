'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Cpu, Image, Eye, CheckCircle, AlertCircle, Loader2, Activity } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { vitService } from '@/services/api'

const tabs = ['Embed Face', 'Visualize Attention'] as const
type Tab = typeof tabs[number]

export default function VitPage() {
    const router = useRouter()
    const [activeTab, setActiveTab] = useState<Tab>('Embed Face')
    const [loading, setLoading] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [result, setResult] = useState<any>(null)

    const [embedForm, setEmbedForm] = useState({ detection_log_id: '', image_path: '', layer: 12 })
    const [attentionForm, setAttentionForm] = useState({ embedding_id: '' })

    const flash = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 5000)
    }

    const handleEmbedFace = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!embedForm.image_path) { flash('error', 'Image path required'); return }
        setLoading(true); setResult(null)
        try {
            const res = await vitService.embedFace(embedForm)
            setResult(res.data)
            flash('success', `ViT embedding generated (${res.data.embedding_dim || 768}-d)`)
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Embedding failed')
        } finally { setLoading(false) }
    }

    const handleVisualizeAttention = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!attentionForm.embedding_id) { flash('error', 'Embedding ID required'); return }
        setLoading(true); setResult(null)
        try {
            const res = await vitService.visualizeAttention(attentionForm)
            setResult(res.data)
            flash('success', 'Attention map generated')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Visualization failed')
        } finally { setLoading(false) }
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <div className="mb-8">
                    <h1 className="text-3xl font-bold flex items-center gap-3"><Cpu className="w-8 h-8 text-violet-400" /> Vision Transformer</h1>
                    <p className="text-gray-400 mt-2">Generate ViT-B/32 face embeddings and visualize attention maps for interpretability.</p>
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

                {activeTab === 'Embed Face' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Image className="w-5 h-5" /> Generate ViT Embedding</h2>
                        <form onSubmit={handleEmbedFace} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Detection Log ID (optional)</label>
                                <input value={embedForm.detection_log_id} onChange={e => setEmbedForm({ ...embedForm, detection_log_id: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID (optional)" />
                            </div>
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Image Path</label>
                                <input value={embedForm.image_path} onChange={e => setEmbedForm({ ...embedForm, image_path: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="/path/to/face.jpg" />
                            </div>
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Transformer Layer (1-12)</label>
                                <input type="number" min={1} max={12} value={embedForm.layer}
                                    onChange={e => setEmbedForm({ ...embedForm, layer: parseInt(e.target.value) || 12 })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" />
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-violet-600 hover:bg-violet-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />} Generate Embedding
                            </button>
                        </form>
                    </motion.div>
                )}

                {activeTab === 'Visualize Attention' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Eye className="w-5 h-5" /> Attention Map Visualization</h2>
                        <form onSubmit={handleVisualizeAttention} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Embedding ID</label>
                                <input value={attentionForm.embedding_id} onChange={e => setAttentionForm({ ...attentionForm, embedding_id: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-violet-600 hover:bg-violet-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Eye className="w-4 h-4" />} Visualize
                            </button>
                        </form>
                    </motion.div>
                )}

                {result && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h3 className="text-lg font-semibold mb-3 flex items-center gap-2"><Activity className="w-5 h-5 text-violet-400" /> Result</h3>
                        {result.attention_heads && (
                            <div className="grid grid-cols-4 gap-2 mb-4">
                                {result.attention_heads.map((head: any, i: number) => (
                                    <div key={i} className="bg-black/40 rounded-lg p-2 text-center">
                                        <div className="text-xs text-gray-500">Head {i + 1}</div>
                                        <div className="text-sm text-violet-300 font-mono">{(head.avg_attention * 100).toFixed(1)}%</div>
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

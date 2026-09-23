'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Box, ScanFace, GitCompare, Fingerprint, CheckCircle, AlertCircle, Loader2 } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { threeDFaceService } from '@/services/api'

const tabs = ['Capture', 'Match', 'Liveness'] as const
type Tab = typeof tabs[number]

export default function ThreeDFacePage() {
    const router = useRouter()
    const [activeTab, setActiveTab] = useState<Tab>('Capture')
    const [loading, setLoading] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [result, setResult] = useState<any>(null)

    const [captureForm, setCaptureForm] = useState({
        visitor_id: '',
        depth_map_path: '',
        point_cloud_path: '',
        texture_map_path: '',
        face_width_mm: '',
        face_height_mm: '',
        face_depth_mm: '',
    })

    const [matchForm, setMatchForm] = useState({
        face_data_1_id: '',
        face_data_2_id: '',
        match_threshold: 0.7,
    })

    const [livenessForm, setLivenessForm] = useState({
        face_data_id: '',
    })

    const flash = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 5000)
    }

    const handleCapture = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!captureForm.visitor_id) { flash('error', 'Visitor ID is required'); return }
        setLoading(true)
        setResult(null)
        try {
            const payload: any = {
                visitor_id: captureForm.visitor_id,
                depth_map_path: captureForm.depth_map_path || undefined,
                point_cloud_path: captureForm.point_cloud_path || undefined,
                texture_map_path: captureForm.texture_map_path || undefined,
            }
            if (captureForm.face_width_mm) payload.face_width_mm = parseFloat(captureForm.face_width_mm)
            if (captureForm.face_height_mm) payload.face_height_mm = parseFloat(captureForm.face_height_mm)
            if (captureForm.face_depth_mm) payload.face_depth_mm = parseFloat(captureForm.face_depth_mm)
            const res = await threeDFaceService.capture(payload)
            setResult(res.data)
            flash('success', '3D face data captured successfully')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Capture failed')
        } finally {
            setLoading(false)
        }
    }

    const handleMatch = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!matchForm.face_data_1_id || !matchForm.face_data_2_id) { flash('error', 'Both face data IDs are required'); return }
        setLoading(true)
        setResult(null)
        try {
            const res = await threeDFaceService.compare({
                face_data_1_id: matchForm.face_data_1_id,
                face_data_2_id: matchForm.face_data_2_id,
                match_threshold: matchForm.match_threshold,
            })
            setResult(res.data)
            flash('success', 'Match comparison complete')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Match failed')
        } finally {
            setLoading(false)
        }
    }

    const handleLiveness = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!livenessForm.face_data_id) { flash('error', 'Face Data ID is required'); return }
        setLoading(true)
        setResult(null)
        try {
            const res = await threeDFaceService.liveness(livenessForm.face_data_id)
            setResult(res.data)
            flash('success', 'Liveness check complete')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Liveness check failed')
        } finally {
            setLoading(false)
        }
    }

    const inputCls = "w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-cyan-500/50 transition-colors"

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
                    {/* Header */}
                    <div className="flex items-center gap-4 mb-8">
                        <div className="w-14 h-14 bg-gradient-to-br from-cyan-500 to-blue-700 rounded-2xl flex items-center justify-center shadow-lg shadow-cyan-500/20">
                            <Box size={28} className="text-white" />
                        </div>
                        <div>
                            <h1 className="text-3xl font-bold tracking-tight">3D Face Recognition</h1>
                            <p className="text-gray-400 mt-1">Capture depth maps, match 3D face data, and verify liveness</p>
                        </div>
                    </div>

                    {/* Message */}
                    <AnimatePresence>
                        {message && (
                            <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className={`mb-6 p-4 rounded-xl border flex items-center gap-3 ${message.type === 'success' ? 'bg-green-500/10 border-green-500/20 text-green-300' : 'bg-red-500/10 border-red-500/20 text-red-300'}`}>
                                {message.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
                                {message.text}
                            </motion.div>
                        )}
                    </AnimatePresence>

                    {/* Tabs */}
                    <div className="flex gap-2 mb-8">
                        {tabs.map((tab) => (
                            <button key={tab} onClick={() => { setActiveTab(tab); setResult(null) }} className={`px-5 py-2.5 rounded-xl text-sm font-medium transition-all ${activeTab === tab ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30' : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'}`}>
                                {tab}
                            </button>
                        ))}
                    </div>

                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                        {/* Form Panel */}
                        <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
                            {activeTab === 'Capture' && (
                                <form onSubmit={handleCapture} className="space-y-5">
                                    <h2 className="text-lg font-semibold flex items-center gap-2"><ScanFace size={18} /> Capture 3D Face Data</h2>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Visitor ID *</label>
                                        <input type="text" value={captureForm.visitor_id} onChange={(e) => setCaptureForm({ ...captureForm, visitor_id: e.target.value })} className={inputCls} placeholder="Enter visitor ID" required />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Depth Map Path</label>
                                        <input type="text" value={captureForm.depth_map_path} onChange={(e) => setCaptureForm({ ...captureForm, depth_map_path: e.target.value })} className={inputCls} placeholder="/path/to/depth_map.npy" />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Point Cloud Path</label>
                                        <input type="text" value={captureForm.point_cloud_path} onChange={(e) => setCaptureForm({ ...captureForm, point_cloud_path: e.target.value })} className={inputCls} placeholder="/path/to/point_cloud.ply" />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Texture Map Path</label>
                                        <input type="text" value={captureForm.texture_map_path} onChange={(e) => setCaptureForm({ ...captureForm, texture_map_path: e.target.value })} className={inputCls} placeholder="/path/to/texture.png" />
                                    </div>
                                    <div className="grid grid-cols-3 gap-3">
                                        <div>
                                            <label className="block text-sm text-gray-400 mb-1.5">Width (mm)</label>
                                            <input type="number" step="0.1" value={captureForm.face_width_mm} onChange={(e) => setCaptureForm({ ...captureForm, face_width_mm: e.target.value })} className={inputCls} placeholder="0.0" />
                                        </div>
                                        <div>
                                            <label className="block text-sm text-gray-400 mb-1.5">Height (mm)</label>
                                            <input type="number" step="0.1" value={captureForm.face_height_mm} onChange={(e) => setCaptureForm({ ...captureForm, face_height_mm: e.target.value })} className={inputCls} placeholder="0.0" />
                                        </div>
                                        <div>
                                            <label className="block text-sm text-gray-400 mb-1.5">Depth (mm)</label>
                                            <input type="number" step="0.1" value={captureForm.face_depth_mm} onChange={(e) => setCaptureForm({ ...captureForm, face_depth_mm: e.target.value })} className={inputCls} placeholder="0.0" />
                                        </div>
                                    </div>
                                    <button type="submit" disabled={loading} className="w-full py-3 bg-cyan-600 hover:bg-cyan-700 disabled:opacity-50 rounded-xl font-medium transition-colors flex items-center justify-center gap-2">
                                        {loading ? <Loader2 size={18} className="animate-spin" /> : <ScanFace size={18} />}
                                        Capture 3D Data
                                    </button>
                                </form>
                            )}

                            {activeTab === 'Match' && (
                                <form onSubmit={handleMatch} className="space-y-5">
                                    <h2 className="text-lg font-semibold flex items-center gap-2"><GitCompare size={18} /> Match 3D Faces</h2>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Face Data ID 1 *</label>
                                        <input type="text" value={matchForm.face_data_1_id} onChange={(e) => setMatchForm({ ...matchForm, face_data_1_id: e.target.value })} className={inputCls} placeholder="First face data ID" required />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Face Data ID 2 *</label>
                                        <input type="text" value={matchForm.face_data_2_id} onChange={(e) => setMatchForm({ ...matchForm, face_data_2_id: e.target.value })} className={inputCls} placeholder="Second face data ID" required />
                                    </div>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Match Threshold: {matchForm.match_threshold}</label>
                                        <input type="range" min="0" max="1" step="0.05" value={matchForm.match_threshold} onChange={(e) => setMatchForm({ ...matchForm, match_threshold: parseFloat(e.target.value) })} className="w-full accent-cyan-500" />
                                    </div>
                                    <button type="submit" disabled={loading} className="w-full py-3 bg-cyan-600 hover:bg-cyan-700 disabled:opacity-50 rounded-xl font-medium transition-colors flex items-center justify-center gap-2">
                                        {loading ? <Loader2 size={18} className="animate-spin" /> : <GitCompare size={18} />}
                                        Compare Faces
                                    </button>
                                </form>
                            )}

                            {activeTab === 'Liveness' && (
                                <form onSubmit={handleLiveness} className="space-y-5">
                                    <h2 className="text-lg font-semibold flex items-center gap-2"><Fingerprint size={18} /> Liveness Check</h2>
                                    <div>
                                        <label className="block text-sm text-gray-400 mb-1.5">Face Data ID *</label>
                                        <input type="text" value={livenessForm.face_data_id} onChange={(e) => setLivenessForm({ ...livenessForm, face_data_id: e.target.value })} className={inputCls} placeholder="Enter face data ID" required />
                                    </div>
                                    <p className="text-sm text-gray-500">Run geometric liveness verification against the captured 3D face data to detect spoofing attempts.</p>
                                    <button type="submit" disabled={loading} className="w-full py-3 bg-cyan-600 hover:bg-cyan-700 disabled:opacity-50 rounded-xl font-medium transition-colors flex items-center justify-center gap-2">
                                        {loading ? <Loader2 size={18} className="animate-spin" /> : <Fingerprint size={18} />}
                                        Run Liveness Check
                                    </button>
                                </form>
                            )}
                        </div>

                        {/* Results Panel */}
                        <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
                            <h2 className="text-lg font-semibold mb-4">Results</h2>
                            {loading ? (
                                <div className="flex items-center justify-center py-16">
                                    <Loader2 size={32} className="animate-spin text-cyan-400" />
                                </div>
                            ) : result ? (
                                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
                                    {/* Match result */}
                                    {result.match_confidence !== undefined && (
                                        <div className={`rounded-xl p-4 text-center border ${result.is_same_person ? 'bg-green-500/10 border-green-500/20' : 'bg-red-500/10 border-red-500/20'}`}>
                                            <p className="text-sm text-gray-400 mb-1">Match Confidence</p>
                                            <p className={`text-4xl font-bold ${result.is_same_person ? 'text-green-300' : 'text-red-300'}`}>{(result.match_confidence * 100).toFixed(1)}%</p>
                                            <span className={`inline-block mt-2 px-3 py-1 rounded-full text-xs font-medium ${result.is_same_person ? 'bg-green-500/20 text-green-300' : 'bg-red-500/20 text-red-300'}`}>
                                                {result.is_same_person ? 'Same Person' : 'Different Person'}
                                            </span>
                                        </div>
                                    )}
                                    {/* Liveness result */}
                                    {result.geometric_liveness_score !== undefined && !result.match_confidence && (
                                        <div className={`rounded-xl p-4 text-center border ${result.geometric_liveness_score > 0.5 ? 'bg-green-500/10 border-green-500/20' : 'bg-red-500/10 border-red-500/20'}`}>
                                            <p className="text-sm text-gray-400 mb-1">Geometric Liveness Score</p>
                                            <p className={`text-4xl font-bold ${result.geometric_liveness_score > 0.5 ? 'text-green-300' : 'text-red-300'}`}>{(result.geometric_liveness_score * 100).toFixed(1)}%</p>
                                            <span className={`inline-block mt-2 px-3 py-1 rounded-full text-xs font-medium ${result.geometric_liveness_score > 0.5 ? 'bg-green-500/20 text-green-300' : 'bg-red-500/20 text-red-300'}`}>
                                                {result.geometric_liveness_score > 0.5 ? 'Live' : 'Potential Spoof'}
                                            </span>
                                        </div>
                                    )}
                                    {/* Capture result */}
                                    {result.id && result.embedding_confidence !== undefined && (
                                        <div className="space-y-3">
                                            <div className="bg-cyan-500/10 border border-cyan-500/20 rounded-xl p-4 text-center">
                                                <p className="text-sm text-gray-400 mb-1">Embedding Confidence</p>
                                                <p className="text-3xl font-bold text-cyan-300">{(result.embedding_confidence * 100).toFixed(1)}%</p>
                                            </div>
                                            <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                                                <p className="text-sm text-gray-400 mb-1">Capture Quality</p>
                                                <p className="text-lg font-semibold">{(result.capture_quality_score * 100).toFixed(1)}%</p>
                                            </div>
                                        </div>
                                    )}
                                    {/* Similarity scores */}
                                    {(result.cosine_similarity !== undefined || result.shape_similarity !== undefined) && (
                                        <div className="grid grid-cols-2 gap-3">
                                            {result.cosine_similarity !== null && result.cosine_similarity !== undefined && (
                                                <div className="bg-white/5 border border-white/10 rounded-xl p-3 text-center">
                                                    <p className="text-xs text-gray-400 mb-1">Cosine Similarity</p>
                                                    <p className="text-lg font-bold text-cyan-300">{(result.cosine_similarity * 100).toFixed(1)}%</p>
                                                </div>
                                            )}
                                            {result.shape_similarity !== null && result.shape_similarity !== undefined && (
                                                <div className="bg-white/5 border border-white/10 rounded-xl p-3 text-center">
                                                    <p className="text-xs text-gray-400 mb-1">Shape Similarity</p>
                                                    <p className="text-lg font-bold text-cyan-300">{(result.shape_similarity * 100).toFixed(1)}%</p>
                                                </div>
                                            )}
                                            {result.texture_similarity !== null && result.texture_similarity !== undefined && (
                                                <div className="bg-white/5 border border-white/10 rounded-xl p-3 text-center">
                                                    <p className="text-xs text-gray-400 mb-1">Texture Similarity</p>
                                                    <p className="text-lg font-bold text-cyan-300">{(result.texture_similarity * 100).toFixed(1)}%</p>
                                                </div>
                                            )}
                                            {result.euclidean_distance !== null && result.euclidean_distance !== undefined && (
                                                <div className="bg-white/5 border border-white/10 rounded-xl p-3 text-center">
                                                    <p className="text-xs text-gray-400 mb-1">Euclidean Distance</p>
                                                    <p className="text-lg font-bold text-cyan-300">{result.euclidean_distance.toFixed(4)}</p>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                    <div className="bg-white/5 border border-white/10 rounded-xl p-4">
                                        <p className="text-sm text-gray-400 mb-2">Raw Response</p>
                                        <pre className="text-xs text-gray-300 overflow-auto max-h-48 whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>
                                    </div>
                                </motion.div>
                            ) : (
                                <div className="flex flex-col items-center justify-center py-16 text-gray-500">
                                    <Box size={48} className="mb-4 opacity-30" />
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

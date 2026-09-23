'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Waves, Thermometer, Layers, CheckCircle, AlertCircle, Loader2, Activity } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { multispectralService } from '@/services/api'

const tabs = ['Thermal Capture', 'Multispectral Capture'] as const
type Tab = typeof tabs[number]

export default function MultispectralPage() {
    const router = useRouter()
    const [activeTab, setActiveTab] = useState<Tab>('Thermal Capture')
    const [loading, setLoading] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [result, setResult] = useState<any>(null)

    const [thermalForm, setThermalForm] = useState({ visitor_id: '', thermal_image_path: '', ambient_temp_c: 22.0 })
    const [msForm, setMsForm] = useState({
        visitor_id: '', visible_image_path: '', nir_image_path: '',
        swir_image_path: '', thermal_image_path: '',
    })

    const flash = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 5000)
    }

    const handleThermalCapture = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!thermalForm.visitor_id || !thermalForm.thermal_image_path) { flash('error', 'Visitor ID and thermal image required'); return }
        setLoading(true); setResult(null)
        try {
            const res = await multispectralService.captureThermal(thermalForm)
            setResult(res.data)
            flash('success', 'Thermal data captured and analyzed')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Thermal capture failed')
        } finally { setLoading(false) }
    }

    const handleMultispectralCapture = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!msForm.visitor_id) { flash('error', 'Visitor ID required'); return }
        setLoading(true); setResult(null)
        try {
            const res = await multispectralService.captureMultispectral(msForm)
            setResult(res.data)
            flash('success', 'Multispectral data captured')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Multispectral capture failed')
        } finally { setLoading(false) }
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <div className="mb-8">
                    <h1 className="text-3xl font-bold flex items-center gap-3"><Waves className="w-8 h-8 text-orange-400" /> Multi-Spectral & Infrared</h1>
                    <p className="text-gray-400 mt-2">Process thermal and multispectral images for advanced spoofing detection and recognition.</p>
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

                {activeTab === 'Thermal Capture' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Thermometer className="w-5 h-5 text-red-400" /> Thermal Image Analysis</h2>
                        <form onSubmit={handleThermalCapture} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Visitor ID</label>
                                <input value={thermalForm.visitor_id} onChange={e => setThermalForm({ ...thermalForm, visitor_id: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                            </div>
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Thermal Image Path</label>
                                <input value={thermalForm.thermal_image_path} onChange={e => setThermalForm({ ...thermalForm, thermal_image_path: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="/path/to/thermal.png" />
                            </div>
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Ambient Temperature (C)</label>
                                <input type="number" step={0.1} value={thermalForm.ambient_temp_c}
                                    onChange={e => setThermalForm({ ...thermalForm, ambient_temp_c: parseFloat(e.target.value) || 22 })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" />
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-orange-600 hover:bg-orange-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Thermometer className="w-4 h-4" />} Analyze Thermal
                            </button>
                        </form>
                    </motion.div>
                )}

                {activeTab === 'Multispectral Capture' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Layers className="w-5 h-5 text-orange-400" /> Multi-Band Capture</h2>
                        <form onSubmit={handleMultispectralCapture} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Visitor ID</label>
                                <input value={msForm.visitor_id} onChange={e => setMsForm({ ...msForm, visitor_id: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="UUID" />
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                {(['visible_image_path', 'nir_image_path', 'swir_image_path', 'thermal_image_path'] as const).map(field => (
                                    <div key={field}>
                                        <label className="block text-sm text-gray-400 mb-1">{field.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</label>
                                        <input value={msForm[field]} onChange={e => setMsForm({ ...msForm, [field]: e.target.value })}
                                            className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder={`/path/to/${field.split('_')[0]}.png`} />
                                    </div>
                                ))}
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-orange-600 hover:bg-orange-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Waves className="w-4 h-4" />} Capture Multispectral
                            </button>
                        </form>
                    </motion.div>
                )}

                {result && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h3 className="text-lg font-semibold mb-3 flex items-center gap-2"><Activity className="w-5 h-5 text-orange-400" /> Analysis Result</h3>
                        {result.liveness_score !== undefined && (
                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                                <div className="bg-black/30 rounded-xl p-3 text-center">
                                    <div className="text-xs text-gray-500">Liveness</div>
                                    <div className={`text-lg font-bold ${result.liveness_score > 0.5 ? 'text-green-400' : 'text-red-400'}`}>{(result.liveness_score * 100).toFixed(1)}%</div>
                                </div>
                                {result.spoofing_confidence !== undefined && (
                                    <div className="bg-black/30 rounded-xl p-3 text-center">
                                        <div className="text-xs text-gray-500">Spoof Risk</div>
                                        <div className={`text-lg font-bold ${result.spoofing_confidence < 0.3 ? 'text-green-400' : 'text-red-400'}`}>{(result.spoofing_confidence * 100).toFixed(1)}%</div>
                                    </div>
                                )}
                            </div>
                        )}
                        <pre className="bg-black/40 p-4 rounded-xl text-sm text-gray-300 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>
                    </motion.div>
                )}
            </main>
        </div>
    )
}

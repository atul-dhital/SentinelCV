'use client'

import React, { useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import { Smartphone, Bell, CloudOff, Upload, CheckCircle, AlertCircle, Loader2, Activity } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { mobileService } from '@/services/api'

const tabs = ['Push Notifications', 'Offline Sync'] as const
type Tab = typeof tabs[number]

export default function MobilePage() {
    const router = useRouter()
    const [activeTab, setActiveTab] = useState<Tab>('Push Notifications')
    const [loading, setLoading] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [result, setResult] = useState<any>(null)

    const [pushForm, setPushForm] = useState({ device_token: '', device_type: 'web' })
    const [syncData, setSyncData] = useState('[\n  {\n    "visitor_id": "",\n    "confidence": 0.85,\n    "timestamp": "2026-04-03T10:00:00Z"\n  }\n]')

    const flash = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 5000)
    }

    const handleRegisterPush = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!pushForm.device_token) { flash('error', 'Device token required'); return }
        setLoading(true); setResult(null)
        try {
            const res = await mobileService.registerPush(pushForm)
            setResult(res.data)
            flash('success', 'Device registered for push notifications')
        } catch (err: any) {
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Registration failed')
        } finally { setLoading(false) }
    }

    const handleSyncOffline = async (e: React.FormEvent) => {
        e.preventDefault()
        setLoading(true); setResult(null)
        try {
            const detections = JSON.parse(syncData)
            const res = await mobileService.syncOffline({ detections })
            setResult(res.data)
            flash('success', `Synced ${detections.length} offline detection(s)`)
        } catch (err: any) {
            if (err instanceof SyntaxError) { flash('error', 'Invalid JSON format'); setLoading(false); return }
            if (err.response?.status === 401) { router.push('/login'); return }
            flash('error', err.response?.data?.detail || 'Sync failed')
        } finally { setLoading(false) }
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <div className="mb-8">
                    <h1 className="text-3xl font-bold flex items-center gap-3"><Smartphone className="w-8 h-8 text-blue-400" /> Mobile & PWA Features</h1>
                    <p className="text-gray-400 mt-2">Push notification registration, offline detection sync, and progressive web app management.</p>
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

                {activeTab === 'Push Notifications' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><Bell className="w-5 h-5" /> Register for Push Notifications</h2>
                        <form onSubmit={handleRegisterPush} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Device Token</label>
                                <input value={pushForm.device_token} onChange={e => setPushForm({ ...pushForm, device_token: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white" placeholder="FCM/APNS device token" />
                            </div>
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Device Type</label>
                                <select value={pushForm.device_type} onChange={e => setPushForm({ ...pushForm, device_type: e.target.value })}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white">
                                    <option value="web">Web (PWA)</option>
                                    <option value="ios">iOS</option>
                                    <option value="android">Android</option>
                                </select>
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Bell className="w-4 h-4" />} Register Device
                            </button>
                        </form>
                    </motion.div>
                )}

                {activeTab === 'Offline Sync' && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2"><CloudOff className="w-5 h-5" /> Sync Offline Detections</h2>
                        <p className="text-gray-400 text-sm mb-4">Paste JSON array of detections captured while offline. They will be re-identified using current models.</p>
                        <form onSubmit={handleSyncOffline} className="space-y-4">
                            <div>
                                <label className="block text-sm text-gray-400 mb-1">Detections JSON</label>
                                <textarea rows={8} value={syncData} onChange={e => setSyncData(e.target.value)}
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2.5 text-white font-mono text-sm" />
                            </div>
                            <button type="submit" disabled={loading}
                                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 rounded-xl font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />} Sync Detections
                            </button>
                        </form>
                    </motion.div>
                )}

                {result && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-6 bg-white/5 border border-white/10 rounded-2xl p-6">
                        <h3 className="text-lg font-semibold mb-3 flex items-center gap-2"><Activity className="w-5 h-5 text-blue-400" /> Result</h3>
                        <pre className="bg-black/40 p-4 rounded-xl text-sm text-gray-300 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>
                    </motion.div>
                )}
            </main>
        </div>
    )
}

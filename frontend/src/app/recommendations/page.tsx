'use client'

import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { useRouter } from 'next/navigation'
import { Lightbulb, AlertTriangle, CheckCircle, Target, TrendingUp, Users, ImageIcon, RefreshCw, ArrowRight } from 'lucide-react'
import Navbar from '@/components/Navbar'
import MediaImage from '@/components/MediaImage'
import { recommendationService } from '@/services/api'
import { getStaticMediaUrl } from '@/lib/utils'

interface Recommendation {
    type: string
    severity: string
    title: string
    message?: string
    description?: string
    action: string
    entity_id?: string | null
    entity_type?: string | null
    entity_name?: string | null
    entity_image_url?: string | null
}

export default function RecommendationsPage() {
    const router = useRouter()
    const [recommendations, setRecommendations] = useState<Recommendation[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')

    useEffect(() => {
        fetchData()
    }, [])

    const fetchData = async () => {
        setLoading(true)
        setError('')
        try {
            const res = await recommendationService.getAll()
            setRecommendations(res.data.recommendations || res.data || [])
        } catch (err: any) {
            if (err.response?.status === 401) {
                window.location.href = '/login'
                return
            }
            setError('Failed to load recommendations')
        } finally {
            setLoading(false)
        }
    }

    const severityColor = (sev: string) => {
        switch (sev) {
            case 'critical': return 'text-red-400 bg-red-400/10 border-red-500/20'
            case 'warning': return 'text-yellow-400 bg-yellow-400/10 border-yellow-500/20'
            case 'info': return 'text-blue-400 bg-blue-400/10 border-blue-500/20'
            default: return 'text-green-400 bg-green-400/10 border-green-500/20'
        }
    }

    const severityIcon = (sev: string) => {
        switch (sev) {
            case 'critical': return <AlertTriangle size={20} />
            case 'warning': return <AlertTriangle size={20} />
            case 'info': return <Lightbulb size={20} />
            default: return <CheckCircle size={20} />
        }
    }

    const typeIcon = (type: string) => {
        switch (type) {
            case 'face_quality': return <ImageIcon size={16} />
            case 'threshold': return <Target size={16} />
            case 'threshold_tuning': return <Target size={16} />
            case 'accuracy': return <TrendingUp size={16} />
            case 'visitor': return <Users size={16} />
            default: return <Lightbulb size={16} />
        }
    }

    const openRecommendation = (rec: Recommendation) => {
        if (rec.entity_type === 'visitor' && rec.entity_id) {
            router.push(`/visitors/${rec.entity_id}#media-enrollment`)
            return
        }

        if (rec.action === 'adjust_threshold') {
            router.push('/settings#confidence-threshold')
            return
        }

        if (rec.action === 'review_settings') {
            router.push('/settings')
        }
    }

    if (loading) {
        return (
            <div className="min-h-screen">
                <Navbar />
                <main className="pt-24 pb-20 px-6 container mx-auto">
                    <div className="animate-pulse space-y-4">
                        <div className="h-8 bg-gray-800 rounded w-64"></div>
                        <div className="space-y-3">
                            {[1, 2, 3, 4].map(i => (
                                <div key={i} className="h-24 bg-gray-800 rounded-xl" />
                            ))}
                        </div>
                    </div>
                </main>
            </div>
        )
    }

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-20 px-6 container mx-auto">
                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
                    <div className="flex items-center justify-between mb-10">
                        <div>
                            <h1 className="text-4xl font-extrabold mb-3 bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
                                Recommendations
                            </h1>
                            <p className="text-gray-400 text-lg">AI-powered suggestions to improve your recognition system.</p>
                        </div>
                        <button
                            onClick={fetchData}
                            className="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                        >
                            <RefreshCw size={16} /> Refresh
                        </button>
                    </div>

                    {error && (
                        <div className="mb-6 p-4 rounded-lg bg-red-500/10 text-red-400 border border-red-500/20 flex items-center gap-3">
                            <AlertTriangle size={20} /> {error}
                        </div>
                    )}

                    {recommendations.length === 0 ? (
                        <div className="glass-card p-12 text-center">
                            <CheckCircle size={48} className="text-green-400 mx-auto mb-4" />
                            <h2 className="text-2xl font-bold mb-2">All Good!</h2>
                            <p className="text-gray-400">No recommendations at this time. Your system is well configured.</p>
                        </div>
                    ) : (
                        <div className="space-y-4">
                            {recommendations.map((rec, i) => (
                                <motion.div
                                    key={i}
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={{ delay: i * 0.05 }}
                                    className={`glass-card p-6 border ${severityColor(rec.severity)}`}
                                >
                                    <div className="flex flex-col md:flex-row md:items-start gap-4">
                                        <div className={`p-2 rounded-lg shrink-0 ${severityColor(rec.severity)}`}>
                                            {severityIcon(rec.severity)}
                                        </div>

                                        <button
                                            type="button"
                                            onClick={() => openRecommendation(rec)}
                                            disabled={rec.entity_type !== 'visitor' || !rec.entity_id}
                                            className="relative w-full md:w-32 aspect-square rounded-2xl overflow-hidden border border-white/10 bg-black/40 disabled:cursor-default disabled:opacity-100 group shrink-0"
                                            title={rec.entity_type === 'visitor' && rec.entity_id ? 'Open visitor profile' : rec.title}
                                        >
                                            {getStaticMediaUrl(rec.entity_image_url) ? (
                                                <MediaImage
                                                    sources={[rec.entity_image_url]}
                                                    alt={rec.entity_name || rec.title}
                                                    className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
                                                    fallback={
                                                        <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-white/5 to-white/0 text-gray-500">
                                                            <Users size={26} />
                                                        </div>
                                                    }
                                                />
                                            ) : (
                                                <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-white/5 to-white/0 text-gray-500">
                                                    <Users size={26} />
                                                </div>
                                            )}
                                            <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity flex items-end justify-start p-3">
                                                <span className="text-[10px] font-bold uppercase tracking-[0.24em] text-white/90 flex items-center gap-1">
                                                    Solve <ArrowRight size={12} />
                                                </span>
                                            </div>
                                        </button>

                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-2 mb-1">
                                                {typeIcon(rec.type)}
                                                <span className="text-xs text-gray-500 uppercase tracking-wider">{rec.type.replace(/_/g, ' ')}</span>
                                            </div>
                                            <div className="flex flex-wrap items-center gap-2 mb-2">
                                                <h3 className="text-lg font-bold text-white">{rec.title}</h3>
                                                {rec.entity_name && (
                                                    <span className="text-xs bg-white/5 border border-white/10 text-gray-300 px-2 py-1 rounded-full">
                                                        {rec.entity_name}
                                                    </span>
                                                )}
                                            </div>
                                            <p className="text-gray-400 text-sm mb-3">{rec.description || rec.message}</p>
                                            <div className="flex flex-wrap items-center gap-3">
                                                <p className="text-sm text-brand-400 font-medium">{rec.action}</p>
                                                {rec.entity_type === 'visitor' && rec.entity_id && (
                                                    <button
                                                        type="button"
                                                        onClick={() => openRecommendation(rec)}
                                                        className="inline-flex items-center gap-2 text-xs font-semibold text-white bg-brand-600/20 hover:bg-brand-600/30 border border-brand-500/20 px-3 py-2 rounded-lg transition-colors"
                                                    >
                                                        Open profile
                                                        <ArrowRight size={14} />
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                            ))}
                        </div>
                    )}
                </motion.div>
            </main>
        </div>
    )
}

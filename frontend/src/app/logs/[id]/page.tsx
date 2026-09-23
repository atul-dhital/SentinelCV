'use client'

import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { useParams, useRouter } from 'next/navigation'
import {
    ArrowLeft, Clock, Camera, User, UserPlus, Search, CheckCircle,
    AlertCircle, Image, Video, Eye, Link2, ThumbsUp, ThumbsDown, UserX, ChevronRight
} from 'lucide-react'
import Link from 'next/link'
import Navbar from '@/components/Navbar'
import MediaImage from '@/components/MediaImage'
import { logService, visitorService, VisitorLog, Visitor } from '@/services/api'
import { getStaticMediaUrl } from '@/lib/utils'

export default function LogDetailPage() {
    const params = useParams()
    const router = useRouter()
    const logId = params.id as string

    const [log, setLog] = useState<VisitorLog | null>(null)
    const [loading, setLoading] = useState(true)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

    // Assign to existing visitor
    const [showAssign, setShowAssign] = useState(false)
    const [searchQuery, setSearchQuery] = useState('')
    const [visitors, setVisitors] = useState<Visitor[]>([])
    const [searchingVisitors, setSearchingVisitors] = useState(false)

    // Create new visitor from log
    const [showCreate, setShowCreate] = useState(false)
    const [creating, setCreating] = useState(false)
    const [newVisitor, setNewVisitor] = useState({
        name: '',
        email: '',
        phone: '',
        notes: '',
    })

    useEffect(() => {
        fetchLog()
    }, [logId])

    const fetchLog = async () => {
        try {
            const res = await logService.getLog(logId)
            setLog(res.data)
        } catch (err: any) {
            if (err.response?.status === 401) {
                router.push('/login')
                return
            }
            if (err.response?.status === 404) {
                setMessage({ type: 'error', text: 'Log entry not found' })
            }
        } finally {
            setLoading(false)
        }
    }

    const searchVisitors = async () => {
        setSearchingVisitors(true)
        try {
            const res = await visitorService.getVisitors({ search: searchQuery, limit: 10 })
            setVisitors(res.data.items)
        } catch {
            console.error('Failed to search visitors')
        } finally {
            setSearchingVisitors(false)
        }
    }

    const handleAssign = async (visitorId: string) => {
        try {
            await logService.assignLog(logId, visitorId)
            setMessage({ type: 'success', text: 'Log assigned to visitor successfully!' })
            setShowAssign(false)
            fetchLog()
        } catch {
            setMessage({ type: 'error', text: 'Failed to assign log to visitor' })
        }
    }

    const handleCreateVisitor = async (e: React.FormEvent) => {
        e.preventDefault()
        setCreating(true)
        try {
            await logService.createVisitorFromLog(logId, newVisitor)
            setMessage({ type: 'success', text: 'New visitor created and log assigned!' })
            setShowCreate(false)
            setNewVisitor({ name: '', email: '', phone: '', notes: '' })
            fetchLog()
        } catch {
            setMessage({ type: 'error', text: 'Failed to create visitor from log' })
        } finally {
            setCreating(false)
        }
    }

    const handleConfirm = async (action: 'confirm' | 'reject') => {
        try {
            await logService.confirmLog(logId, action)
            setMessage({
                type: 'success',
                text: action === 'confirm'
                    ? 'AI identification confirmed!'
                    : 'Marked as unknown. The log was returned to manual review.',
            })
            fetchLog()
        } catch {
            setMessage({ type: 'error', text: `Failed to ${action} identification` })
        }
    }

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'identified': return 'text-green-400 bg-green-400/10'
            case 'reviewed': return 'text-blue-400 bg-blue-400/10'
            case 'detected': return 'text-yellow-400 bg-yellow-400/10'
            case 'unidentified': return 'text-red-400 bg-red-400/10'
            default: return 'text-gray-400 bg-gray-400/10'
        }
    }

    const capturedImageUrl = log ? getStaticMediaUrl(log.face_image_path) : null
    const visitorImageUrl = log ? getStaticMediaUrl(log.visitor_image_url) : null

    if (loading) {
        return (
            <div className="min-h-screen">
                <Navbar />
                <main className="pt-24 pb-20 px-6 container mx-auto">
                    <div className="animate-pulse space-y-4">
                        <div className="h-8 bg-gray-800 rounded w-64"></div>
                        <div className="h-64 bg-gray-800 rounded"></div>
                    </div>
                </main>
            </div>
        )
    }

    if (!log) {
        return (
            <div className="min-h-screen">
                <Navbar />
                <main className="pt-24 pb-20 px-6 container mx-auto">
                    <div className="glass-card p-12 text-center">
                        <AlertCircle size={48} className="text-red-400 mx-auto mb-4" />
                        <h2 className="text-2xl font-bold mb-2">Log Not Found</h2>
                        <p className="text-gray-400 mb-6">The log entry you are looking for does not exist.</p>
                        <button
                            onClick={() => router.push('/logs')}
                            className="bg-brand-600 hover:bg-brand-700 text-white px-6 py-3 rounded-lg font-medium transition-colors"
                        >
                            Back to Logs
                        </button>
                    </div>
                </main>
            </div>
        )
    }

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-24 px-6 container mx-auto">
                {/* Breadcrumb */}
                <nav className="flex items-center gap-2 text-xs text-gray-500 mb-6">
                    <Link href="/" className="hover:text-white transition-colors">Dashboard</Link>
                    <ChevronRight size={12} />
                    <Link href="/logs" className="hover:text-white transition-colors">Detection Logs</Link>
                    <ChevronRight size={12} />
                    <span className="text-gray-300 font-mono">{log.id.slice(0, 12)}…</span>
                </nav>

                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                >
                    {/* Header */}
                    <div className="flex items-center gap-4 mb-8">
                        <button
                            onClick={() => router.push('/logs')}
                            className="p-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                        >
                            <ArrowLeft size={20} />
                        </button>
                        <div className="flex-1">
                            <h1 className="text-3xl font-extrabold bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
                                Log Detail
                            </h1>
                            <p className="text-gray-500 text-sm mt-1 font-mono">{log.id}</p>
                        </div>
                        <span className={`text-sm px-3 py-1.5 rounded-full font-medium ${getStatusColor(log.status)}`}>
                            {log.status}
                        </span>
                    </div>

                    {message && (
                        <div className={`mb-6 p-4 rounded-lg flex items-center gap-3 ${message.type === 'success'
                                ? 'bg-green-500/10 text-green-400 border border-green-500/20'
                                : 'bg-red-500/10 text-red-400 border border-red-500/20'
                            }`}>
                            {message.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
                            {message.text}
                        </div>
                    )}

                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                        {/* Main Details */}
                        <div className="lg:col-span-2 space-y-6">
                            {/* Detection Info */}
                            <div className="glass-card p-6">
                                <h2 className="text-xl font-bold mb-6 flex items-center gap-3">
                                    <div className="p-2 bg-brand-500/10 rounded-lg">
                                        <Eye className="text-brand-500" size={24} />
                                    </div>
                                    Detection Details
                                </h2>

                                <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                                    <div>
                                        <p className="text-xs text-gray-500 mb-1">Timestamp</p>
                                        <p className="text-gray-200 flex items-center gap-2">
                                            <Clock size={14} className="text-gray-500" />
                                            {new Date(log.timestamp).toLocaleString()}
                                        </p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-gray-500 mb-1">Confidence</p>
                                        <p className={`font-semibold ${log.confidence >= 0.7 ? 'text-green-400' : log.confidence >= 0.4 ? 'text-yellow-400' : 'text-red-400'}`}>
                                            {(log.confidence * 100).toFixed(1)}%
                                        </p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-gray-500 mb-1">Identified</p>
                                        <p className={log.identified ? 'text-green-400' : 'text-red-400'}>
                                            {log.identified ? 'Yes' : 'No'}
                                        </p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-gray-500 mb-1">Track ID</p>
                                        <p className="text-gray-200">{log.track_id ?? 'N/A'}</p>
                                    </div>
                                </div>

                                {/* Confirm / Reject AI Identification */}
                                {log.identified && log.status !== 'reviewed' && (
                                    <div className="mt-6 pt-4 border-t border-gray-800">
                                        <p className="text-sm text-gray-400 mb-3">Is this AI identification correct?</p>
                                        <div className="flex gap-3">
                                            <button
                                                onClick={() => handleConfirm('confirm')}
                                                className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                            >
                                                <ThumbsUp size={16} /> Confirm
                                            </button>
                                            <button
                                                onClick={() => handleConfirm('reject')}
                                                className="bg-red-500/10 hover:bg-red-500/20 text-red-400 px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                            >
                                                <ThumbsDown size={16} /> Reject
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Face Image */}
                            {capturedImageUrl && (
                                <div className="glass-card p-6">
                                    <h2 className="text-xl font-bold mb-4 flex items-center gap-3">
                                        <div className="p-2 bg-purple-500/10 rounded-lg">
                                            <Image className="text-purple-400" size={24} />
                                        </div>
                                        Captured Face
                                    </h2>
                                    <div className="bg-gray-900 rounded-lg overflow-hidden inline-block">
                                        <MediaImage
                                            sources={[log.face_image_path]}
                                            alt="Captured face"
                                            className="max-w-xs max-h-64 object-contain"
                                            fallback={<div className="w-64 h-64 flex items-center justify-center"><Image className="text-gray-600" size={28} /></div>}
                                        />
                                    </div>
                                    <p className="text-xs text-gray-500 mt-3">
                                        This is the face crop captured for the detection. Review it against the visitor profile below.
                                    </p>
                                </div>
                            )}

                            {log.visitor_id && (
                                <div className="glass-card p-6">
                                    <h2 className="text-xl font-bold mb-4 flex items-center gap-3">
                                        <div className="p-2 bg-green-500/10 rounded-lg">
                                            <User className="text-green-400" size={24} />
                                        </div>
                                        Matched Visitor
                                    </h2>
                                    <div className="flex flex-col md:flex-row gap-4 md:items-center">
                                        <div className="w-28 h-28 rounded-xl overflow-hidden bg-gray-900 border border-white/5 shrink-0">
                                            {visitorImageUrl ? (
                                                <MediaImage
                                                    sources={[log.visitor_image_url, log.face_image_path]}
                                                    alt={log.visitor_name || 'Visitor'}
                                                    className="w-full h-full object-cover"
                                                    fallback={<div className="w-full h-full flex items-center justify-center"><User className="text-gray-600" size={32} /></div>}
                                                />
                                            ) : (
                                                <div className="w-full h-full flex items-center justify-center">
                                                    <User className="text-gray-600" size={32} />
                                                </div>
                                            )}
                                        </div>
                                        <div className="min-w-0">
                                            <p className="text-lg font-semibold text-white">
                                                {log.visitor_name || `Visitor ${log.visitor_id.slice(0, 8)}...`}
                                            </p>
                                            <p className="text-sm text-gray-400 mt-1">
                                                This log is currently assigned to this visitor profile.
                                            </p>
                                            <button
                                                onClick={() => router.push(`/visitors/${log.visitor_id}`)}
                                                className="mt-3 text-brand-400 hover:text-brand-300 text-sm font-medium transition-colors"
                                            >
                                                Open visitor profile
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Manual Review Actions (only if not identified) */}
                            {!log.identified && (
                                <div className="glass-card p-6">
                                    <h2 className="text-xl font-bold mb-4 flex items-center gap-3">
                                        <div className="p-2 bg-yellow-500/10 rounded-lg">
                                            <UserPlus className="text-yellow-400" size={24} />
                                        </div>
                                        Manual Review
                                    </h2>
                                    <p className="text-gray-400 text-sm mb-4">
                                        This detection was not automatically identified. You can assign it to an existing visitor or create a new one.
                                    </p>

                                    <div className="flex gap-3">
                                        <button
                                            onClick={() => { setShowAssign(true); setShowCreate(false); }}
                                            className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                        >
                                            <Link2 size={16} /> Assign to Existing Visitor
                                        </button>
                                        <button
                                            onClick={() => { setShowCreate(true); setShowAssign(false); }}
                                            className="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                        >
                                            <UserPlus size={16} /> Create New Visitor
                                        </button>
                                        <button
                                            onClick={() => handleConfirm('reject')}
                                            className="bg-red-500/10 hover:bg-red-500/20 text-red-400 px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                        >
                                            <UserX size={16} /> Set as Unknown
                                        </button>
                                    </div>

                                    {/* Assign to Existing Visitor */}
                                    {showAssign && (
                                        <motion.div
                                            initial={{ opacity: 0, height: 0 }}
                                            animate={{ opacity: 1, height: 'auto' }}
                                            className="mt-4 bg-gray-900/50 rounded-lg p-4 border border-gray-800"
                                        >
                                            <div className="flex gap-2 mb-3">
                                                <input
                                                    type="text"
                                                    value={searchQuery}
                                                    onChange={(e) => setSearchQuery(e.target.value)}
                                                    onKeyDown={(e) => e.key === 'Enter' && searchVisitors()}
                                                    className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:border-brand-500 outline-none"
                                                    placeholder="Search visitors by name..."
                                                />
                                                <button
                                                    onClick={searchVisitors}
                                                    disabled={searchingVisitors}
                                                    className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-1"
                                                >
                                                    <Search size={14} />
                                                    {searchingVisitors ? 'Searching...' : 'Search'}
                                                </button>
                                            </div>

                                            {visitors.length > 0 && (
                                                <div className="space-y-2 max-h-48 overflow-y-auto">
                                                    {visitors.map((v) => (
                                                        <div
                                                            key={v.id}
                                                            className="flex items-center justify-between bg-gray-800/50 rounded-lg p-3 hover:bg-gray-800 transition-colors"
                                                        >
                                                            <div>
                                                                <p className="font-medium text-sm">{v.name || 'Unnamed'}</p>
                                                                <p className="text-xs text-gray-500">{v.email || 'No email'}</p>
                                                            </div>
                                                            <button
                                                                onClick={() => handleAssign(v.id)}
                                                                className="bg-brand-600 hover:bg-brand-700 text-white px-3 py-1.5 rounded text-xs font-medium transition-colors"
                                                            >
                                                                Assign
                                                            </button>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </motion.div>
                                    )}

                                    {/* Create New Visitor */}
                                    {showCreate && (
                                        <motion.div
                                            initial={{ opacity: 0, height: 0 }}
                                            animate={{ opacity: 1, height: 'auto' }}
                                            className="mt-4"
                                        >
                                            <form onSubmit={handleCreateVisitor} className="bg-gray-900/50 rounded-lg p-4 border border-gray-800 space-y-3">
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-400 mb-1">Name *</label>
                                                    <input
                                                        type="text"
                                                        value={newVisitor.name}
                                                        onChange={(e) => setNewVisitor({ ...newVisitor, name: e.target.value })}
                                                        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:border-brand-500 outline-none"
                                                        placeholder="Visitor name"
                                                        required
                                                    />
                                                </div>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div>
                                                        <label className="block text-xs font-medium text-gray-400 mb-1">Email</label>
                                                        <input
                                                            type="email"
                                                            value={newVisitor.email}
                                                            onChange={(e) => setNewVisitor({ ...newVisitor, email: e.target.value })}
                                                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:border-brand-500 outline-none"
                                                            placeholder="visitor@example.com"
                                                        />
                                                    </div>
                                                    <div>
                                                        <label className="block text-xs font-medium text-gray-400 mb-1">Phone</label>
                                                        <input
                                                            type="text"
                                                            value={newVisitor.phone}
                                                            onChange={(e) => setNewVisitor({ ...newVisitor, phone: e.target.value })}
                                                            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:border-brand-500 outline-none"
                                                            placeholder="+1 234 567 8900"
                                                        />
                                                    </div>
                                                </div>
                                                <div>
                                                    <label className="block text-xs font-medium text-gray-400 mb-1">Notes</label>
                                                    <input
                                                        type="text"
                                                        value={newVisitor.notes}
                                                        onChange={(e) => setNewVisitor({ ...newVisitor, notes: e.target.value })}
                                                        className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white focus:border-brand-500 outline-none"
                                                        placeholder="Any notes..."
                                                    />
                                                </div>
                                                <div className="flex gap-2 pt-2">
                                                    <button
                                                        type="button"
                                                        onClick={() => setShowCreate(false)}
                                                        className="flex-1 bg-gray-800 hover:bg-gray-700 text-white px-3 py-2 rounded-lg text-sm font-medium transition-colors"
                                                    >
                                                        Cancel
                                                    </button>
                                                    <button
                                                        type="submit"
                                                        disabled={creating}
                                                        className="flex-1 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-3 py-2 rounded-lg text-sm font-medium transition-colors"
                                                    >
                                                        {creating ? 'Creating...' : 'Create & Assign'}
                                                    </button>
                                                </div>
                                            </form>
                                        </motion.div>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Sidebar */}
                        <div className="space-y-6">
                            {/* References */}
                            <div className="glass-card p-6">
                                <h3 className="font-bold mb-4 text-gray-300">References</h3>
                                <div className="space-y-4">
                                    {log.visitor_id && (
                                        <div>
                                            <p className="text-xs text-gray-500 mb-1 flex items-center gap-1"><User size={12} /> Visitor</p>
                                            <button
                                                onClick={() => router.push(`/visitors/${log.visitor_id}`)}
                                                className="text-brand-400 hover:text-brand-300 text-sm font-medium transition-colors"
                                            >
                                                View Visitor Profile
                                            </button>
                                        </div>
                                    )}
                                    {log.camera_id && (
                                        <div>
                                            <p className="text-xs text-gray-500 mb-1 flex items-center gap-1"><Camera size={12} /> Source</p>
                                            <p className="text-sm font-mono text-gray-400 truncate">{log.camera_id}</p>
                                        </div>
                                    )}
                                    {log.face_data_id && (
                                        <div>
                                            <p className="text-xs text-gray-500 mb-1 flex items-center gap-1"><Image size={12} /> Face Data</p>
                                            <p className="text-sm font-mono text-gray-400 truncate">{log.face_data_id}</p>
                                        </div>
                                    )}
                                    {log.source_video && (
                                        <div>
                                            <p className="text-xs text-gray-500 mb-1 flex items-center gap-1"><Video size={12} /> Source</p>
                                            <p className="text-sm text-gray-400 truncate">
                                                {log.source_video === 'live_camera' ? 'Webcam (browser)' : log.source_video}
                                            </p>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Raw Data */}
                            <div className="glass-card p-6">
                                <h3 className="font-bold mb-4 text-gray-300">Raw Data</h3>
                                <div className="space-y-3 text-sm">
                                    <div className="flex justify-between">
                                        <span className="text-gray-500">ID</span>
                                        <span className="text-gray-400 font-mono text-xs truncate ml-4 max-w-[180px]">{log.id}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-gray-500">Status</span>
                                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${getStatusColor(log.status)}`}>{log.status}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-gray-500">Confidence</span>
                                        <span className="text-gray-300">{(log.confidence * 100).toFixed(1)}%</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-gray-500">Identified</span>
                                        <span className={log.identified ? 'text-green-400' : 'text-red-400'}>{log.identified ? 'Yes' : 'No'}</span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span className="text-gray-500">Timestamp</span>
                                        <span className="text-gray-300 text-xs">{new Date(log.timestamp).toISOString()}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </motion.div>
            </main>
        </div>
    )
}

'use client'

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Users, Plus, Edit2, Trash2, X, Check, Search, Mail, Phone, ChevronLeft, ChevronRight, Eye, Upload, Loader, Video, Camera, StopCircle, AlertCircle, Download, ScanFace } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import Navbar from '@/components/Navbar'
import GuidedFaceCapture, { GUIDED_POSES } from '@/components/GuidedFaceCapture'
import { visitorService } from '@/services/api'
import type { Visitor, PaginatedResponse, BulkImportResult } from '@/services/api'
import { getStaticMediaUrl } from '@/lib/utils'
import { useConfirm } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'

export default function VisitorsPage() {
    const router = useRouter()
    const confirm = useConfirm()
    const toast = useToast()
    const [visitors, setVisitors] = useState<Visitor[]>([])
    const [total, setTotal] = useState(0)
    const [page, setPage] = useState(1)
    const [pages, setPages] = useState(1)
    const [loading, setLoading] = useState(true)
    const [search, setSearch] = useState('')
    const [debouncedSearch, setDebouncedSearch] = useState('')
    const [showCreate, setShowCreate] = useState(false)
    const [editingId, setEditingId] = useState<string | null>(null)
    const [form, setForm] = useState({
        name: '', email: '', phone: '', description: '', notes: '', is_known: true
    })
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [creatingVisitor, setCreatingVisitor] = useState(false)
    const [enrollStep, setEnrollStep] = useState(1) // Added for multi-step flow
    const [previews, setPreviews] = useState<string[]>([]) // Added for visual previews

    // Bulk import
    const bulkInputRef = useRef<HTMLInputElement>(null)
    const [bulkImporting, setBulkImporting] = useState(false)
    const [exportingVisitors, setExportingVisitors] = useState(false)
    const [bulkResult, setBulkResult] = useState<BulkImportResult | null>(null)
    const [showBulkResult, setShowBulkResult] = useState(false)
    // Cursor-based pagination — avoids O(N) OFFSET scans on large tables.
    const [nextCursor, setNextCursor] = useState<string | null>(null)
    const [loadingMore, setLoadingMore] = useState(false)
    
    // Media enrollment
    const imageInputRef = useRef<HTMLInputElement>(null)
    const videoInputRef = useRef<HTMLInputElement>(null)
    const cameraVideoRef = useRef<HTMLVideoElement>(null)
    const mediaRecorderRef = useRef<MediaRecorder | null>(null)
    const timerRef = useRef<NodeJS.Timeout | null>(null)
    const [selectedImages, setSelectedImages] = useState<File[]>([])
    const [selectedVideo, setSelectedVideo] = useState<File | null>(null)
    const [cameraStream, setCameraStream] = useState<MediaStream | null>(null)
    const cameraStreamRef = useRef<MediaStream | null>(null)
    const discardRecordingRef = useRef(false)
    const [cameraActive, setCameraActive] = useState(false)
    const [recording, setRecording] = useState(false)
    const [recordingTime, setRecordingTime] = useState(0)
    const [brokenImageIds, setBrokenImageIds] = useState<Record<string, boolean>>({})

    // Guided multi-pose capture: photos collected locally, uploaded per-angle after create
    const [guidedActive, setGuidedActive] = useState(false)
    const [angleCaptures, setAngleCaptures] = useState<Array<{ angle: string; file: File; previewUrl: string }>>([])

    const handleBulkImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return
        setBulkImporting(true)
        setBulkResult(null)
        try {
            const res = await visitorService.bulkImport(file)
            setBulkResult(res.data)
            setShowBulkResult(true)
            fetchVisitors(page, search)
        } catch (err: any) {
            setBulkResult({
                total: 0,
                created: 0,
                face_enrolled: 0,
                errors: [{ row: 0, error: err.response?.data?.detail || 'Bulk import failed' }],
            })
            setShowBulkResult(true)
        } finally {
            setBulkImporting(false)
            if (bulkInputRef.current) bulkInputRef.current.value = ''
        }
    }

    const handleExportVisitors = async () => {
        try {
            setExportingVisitors(true)
            const res = await visitorService.exportCsv({ search: debouncedSearch || undefined })
            const url = window.URL.createObjectURL(new Blob([res.data]))
            const link = document.createElement('a')
            link.href = url
            link.setAttribute('download', 'visitors.csv')
            document.body.appendChild(link)
            link.click()
            link.remove()
            window.URL.revokeObjectURL(url)
            setMessage({ type: 'success', text: 'Visitor CSV export started.' })
        } catch (err: any) {
            console.error('Failed to export visitors:', err)
            setMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to export visitors.' })
        } finally {
            setExportingVisitors(false)
        }
    }

    const resetMediaSelection = () => {
        previews.forEach(p => URL.revokeObjectURL(p))
        setPreviews([])
        setSelectedImages([])
        setSelectedVideo(null)
        setRecording(false)
        setRecordingTime(0)
        angleCaptures.forEach(c => URL.revokeObjectURL(c.previewUrl))
        setAngleCaptures([])
        setGuidedActive(false)
    }

    const closeCreateModal = () => {
        discardRecordingRef.current = true
        if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
            mediaRecorderRef.current.stop()
        }
        setShowCreate(false)
        setEnrollStep(1)
        resetMediaSelection()
        stopCamera()
    }

    const stopCamera = useCallback(() => {
        if (cameraStreamRef.current) {
            cameraStreamRef.current.getTracks().forEach((track) => track.stop())
            cameraStreamRef.current = null
        }
        setCameraStream(null)
        setCameraActive(false)
        setRecording(false)
        if (timerRef.current) {
            clearInterval(timerRef.current)
            timerRef.current = null
        }
        setRecordingTime(0)
    }, [])

    const startCamera = async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
            cameraStreamRef.current = stream
            setCameraStream(stream)
            setCameraActive(true)
        } catch (err) {
            console.error('Error accessing camera:', err)
            setMessage({ type: 'error', text: 'Could not access the camera. Please allow permissions and try again.' })
        }
    }

    const startRecording = () => {
        if (!cameraStreamRef.current) return

        discardRecordingRef.current = false
        const chunks: Blob[] = []
        const mediaRecorder = new MediaRecorder(cameraStreamRef.current)
        mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) chunks.push(event.data)
        }
        mediaRecorder.onstop = () => {
            const blob = new Blob(chunks, { type: 'video/webm' })
            const file = new File([blob], `visitor-enrollment-${Date.now()}.webm`, { type: 'video/webm' })
            if (!discardRecordingRef.current) {
                setSelectedVideo(file)
            }
            setRecording(false)
            if (timerRef.current) {
                clearInterval(timerRef.current)
                timerRef.current = null
            }
            setRecordingTime(0)
            mediaRecorderRef.current = null
            discardRecordingRef.current = false
        }

        mediaRecorderRef.current = mediaRecorder
        mediaRecorder.start()
        setRecording(true)
        setRecordingTime(0)
        timerRef.current = setInterval(() => {
            setRecordingTime((prev) => prev + 1)
        }, 1000)
    }

    const stopRecording = () => {
        if (mediaRecorderRef.current && recording) {
            mediaRecorderRef.current.stop()
        }
    }

    const handleImageSelection = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(e.target.files || [])
        if (files.length) {
            setSelectedImages(files)
            // Visual previews
            previews.forEach(p => URL.revokeObjectURL(p))
            const newPreviews = files.map(f => URL.createObjectURL(f))
            setPreviews(newPreviews)
        }
    }

    const handleVideoSelection = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (file) {
            setSelectedVideo(file)
        }
    }

    useEffect(() => {
        if (cameraActive && cameraStream && cameraVideoRef.current) {
            cameraVideoRef.current.srcObject = cameraStream
        }
    }, [cameraActive, cameraStream])

    useEffect(() => {
        return () => {
            stopCamera()
        }
    }, [stopCamera])

    const fetchVisitors = useCallback(async (p: number, q?: string) => {
        setLoading(true)
        setNextCursor(null)
        try {
            const res = await visitorService.getVisitors({ page: p, limit: 20, search: q || undefined })
            setVisitors(res.data.items)
            setTotal(res.data.total)
            setPages(res.data.pages)
            setNextCursor(res.data.next_cursor ?? null)
        } catch (err: any) {
            if (err.response?.status === 401) {
                router.push('/login')
                return
            }
            console.error('Failed to fetch visitors:', err)
        } finally {
            setLoading(false)
        }
    }, [router])

    const loadMoreVisitors = async () => {
        if (!nextCursor || loadingMore) return
        setLoadingMore(true)
        try {
            const res = await visitorService.getVisitors({
                after_cursor: nextCursor,
                limit: 20,
                search: debouncedSearch || undefined,
            })
            setVisitors(prev => [...prev, ...res.data.items])
            setNextCursor(res.data.next_cursor ?? null)
        } catch (err) {
            console.error('Load more failed:', err)
        } finally {
            setLoadingMore(false)
        }
    }

    // Debounce search input
    useEffect(() => {
        const timer = setTimeout(() => {
            setDebouncedSearch(search)
            setPage(1)
        }, 300)
        return () => clearTimeout(timer)
    }, [search])

    useEffect(() => {
        fetchVisitors(page, debouncedSearch)
    }, [fetchVisitors, page, debouncedSearch])

    // Validate the step-1 detail fields. Returns an error string, or null when
    // the details are good. Email/phone are optional but, when filled, must be
    // well-formed — the browser's native type=email check never fires here
    // because the field is unmounted by the time the form submits on step 2.
    const validateDetails = (): string | null => {
        const name = form.name.trim()
        if (!name) return 'Subject name is required.'
        if (name.length < 2) return 'Subject name must be at least 2 characters.'

        const email = form.email.trim()
        if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            return 'Enter a valid email address, or leave it blank.'
        }

        const phone = form.phone.trim()
        if (phone) {
            const digits = phone.replace(/\D/g, '')
            if (!/^[\d\s+()-]+$/.test(phone) || digits.length < 7) {
                return 'Enter a valid phone number, or leave it blank.'
            }
        }
        return null
    }

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault()
        setMessage(null)

        // Guard: details must be valid even if step 2 was reached directly.
        const detailError = validateDetails()
        if (detailError) {
            setMessage({ type: 'error', text: detailError })
            setEnrollStep(1)
            return
        }

        if (selectedImages.length === 0 && angleCaptures.length === 0) {
            setMessage({ type: 'error', text: 'Capture or upload at least one face image before creating a visitor.' })
            setEnrollStep(2)
            return
        }

        // Client-side size validation before any network call
        const MAX_IMAGE_MB = 10, MAX_VIDEO_MB = 200
        for (const img of selectedImages) {
            if (img.size > MAX_IMAGE_MB * 1024 * 1024) {
                setMessage({ type: 'error', text: `"${img.name}" exceeds ${MAX_IMAGE_MB} MB. Please use a smaller image.` })
                return
            }
        }
        if (selectedVideo && selectedVideo.size > MAX_VIDEO_MB * 1024 * 1024) {
            setMessage({ type: 'error', text: `Video exceeds ${MAX_VIDEO_MB} MB. Please record a shorter clip.` })
            return
        }

        setCreatingVisitor(true)
        try {
            const created = await visitorService.createVisitor({
                name: form.name.trim() || undefined,
                email: form.email.trim() || undefined,
                phone: form.phone.trim() || undefined,
                description: form.description.trim() || undefined,
                notes: form.notes.trim() || undefined,
                is_known: form.is_known,
            })

            let mediaText = ''
            let mediaUploadFailed = false

            // Guided pose captures upload one-by-one so each keeps its angle label
            let posesEnrolled = 0
            const poseWarnings: string[] = []
            for (const capture of angleCaptures) {
                try {
                    await visitorService.uploadFaceImage(created.data.id, capture.file, capture.angle)
                    posesEnrolled += 1
                } catch (poseError: any) {
                    console.error(`Failed to enroll ${capture.angle} pose:`, poseError)
                    poseWarnings.push(poseError?.response?.data?.detail || `${capture.angle} pose failed`)
                }
            }

            if (selectedImages.length > 0 || selectedVideo) {
                try {
                    const mediaRes = await visitorService.uploadMedia(created.data.id, {
                        images: selectedImages,
                        video: selectedVideo,
                    })
                    const parts = []
                    if (mediaRes.data.images_added > 0) {
                        parts.push(`${mediaRes.data.images_added} image${mediaRes.data.images_added > 1 ? 's' : ''}`)
                    }
                    if (mediaRes.data.video_frames_added > 0) {
                        parts.push(`${mediaRes.data.video_frames_added} video frame${mediaRes.data.video_frames_added > 1 ? 's' : ''}`)
                    }
                    mediaText = parts.length ? ` and enrolled ${parts.join(' + ')}` : ''
                    if (mediaRes.data.warnings.length > 0) {
                        mediaText += ` (${mediaRes.data.warnings[0]})`
                    }
                } catch (mediaError: any) {
                    console.error('Failed to upload visitor media:', mediaError)
                    mediaUploadFailed = true
                    mediaText = mediaError?.response?.data?.detail || ''
                }
            }

            if (posesEnrolled > 0) {
                mediaText = ` with ${posesEnrolled} angle pose${posesEnrolled === 1 ? '' : 's'}${mediaText}`
            }
            if (poseWarnings.length > 0) {
                mediaUploadFailed = mediaUploadFailed || posesEnrolled === 0
                mediaText += ` (${poseWarnings[0]})`
            }

            closeCreateModal()
            setForm({ name: '', email: '', phone: '', description: '', notes: '', is_known: true })
            setEnrollStep(1)
            resetMediaSelection()
            setBrokenImageIds((prev) => {
                const next = { ...prev }
                delete next[created.data.id]
                return next
            })
            fetchVisitors(page, debouncedSearch)
            setMessage({
                type: mediaUploadFailed ? 'error' : 'success',
                text: mediaUploadFailed
                    ? `Visitor created, but face upload failed${mediaText ? `: ${mediaText}` : ''}. Add images from the visitor detail page.`
                    : `Visitor created successfully${mediaText}.`,
            })
        } catch (err) {
            console.error('Failed to create visitor:', err)
            setMessage({ type: 'error', text: 'Failed to create visitor.' })
        } finally {
            setCreatingVisitor(false)
        }
    }

    const handleUpdate = async (visitorId: string) => {
        try {
            await visitorService.updateVisitor(visitorId, {
                name: form.name || undefined,
                email: form.email || undefined,
                phone: form.phone || undefined,
                description: form.description || undefined,
                notes: form.notes || undefined,
                is_known: form.is_known,
            })
            setEditingId(null)
            fetchVisitors(page, search)
        } catch (err) {
            console.error('Failed to update visitor:', err)
        }
    }

    const handleDelete = async (visitorId: string) => {
        const target = visitors.find(v => v.id === visitorId)
        const ok = await confirm({
            kind: 'danger',
            title: target ? `Delete ${target.name || 'visitor'}?` : 'Delete visitor?',
            description: 'All faces, logs, and media for this visitor will be permanently removed.',
            confirmLabel: 'Delete visitor',
        })
        if (!ok) return
        try {
            await visitorService.deleteVisitor(visitorId)
            toast.success('Visitor deleted')
            fetchVisitors(page, search)
        } catch (err) {
            toast.error('Failed to delete visitor')
            console.error('Failed to delete visitor:', err)
        }
    }

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-20 px-6 container mx-auto">
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
                    <div>
                        <h1 className="text-3xl font-bold mb-1">Visitors</h1>
                        <p className="text-gray-400">Manage known and detected visitors ({total} total)</p>
                    </div>
                    <div className="flex gap-3 items-center">
                        <div className="relative">
                            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                            <input
                                type="text"
                                placeholder="Search visitors..."
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                className="bg-white/5 border border-white/10 rounded-lg pl-10 pr-4 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 w-56"
                            />
                        </div>
                        <input
                            ref={bulkInputRef}
                            type="file"
                            accept=".csv"
                            onChange={handleBulkImport}
                            className="hidden"
                        />
                        <button
                            onClick={handleExportVisitors}
                            disabled={exportingVisitors}
                            className="bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-white px-4 py-2.5 rounded-lg font-medium transition-colors flex items-center gap-2 text-sm"
                        >
                            {exportingVisitors ? (
                                <><Loader size={16} className="animate-spin" /> Exporting...</>
                            ) : (
                                <><Download size={16} /> Export CSV</>
                            )}
                        </button>
                        <button
                            onClick={() => bulkInputRef.current?.click()}
                            disabled={bulkImporting}
                            className="bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-white px-4 py-2.5 rounded-lg font-medium transition-colors flex items-center gap-2 text-sm"
                        >
                            {bulkImporting ? (
                                <><Loader size={16} className="animate-spin" /> Importing...</>
                            ) : (
                                <><Upload size={16} /> Bulk Import</>
                            )}
                        </button>
                        <button
                            onClick={() => {
                                setShowCreate(true)
                                setEnrollStep(1)
                                setForm({ name: '', email: '', phone: '', description: '', notes: '', is_known: true })
                                resetMediaSelection()
                                setMessage(null)
                                stopCamera()
                            }}
                            className="bg-brand-600 hover:bg-brand-700 text-white px-5 py-2.5 rounded-lg font-medium transition-colors flex items-center gap-2"
                        >
                            <Plus size={18} /> Add Visitor
                        </button>
                    </div>
                </div>

                {message && (
                    <div className={`mb-6 p-4 rounded-lg flex items-center gap-3 ${
                        message.type === 'success'
                            ? 'bg-green-500/10 text-green-400 border border-green-500/20'
                            : 'bg-red-500/10 text-red-400 border border-red-500/20'
                    }`}>
                        {message.type === 'success' ? <Check size={18} /> : <AlertCircle size={18} />}
                        <span className="text-sm">{message.text}</span>
                    </div>
                )}

                {/* Bulk Import Result */}
                {showBulkResult && bulkResult && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center px-4">
                        <div className="glass-card p-6 w-full max-w-md">
                            <div className="flex justify-between items-center mb-4">
                                <h3 className="text-lg font-bold">Bulk Import Results</h3>
                                <button onClick={() => setShowBulkResult(false)} className="text-gray-400 hover:text-white"><X size={20} /></button>
                            </div>
                            <div className="space-y-3 text-sm">
                                <div className="flex justify-between">
                                    <span className="text-gray-400">Total Rows</span>
                                    <span className="font-medium">{bulkResult.total}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-gray-400">Successfully Created</span>
                                    <span className="font-medium text-green-400">{bulkResult.created}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span className="text-gray-400">Faces Enrolled</span>
                                    <span className="font-medium text-brand-300">{bulkResult.face_enrolled || 0}</span>
                                </div>
                                {bulkResult.errors.length > 0 && (
                                    <div>
                                        <p className="text-red-400 font-medium mb-2">Errors ({bulkResult.errors.length}):</p>
                                        <div className="max-h-40 overflow-y-auto space-y-1">
                                            {bulkResult.errors.map((err, i) => (
                                                <p key={i} className="text-xs text-red-300 bg-red-500/10 px-3 py-1.5 rounded">
                                                    Row {err.row}: {err.error}
                                                </p>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                            <button
                                onClick={() => setShowBulkResult(false)}
                                className="w-full mt-4 bg-brand-600 hover:bg-brand-700 text-white py-2.5 rounded-lg font-medium"
                            >
                                Close
                            </button>
                        </div>
                    </motion.div>
                )}

                {/* Create Modal */}
                <AnimatePresence>
                    {showCreate && (
                        <motion.div 
                            initial={{ opacity: 0 }} 
                            animate={{ opacity: 1 }} 
                            exit={{ opacity: 0 }}
                        className="fixed inset-0 bg-black/60 backdrop-blur-md z-50 flex items-center justify-center px-4"
                            onClick={closeCreateModal}
                        >
                            <motion.div 
                                initial={{ scale: 0.95, opacity: 0 }}
                                animate={{ scale: 1, opacity: 1 }}
                                exit={{ scale: 0.95, opacity: 0 }}
                                className="glass-card p-8 w-full max-w-lg"
                                onClick={(e) => e.stopPropagation()}
                            >
                                <div className="mb-6" role="group" aria-label="Enrollment progress">
                                    <div className="flex items-center justify-between mb-2">
                                        <p className="text-sm font-medium text-white">
                                            Step {enrollStep} of 2 — {enrollStep === 1 ? 'Details' : 'Photos'}
                                        </p>
                                        <p className="text-xs text-gray-500">
                                            {enrollStep === 1 ? 'Name, email, and notes' : 'Capture or upload face images'}
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-2" aria-hidden="true">
                                        {[1, 2].map((s) => (
                                            <div key={s} className="flex-1 h-1.5 rounded-full bg-white/10 overflow-hidden">
                                                <motion.div
                                                    className="h-full bg-brand-500"
                                                    initial={{ width: 0 }}
                                                    animate={{ width: enrollStep >= s ? '100%' : '0%' }}
                                                />
                                            </div>
                                        ))}
                                    </div>
                                    <div className="flex items-center justify-between mt-1.5 text-[11px] text-gray-600">
                                        <span className={enrollStep >= 1 ? 'text-brand-400' : ''}>1. Details</span>
                                        <span className={enrollStep >= 2 ? 'text-brand-400' : ''}>2. Photos</span>
                                    </div>
                                </div>

                                <form onSubmit={handleCreate} className="space-y-6">
                                    {enrollStep === 1 ? (
                                        <motion.div 
                                            initial={{ x: 20, opacity: 0 }}
                                            animate={{ x: 0, opacity: 1 }}
                                            className="space-y-5"
                                        >
                                            <div className="grid grid-cols-1 gap-4">
                                                <div className="relative group">
                                                    <input
                                                        type="text"
                                                        placeholder="Subject Name"
                                                        value={form.name}
                                                        onChange={(e) => setForm({ ...form, name: e.target.value })}
                                                        className="w-full bg-white/5 border border-white/10 rounded-2xl px-5 py-4 text-white placeholder-gray-700 focus:border-brand-500/50 focus:ring-4 focus:ring-brand-500/10 outline-none transition-all"
                                                        required
                                                    />
                                                    <Users className="absolute right-5 top-1/2 -translate-y-1/2 text-gray-700 group-focus-within:text-brand-500 transition-colors" size={20} />
                                                </div>

                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                    <div className="relative group">
                                                        <input
                                                            type="email"
                                                            placeholder="Email Contact"
                                                            value={form.email}
                                                            onChange={(e) => setForm({ ...form, email: e.target.value })}
                                                            className="w-full bg-white/5 border border-white/10 rounded-2xl px-5 py-4 text-white placeholder-gray-700 focus:border-brand-500/50 focus:ring-4 focus:ring-brand-500/10 outline-none transition-all"
                                                        />
                                                        <Mail className="absolute right-5 top-1/2 -translate-y-1/2 text-gray-700 group-focus-within:text-brand-500 transition-colors" size={18} />
                                                    </div>
                                                    <div className="relative group">
                                                        <input
                                                            type="tel"
                                                            placeholder="Phone Line"
                                                            value={form.phone}
                                                            onChange={(e) => setForm({ ...form, phone: e.target.value })}
                                                            className="w-full bg-white/5 border border-white/10 rounded-2xl px-5 py-4 text-white placeholder-gray-700 focus:border-brand-500/50 focus:ring-4 focus:ring-brand-500/10 outline-none transition-all"
                                                        />
                                                        <Phone className="absolute right-5 top-1/2 -translate-y-1/2 text-gray-700 group-focus-within:text-brand-500 transition-colors" size={18} />
                                                    </div>
                                                </div>

                                                <div className="relative group">
                                                    <textarea
                                                        placeholder="Quick Bio / Identity Markers (e.g. Wears glasses, Regular courier)"
                                                        value={form.description}
                                                        onChange={(e) => setForm({ ...form, description: e.target.value })}
                                                        rows={2}
                                                        className="w-full bg-white/5 border border-white/10 rounded-2xl px-5 py-4 text-white placeholder-gray-700 focus:border-brand-500/50 focus:ring-4 focus:ring-brand-500/10 outline-none transition-all resize-none"
                                                    />
                                                </div>

                                                <div className="relative group">
                                                    <textarea
                                                        placeholder="Internal Notes (optional — staff-only context, not shown publicly)"
                                                        value={form.notes}
                                                        onChange={(e) => setForm({ ...form, notes: e.target.value })}
                                                        rows={2}
                                                        className="w-full bg-white/5 border border-white/10 rounded-2xl px-5 py-4 text-white placeholder-gray-700 focus:border-brand-500/50 focus:ring-4 focus:ring-brand-500/10 outline-none transition-all resize-none"
                                                    />
                                                </div>

                                                <label className="flex items-center gap-3 text-sm font-medium text-gray-400 cursor-pointer select-none px-1">
                                                    <div className="relative">
                                                        <input
                                                            type="checkbox"
                                                            checked={form.is_known}
                                                            onChange={(e) => setForm({ ...form, is_known: e.target.checked })}
                                                            className="peer sr-only"
                                                        />
                                                        <div className="w-10 h-6 bg-white/10 rounded-full peer-checked:bg-brand-600 transition-colors" />
                                                        <div className="absolute left-1 top-1 w-4 h-4 bg-white rounded-full transition-transform peer-checked:translate-x-4" />
                                                    </div>
                                                    Mark as Pre-registered (Known Subject)
                                                </label>
                                            </div>
                                            
                                            <div className="bg-brand-500/5 border border-brand-500/10 p-3 rounded-xl flex items-center gap-3">
                                                <div className="w-8 h-8 rounded-full bg-brand-500/20 flex items-center justify-center text-brand-400">
                                                    <Check size={16} />
                                                </div>
                                                <p className="text-xs text-brand-300">Biometric data is encrypted and stored locally. GDPR compliant identity hashing applied.</p>
                                            </div>

                                            <div className="flex gap-4 pt-2">
                                                <button 
                                                    type="button" 
                                                    onClick={closeCreateModal}
                                                    className="flex-1 bg-white/5 hover:bg-white/10 text-white py-4 rounded-2xl font-bold transition-all border border-white/5"
                                                >
                                                    Cancel
                                                </button>
                                                <button
                                                    type="button"
                                                    onClick={() => {
                                                        const err = validateDetails()
                                                        if (err) { setMessage({ type: 'error', text: err }); return }
                                                        setMessage(null)
                                                        setEnrollStep(2)
                                                    }}
                                                    className="flex-[2] bg-brand-600 hover:bg-brand-500 text-white py-4 rounded-2xl font-bold transition-all shadow-xl shadow-brand-600/20 flex items-center justify-center gap-2"
                                                >
                                                    Continue Enrollment
                                                    <ChevronRight size={18} />
                                                </button>
                                            </div>
                                        </motion.div>
                                    ) : (
                                        <motion.div 
                                            initial={{ x: 20, opacity: 0 }}
                                            animate={{ x: 0, opacity: 1 }}
                                            className="space-y-6"
                                        >
                                            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 space-y-4">
                                                <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-3">
                                                    <p className="text-xs font-semibold uppercase tracking-widest text-amber-300">
                                                        Face image required
                                                    </p>
                                                    <p className="mt-1 text-sm text-amber-100/80">
                                                        Upload at least one clear face image before completing visitor creation.
                                                    </p>
                                                </div>

                                                <div className="flex items-center justify-between gap-3">
                                                    <div>
                                                        <h4 className="text-sm font-semibold text-white">Capture / Upload Face Data</h4>
                                                        <p className="text-xs text-gray-500">Add clear images or record a quick video clip.</p>
                                                    </div>
                                                </div>

                                                <input ref={imageInputRef} type="file" accept="image/*" multiple onChange={handleImageSelection} className="hidden" />
                                                <input ref={videoInputRef} type="file" accept="video/*" onChange={handleVideoSelection} className="hidden" />

                                                <div className="flex flex-wrap gap-2">
                                                    <button type="button" onClick={() => imageInputRef.current?.click()} className="bg-gray-800 hover:bg-gray-700 text-white px-3 py-2.5 rounded-xl text-xs font-medium transition-colors flex items-center gap-2 flex-1 justify-center">
                                                        <Upload size={14} /> Images
                                                    </button>
                                                    <button type="button" onClick={() => videoInputRef.current?.click()} className="bg-gray-800 hover:bg-gray-700 text-white px-3 py-2.5 rounded-xl text-xs font-medium transition-colors flex items-center gap-2 flex-1 justify-center">
                                                        <Video size={14} /> Video
                                                    </button>
                                                    <button type="button" onClick={cameraActive ? stopCamera : startCamera} className="bg-brand-600/20 hover:bg-brand-600/30 text-brand-400 border border-brand-500/20 px-3 py-2.5 rounded-xl text-xs font-medium transition-colors flex items-center gap-2 flex-[1.5] justify-center">
                                                        <Camera size={14} /> {cameraActive ? 'Close Lens' : 'Live Capture'}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            if (guidedActive) {
                                                                setGuidedActive(false)
                                                                return
                                                            }
                                                            stopCamera()
                                                            angleCaptures.forEach(c => URL.revokeObjectURL(c.previewUrl))
                                                            setAngleCaptures([])
                                                            setGuidedActive(true)
                                                        }}
                                                        title="Step-by-step capture: frontal, 45° left, 45° right, profile, top"
                                                        className="bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/20 px-3 py-2.5 rounded-xl text-xs font-medium transition-colors flex items-center gap-2 flex-[1.5] justify-center"
                                                    >
                                                        <ScanFace size={14} /> {guidedActive ? 'Stop Guided' : 'Guided Poses'}
                                                    </button>
                                                </div>

                                                {guidedActive && (
                                                    <GuidedFaceCapture
                                                        onCapture={(angle, file) => {
                                                            setAngleCaptures(prev => [
                                                                ...prev.filter(c => {
                                                                    if (c.angle !== angle) return true
                                                                    URL.revokeObjectURL(c.previewUrl)
                                                                    return false
                                                                }),
                                                                { angle, file, previewUrl: URL.createObjectURL(file) },
                                                            ])
                                                        }}
                                                        onFinish={() => setGuidedActive(false)}
                                                        onClose={() => setGuidedActive(false)}
                                                    />
                                                )}

                                                {angleCaptures.length > 0 && (
                                                    <div className="pt-1">
                                                        <p className="text-[10px] font-bold text-gray-500 mb-2 uppercase">Guided Pose Captures</p>
                                                        <div className="flex gap-2 overflow-x-auto pb-2 custom-scrollbar">
                                                            {angleCaptures.map((capture) => {
                                                                const pose = GUIDED_POSES.find(p => p.key === capture.angle)
                                                                return (
                                                                    <div key={capture.angle} className="shrink-0">
                                                                        <div className="w-16 h-16 rounded-lg bg-white/5 border border-cyan-500/20 overflow-hidden">
                                                                            <img src={capture.previewUrl} alt={pose?.label || capture.angle} className="w-full h-full object-cover" />
                                                                        </div>
                                                                        <p className="mt-1 text-[9px] font-bold text-cyan-300/80 text-center uppercase">{pose?.label || capture.angle}</p>
                                                                    </div>
                                                                )
                                                            })}
                                                        </div>
                                                    </div>
                                                )}

                                                {cameraActive && (
                                                    <div className="rounded-2xl overflow-hidden border border-white/10 bg-black relative">
                                                        <video ref={cameraVideoRef} autoPlay muted playsInline className="w-full aspect-video object-cover bg-black" />
                                                        <div className="absolute inset-x-0 bottom-0 p-4 bg-gradient-to-t from-black/90 to-transparent flex flex-col items-center">
                                                            {recording && (
                                                                <div className="mb-4 bg-red-600/80 px-4 py-1.5 rounded-full flex items-center gap-2 border border-red-500/30">
                                                                    <div className="w-2 h-2 rounded-full bg-white animate-pulse" />
                                                                    <span className="text-xs font-black text-white uppercase tracking-widest">
                                                                        {Math.floor(recordingTime / 60)}:{String(recordingTime % 60).padStart(2, '0')}
                                                                    </span>
                                                                </div>
                                                            )}
                                                            {!recording ? (
                                                                <button
                                                                    type="button"
                                                                    onClick={startRecording}
                                                                    className="w-16 h-16 bg-red-600 hover:bg-red-500 rounded-full flex items-center justify-center transition-all shadow-2xl border-4 border-white/10 group active:scale-95"
                                                                >
                                                                    <div className="w-6 h-6 rounded-full bg-white group-hover:scale-110 transition-transform" />
                                                                </button>
                                                            ) : (
                                                                <button
                                                                    type="button"
                                                                    onClick={stopRecording}
                                                                    className="w-16 h-16 bg-white hover:bg-gray-200 rounded-full flex items-center justify-center transition-all shadow-2xl active:scale-95"
                                                                >
                                                                    <div className="w-6 h-6 rounded-sm bg-red-600" />
                                                                </button>
                                                            )}
                                                            <p className="mt-3 text-[10px] text-white/50 font-bold uppercase tracking-widest">
                                                                {recording ? 'Recording Interaction' : 'Position Face in Center'}
                                                            </p>
                                                        </div>
                                                    </div>
                                                )}

                                                <AnimatePresence>
                                                    {previews.length > 0 && (
                                                        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} className="pt-2">
                                                            <p className="text-[10px] font-bold text-gray-500 mb-2 uppercase">Selected Enrollments</p>
                                                            <div className="flex gap-2 overflow-x-auto pb-2 custom-scrollbar">
                                                                {previews.map((src, idx) => (
                                                                    <div key={idx} className="w-16 h-16 rounded-lg bg-white/5 border border-white/10 overflow-hidden shrink-0">
                                                                        <img src={src} className="w-full h-full object-cover" />
                                                                    </div>
                                                                ))}
                                                                {selectedVideo && (
                                                                    <div className="w-16 h-16 rounded-lg bg-brand-500/10 border border-brand-500/20 flex flex-col items-center justify-center text-brand-400 shrink-0">
                                                                        <Video size={20} />
                                                                        <span className="text-[8px] font-black mt-1 uppercase">Video</span>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        </motion.div>
                                                    )}
                                                </AnimatePresence>
                                            </div>

                                            <div className="flex gap-4">
                                                <button 
                                                    type="button" 
                                                    onClick={() => setEnrollStep(1)}
                                                    className="flex-1 bg-white/5 hover:bg-white/10 text-white py-4 rounded-2xl font-bold transition-all border border-white/5"
                                                >
                                                    Back
                                                </button>
                                                <button
                                                    type="submit"
                                                    disabled={creatingVisitor || (selectedImages.length === 0 && angleCaptures.length === 0)}
                                                    className="flex-[2] bg-brand-600 hover:bg-brand-500 disabled:bg-brand-600/40 disabled:text-white/60 text-white py-4 rounded-2xl font-bold transition-all shadow-xl shadow-brand-600/20 group flex items-center justify-center gap-2 disabled:cursor-not-allowed"
                                                >
                                                    {creatingVisitor ? (
                                                        <><Loader size={20} className="animate-spin" /> Finalizing Enrollment...</>
                                                    ) : (
                                                        <>
                                                            <Check size={20} className="group-hover:scale-110 transition-transform" />
                                                            Complete Enrollment
                                                        </>
                                                    )}
                                                </button>
                                            </div>
                                        </motion.div>
                                    )}
                                </form>

                            </motion.div>
                        </motion.div>
                    )}
                </AnimatePresence>

                {/* Visitors List */}
                {loading ? (
                    <div className="space-y-3">
                        {[1, 2, 3].map((i) => <div key={i} className="glass-card p-4 animate-pulse h-20" />)}
                    </div>
                ) : visitors.length === 0 ? (
                    <div className="glass-card p-12 text-center">
                        <div className="w-16 h-16 bg-white/5 rounded-full flex items-center justify-center mx-auto mb-4">
                            {debouncedSearch ? <Search className="text-gray-500" size={24} /> : <Users className="text-gray-500" size={24} />}
                        </div>
                        <h3 className="text-lg font-bold mb-2">
                            {debouncedSearch ? `No results for "${debouncedSearch}"` : 'No Visitors Yet'}
                        </h3>
                        <p className="text-gray-400 max-w-xs mx-auto text-sm">
                            {debouncedSearch 
                                ? "Check the spelling or try filtering by 'Known' or 'Unknown' status instead." 
                                : "Add visitors manually or upload a video to auto-detect and populate your database."}
                        </p>
                        {debouncedSearch && (
                            <button 
                                onClick={() => setSearch('')}
                                className="mt-6 text-brand-400 font-bold text-xs uppercase tracking-widest hover:text-brand-300 transition-colors"
                            >
                                Clear Search
                            </button>
                        )}
                    </div>
                ) : (
                    <>
                        <div className="space-y-3">
                            {visitors.map((visitor) => (
                                <motion.div
                                    key={visitor.id}
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    className="glass-card p-4 flex items-center justify-between gap-4"
                                >
                                    <div className="flex items-center gap-4 flex-1 min-w-0">
                                        <div className="w-12 h-12 rounded-lg bg-gray-800 flex items-center justify-center shrink-0 overflow-hidden border border-white/5">
                                            {getStaticMediaUrl(visitor.primary_face_image_url) && !brokenImageIds[visitor.id] ? (
                                                <img
                                                    src={getStaticMediaUrl(visitor.primary_face_image_url)!}
                                                    alt={visitor.name || 'Visitor'}
                                                    className="w-full h-full object-cover"
                                                    onError={() => {
                                                        setBrokenImageIds((prev) => ({ ...prev, [visitor.id]: true }))
                                                    }}
                                                />
                                            ) : (
                                                <Users className="text-gray-500" size={20} />
                                            )}
                                        </div>
                                        {editingId === visitor.id ? (
                                            <div className="flex-1 flex gap-2">
                                                <input
                                                    value={form.name}
                                                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                                                    className="flex-1 bg-white/5 border border-white/10 rounded px-3 py-1.5 text-white text-sm focus:outline-none focus:border-brand-500"
                                                    placeholder="Name"
                                                />
                                                <button onClick={() => handleUpdate(visitor.id)} className="text-green-400 hover:text-green-300"><Check size={18} /></button>
                                                <button onClick={() => setEditingId(null)} className="text-gray-400 hover:text-white"><X size={18} /></button>
                                            </div>
                                        ) : (
                                            <div className="min-w-0 flex-1">
                                                <div className="flex items-center gap-2">
                                                    <h3 className="font-semibold truncate">{visitor.name || 'Unidentified'}</h3>
                                                    {!visitor.is_active && (
                                                        <span className="text-xs px-1.5 py-0.5 rounded bg-gray-500/20 text-gray-400">Inactive</span>
                                                    )}
                                                    {(visitor.face_count || 0) > 0 && (
                                                        <span className="text-xs px-1.5 py-0.5 rounded bg-brand-500/10 text-brand-400">
                                                            {visitor.face_count} face{visitor.face_count === 1 ? '' : 's'}
                                                        </span>
                                                    )}
                                                </div>
                                                <p className="text-sm text-gray-400 truncate">{visitor.description || 'No description'}</p>
                                                <div className="flex gap-3 text-xs text-gray-500 mt-0.5">
                                                    {visitor.email && (
                                                        <span className="flex items-center gap-1"><Mail size={10} /> {visitor.email}</span>
                                                    )}
                                                    {visitor.phone && (
                                                        <span className="flex items-center gap-1"><Phone size={10} /> {visitor.phone}</span>
                                                    )}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-3 shrink-0">
                                        <span className={`text-xs px-2 py-1 rounded ${visitor.is_known ? 'bg-green-400/10 text-green-400' : 'bg-yellow-400/10 text-yellow-400'}`}>
                                            {visitor.is_known ? 'Known' : 'Unknown'}
                                        </span>
                                        <Link
                                            href={`/visitors/${visitor.id}`}
                                            aria-label={`View details for ${visitor.name || 'visitor'}`}
                                            title="View details"
                                            className="text-gray-400 hover:text-brand-500"
                                        >
                                            <Eye size={16} />
                                        </Link>
                                        <button
                                            onClick={() => {
                                                setEditingId(visitor.id)
                                                setForm({
                                                    name: visitor.name || '',
                                                    email: visitor.email || '',
                                                    phone: visitor.phone || '',
                                                    description: visitor.description || '',
                                                    notes: visitor.notes || '',
                                                    is_known: visitor.is_known
                                                })
                                            }}
                                            aria-label={`Edit ${visitor.name || 'visitor'}`}
                                            title="Edit"
                                            className="text-gray-400 hover:text-brand-500"
                                        >
                                            <Edit2 size={16} />
                                        </button>
                                        <button
                                            onClick={() => handleDelete(visitor.id)}
                                            aria-label={`Delete ${visitor.name || 'visitor'}`}
                                            title="Delete"
                                            className="text-gray-400 hover:text-red-400"
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    </div>
                                </motion.div>
                            ))}
                        </div>

                        {/* Pagination — offset mode */}
                        {pages > 1 && (
                            <div className="flex items-center justify-center gap-4 mt-8">
                                <button
                                    onClick={() => setPage(Math.max(1, page - 1))}
                                    disabled={page <= 1}
                                    className="flex items-center gap-1 px-3 py-2 rounded-lg bg-white/5 text-gray-400 hover:text-white disabled:opacity-30 text-sm"
                                >
                                    <ChevronLeft size={16} /> Previous
                                </button>
                                <span className="text-sm text-gray-400">
                                    Page {page} of {pages}
                                </span>
                                <button
                                    onClick={() => setPage(Math.min(pages, page + 1))}
                                    disabled={page >= pages}
                                    className="flex items-center gap-1 px-3 py-2 rounded-lg bg-white/5 text-gray-400 hover:text-white disabled:opacity-30 text-sm"
                                >
                                    Next <ChevronRight size={16} />
                                </button>
                            </div>
                        )}

                        {/* Load More — cursor mode (efficient for large tables) */}
                        {nextCursor && (
                            <div className="flex justify-center mt-6">
                                <button
                                    onClick={loadMoreVisitors}
                                    disabled={loadingMore}
                                    className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white disabled:opacity-40 text-sm transition-colors"
                                >
                                    {loadingMore ? (
                                        <Loader size={15} className="animate-spin" />
                                    ) : (
                                        <ChevronRight size={15} />
                                    )}
                                    {loadingMore ? 'Loading…' : 'Load More'}
                                </button>
                            </div>
                        )}
                    </>
                )}
            </main>
        </div>
    )
}

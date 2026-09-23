'use client'

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import {
    ArrowLeft, User, Edit2, Save, X, Trash2, ImagePlus, Star,
    Clock, Eye, Phone, Mail, StickyNote, AlertCircle, CheckCircle, FileText, Upload, Loader,
    Sliders, Brain, FolderUp, Video, Camera, StopCircle, FlipHorizontal,
    ChevronRight, CheckCircle2, History, ShieldCheck, ScanFace
} from 'lucide-react'
import Navbar from '@/components/Navbar'
import MediaImage from '@/components/MediaImage'
import GuidedFaceCapture from '@/components/GuidedFaceCapture'
import { visitorService, VisitorDetail, FaceData, modelService, accuracyService, logService } from '@/services/api'
import type { VisitorLog } from '@/services/api'
import { getStaticMediaUrl } from '@/lib/utils'
import { useConfirm } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'

const FACE_ANGLE_OPTIONS = [
    { value: 'auto', label: 'Auto', desc: 'Let AI decide', emoji: '🤖' },
    { value: 'frontal', label: 'Frontal', desc: 'Face straight ahead', emoji: '😐' },
    { value: '45_left', label: '45° Left', desc: 'Slight left turn', emoji: '↖️' },
    { value: '45_right', label: '45° Right', desc: 'Slight right turn', emoji: '↗️' },
    { value: 'profile', label: 'Profile', desc: 'Full side view', emoji: '👤' },
    { value: 'top', label: 'Top', desc: 'Looking down at face', emoji: '⬇️' },
]

// Visual angle selector component
function VisualAngleSelector({ value, onChange }: { value: string; onChange: (v: string) => void }) {
    return (
        <div className="grid grid-cols-3 gap-2">
            {FACE_ANGLE_OPTIONS.map(opt => (
                <button
                    key={opt.value}
                    type="button"
                    onClick={() => onChange(opt.value)}
                    title={opt.desc}
                    className={`flex flex-col items-center gap-1 px-2 py-2.5 rounded-xl border text-xs transition-all ${
                        value === opt.value
                            ? 'border-brand-500/60 bg-brand-500/10 text-white'
                            : 'border-white/10 bg-white/5 text-gray-400 hover:border-white/20 hover:text-white'
                    }`}
                >
                    <span className="text-lg leading-none">{opt.emoji}</span>
                    <span className="font-medium leading-tight text-center">{opt.label}</span>
                </button>
            ))}
        </div>
    )
}

// Confidence badge helper
function ConfidencePill({ confidence }: { confidence: number }) {
    const pct = Math.round(confidence * 100)
    if (pct <= 0) return null
    const cls = pct >= 80 ? 'text-green-400 bg-green-400/10' : pct >= 60 ? 'text-yellow-400 bg-yellow-400/10' : 'text-red-400 bg-red-400/10'
    const label = pct >= 80 ? 'High' : pct >= 60 ? 'Review' : 'Low'
    return <span className={`text-xs px-2 py-0.5 rounded font-medium ${cls}`}>{pct}% · {label}</span>
}

const FACE_ANGLE_LABELS: Record<string, string> = {
    frontal: 'Frontal',
    '45_left': '45 Left',
    '45_right': '45 Right',
    profile: 'Profile',
    top: 'Top',
    unknown: 'Unknown',
}

const normalizeFaceAngle = (angle?: string | null): string | null => {
    if (!angle) return null
    const value = angle.toLowerCase()
    if (value === 'profile_left' || value === 'profile_right') return 'profile'
    if (value === 'top_down' || value === 'topdown') return 'top'
    return value
}

const formatFaceAngle = (angle?: string | null): string => {
    const normalized = normalizeFaceAngle(angle) || 'unknown'
    return FACE_ANGLE_LABELS[normalized] || FACE_ANGLE_LABELS.unknown
}

export default function VisitorDetailPage() {
    const params = useParams()
    const router = useRouter()
    const confirm = useConfirm()
    const toast = useToast()
    const visitorId = params.id as string

    const [visitor, setVisitor] = useState<VisitorDetail | null>(null)
    const [loading, setLoading] = useState(true)
    const [editing, setEditing] = useState(false)
    const [saving, setSaving] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

    const [formData, setFormData] = useState({
        name: '',
        email: '',
        phone: '',
        description: '',
        notes: '',
        is_known: false,
        is_active: true,
    })

    // S16: Adaptive threshold & auto-learn
    const [customThreshold, setCustomThreshold] = useState<number | null>(null)
    const [autoLearn, setAutoLearn] = useState(false)
    const [savingThreshold, setSavingThreshold] = useState(false)

    // Detection history
    const [detectionHistory, setDetectionHistory] = useState<VisitorLog[]>([])
    const [loadingHistory, setLoadingHistory] = useState(false)

    // S14: Batch upload
    const batchInputRef = useRef<HTMLInputElement>(null)
    const [batchUploading, setBatchUploading] = useState(false)
    const [batchResults, setBatchResults] = useState<{ processed: number; failed: number } | null>(null)

    // Per-file upload progress tracking
    const [uploadProgress, setUploadProgress] = useState<Record<string, 'pending' | 'uploading' | 'done' | 'error'>>({})

    // Camera facing mode for mobile
    const [cameraFacingMode, setCameraFacingMode] = useState<'user' | 'environment'>('user')

    // Media enrollment
    const imageInputRef = useRef<HTMLInputElement>(null)
    const videoInputRef = useRef<HTMLInputElement>(null)
    const cameraVideoRef = useRef<HTMLVideoElement>(null)
    const mediaRecorderRef = useRef<MediaRecorder | null>(null)
    const timerRef = useRef<NodeJS.Timeout | null>(null)
    const cameraStreamRef = useRef<MediaStream | null>(null)
    const mediaEnrollmentRef = useRef<HTMLDivElement>(null)
    const discardRecordingRef = useRef(false)
    const [cameraStream, setCameraStream] = useState<MediaStream | null>(null)
    const [cameraActive, setCameraActive] = useState(false)
    const [recording, setRecording] = useState(false)
    const [recordingTime, setRecordingTime] = useState(0)
    const [selectedImages, setSelectedImages] = useState<File[]>([])
    const [selectedVideo, setSelectedVideo] = useState<File | null>(null)
    const [uploadingMedia, setUploadingMedia] = useState(false)
    const [primaryFaceUpdatingId, setPrimaryFaceUpdatingId] = useState<string | null>(null)
    const [brokenMediaUrls, setBrokenMediaUrls] = useState<Record<string, boolean>>({})

    // Guided multi-pose capture
    const [guidedActive, setGuidedActive] = useState(false)
    const [guidedQueue, setGuidedQueue] = useState<string[]>([])

    const fetchDetectionHistory = useCallback(async () => {
        setLoadingHistory(true)
        try {
            const res = await logService.getLogs({ limit: 50 })
            const items = (res.data.items || []).filter((l: VisitorLog) => l.visitor_id === visitorId)
            setDetectionHistory(items)
        } catch {
            // non-critical — silently ignore
        } finally {
            setLoadingHistory(false)
        }
    }, [visitorId])

    useEffect(() => {
        fetchVisitor()
        fetchDetectionHistory()
    }, [visitorId]) // eslint-disable-line

    useEffect(() => {
        if (!visitor) return
        if (typeof window === 'undefined') return

        const shouldFocusMedia =
            window.location.hash === '#media-enrollment' ||
            new URLSearchParams(window.location.search).get('focus') === 'media-enrollment'

        if (!shouldFocusMedia) return

        const timer = window.setTimeout(() => {
            mediaEnrollmentRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }, 150)

        return () => window.clearTimeout(timer)
    }, [visitor])

    const fetchVisitor = async () => {
        try {
            const res = await visitorService.getVisitor(visitorId)
            setVisitor(res.data)
            setFormData({
                name: res.data.name || '',
                email: res.data.email || '',
                phone: res.data.phone || '',
                description: res.data.description || '',
                notes: res.data.notes || '',
                is_known: res.data.is_known,
                is_active: res.data.is_active,
            })
            setCustomThreshold(res.data.custom_threshold ?? null)
            setAutoLearn(res.data.auto_learn ?? false)
        } catch (err: any) {
            if (err.response?.status === 401) {
                router.push('/login')
                return
            }
            if (err.response?.status === 404) {
                setMessage({ type: 'error', text: 'Visitor not found' })
            }
        } finally {
            setLoading(false)
        }
    }

    const handleSave = async () => {
        setSaving(true)
        setMessage(null)
        try {
            await visitorService.updateVisitor(visitorId, formData)
            setMessage({ type: 'success', text: 'Visitor updated successfully!' })
            setEditing(false)
            fetchVisitor()
        } catch {
            setMessage({ type: 'error', text: 'Failed to update visitor' })
        } finally {
            setSaving(false)
        }
    }

    const handleDelete = async () => {
        const ok = await confirm({
            kind: 'danger',
            title: visitor?.name ? `Delete ${visitor.name}?` : 'Delete visitor?',
            description: 'All enrolled faces, detection logs, and media will be permanently deleted. This cannot be undone.',
            confirmLabel: 'Delete visitor',
        })
        if (!ok) return
        try {
            await visitorService.deleteVisitor(visitorId)
            toast.success('Visitor deleted')
            router.push('/visitors')
        } catch {
            toast.error('Failed to delete visitor')
        }
    }

    const handleDeleteFace = async (faceDataId: string) => {
        const ok = await confirm({
            kind: 'danger',
            title: 'Delete face data?',
            description: 'This face capture will be removed from the visitor. Future detections may be less accurate.',
            confirmLabel: 'Delete face',
        })
        if (!ok) return
        try {
            await visitorService.deleteFaceData(visitorId, faceDataId)
            toast.success('Face data removed')
            fetchVisitor()
        } catch {
            toast.error('Failed to delete face data')
        }
    }

    const resetMediaSelection = () => {
        setSelectedImages([])
        setSelectedVideo(null)
        if (imageInputRef.current) imageInputRef.current.value = ''
        if (videoInputRef.current) videoInputRef.current.value = ''
    }

    const stopCamera = useCallback(() => {
        if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
            discardRecordingRef.current = true
            mediaRecorderRef.current.stop()
        }
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

    const startCamera = async (facingMode: 'user' | 'environment' = cameraFacingMode) => {
        try {
            if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
                setMessage({ type: 'error', text: 'Camera recording is not supported in this browser.' })
                return
            }
            // Stop existing stream before switching
            if (cameraStreamRef.current) {
                cameraStreamRef.current.getTracks().forEach(t => t.stop())
                cameraStreamRef.current = null
            }
            const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode }, audio: false })
            cameraStreamRef.current = stream
            setCameraStream(stream)
            setCameraActive(true)
            setCameraFacingMode(facingMode)
        } catch {
            setMessage({ type: 'error', text: 'Could not access the camera. Please allow permissions and try again.' })
        }
    }

    const flipCamera = () => {
        const next: 'user' | 'environment' = cameraFacingMode === 'user' ? 'environment' : 'user'
        void startCamera(next)
    }

    const startRecording = () => {
        if (!cameraStreamRef.current || typeof MediaRecorder === 'undefined') return

        discardRecordingRef.current = false
        const chunks: Blob[] = []
        const recorder = new MediaRecorder(cameraStreamRef.current)

        recorder.ondataavailable = (event) => {
            if (event.data.size > 0) chunks.push(event.data)
        }
        recorder.onstop = () => {
            const blob = new Blob(chunks, { type: 'video/webm' })
            const file = new File([blob], `visitor-enrollment-${Date.now()}.webm`, { type: 'video/webm' })
            if (!discardRecordingRef.current) {
                setSelectedVideo(file)
                setMessage({ type: 'success', text: 'Camera recording saved. Click enroll to process it.' })
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

        mediaRecorderRef.current = recorder
        recorder.start()
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
            // Reset progress state for new selection
            const initial: Record<string, 'pending' | 'uploading' | 'done' | 'error'> = {}
            files.forEach(f => { initial[f.name] = 'pending' })
            setUploadProgress(initial)
        }
    }

    const handleVideoSelection = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (file) {
            setSelectedVideo(file)
        }
    }

    const handleSetPrimaryFace = async (faceDataId: string) => {
        setPrimaryFaceUpdatingId(faceDataId)
        setMessage(null)
        try {
            await visitorService.setPrimaryFace(visitorId, faceDataId)
            setMessage({ type: 'success', text: 'Primary face updated successfully.' })
            fetchVisitor()
        } catch (err: any) {
            const detail = err.response?.data?.detail
            setMessage({ type: 'error', text: detail || 'Failed to update primary face' })
        } finally {
            setPrimaryFaceUpdatingId(null)
        }
    }

    const handleEnrollMedia = async () => {
        if (selectedImages.length === 0 && !selectedVideo) {
            setMessage({ type: 'error', text: 'Select at least one image or video before enrolling media.' })
            return
        }

        setUploadingMedia(true)
        setMessage(null)

        // Mark all selected images as uploading
        if (selectedImages.length > 0) {
            const uploading: Record<string, 'pending' | 'uploading' | 'done' | 'error'> = {}
            selectedImages.forEach(f => { uploading[f.name] = 'uploading' })
            setUploadProgress(uploading)
        }

        try {
            const res = await visitorService.uploadMedia(visitorId, {
                images: selectedImages,
                video: selectedVideo,
            })

            // Mark all as done on success
            if (selectedImages.length > 0) {
                const done: Record<string, 'pending' | 'uploading' | 'done' | 'error'> = {}
                selectedImages.forEach(f => { done[f.name] = 'done' })
                setUploadProgress(done)
            }

            const pieces = []
            if (res.data.images_added > 0) pieces.push(`${res.data.images_added} image${res.data.images_added === 1 ? '' : 's'}`)
            if (res.data.video_frames_added > 0) pieces.push(`${res.data.video_frames_added} video frame${res.data.video_frames_added === 1 ? '' : 's'}`)

            await fetchVisitor()
            resetMediaSelection()
            setUploadProgress({})
            setMessage({
                type: 'success',
                text: `${pieces.length ? `Media enrolled successfully: ${pieces.join(' + ')}.` : 'Media processed successfully.'}${res.data.warnings.length > 0 ? ` Warning: ${res.data.warnings[0]}` : ''}`,
            })
        } catch (err: any) {
            // Mark all as error
            if (selectedImages.length > 0) {
                const errState: Record<string, 'pending' | 'uploading' | 'done' | 'error'> = {}
                selectedImages.forEach(f => { errState[f.name] = 'error' })
                setUploadProgress(errState)
            }
            const detail = err.response?.data?.detail
            setMessage({ type: 'error', text: detail || 'Failed to process visitor media' })
        } finally {
            setUploadingMedia(false)
        }
    }

    const enrolledVideoUrls = Array.isArray(visitor?.metadata?.enrollment_media?.video_urls)
        ? visitor?.metadata?.enrollment_media?.video_urls ?? []
        : []
    const enrolledFaceImages = visitor?.face_data?.filter((face) => !!face.image_url) ?? []
    const primaryFace = enrolledFaceImages.find((face) => face.is_primary) ?? enrolledFaceImages[0] ?? null

    // Face image upload
    const faceInputRef = useRef<HTMLInputElement>(null)
    const [uploadingFace, setUploadingFace] = useState(false)
    const [selectedFaceAngle, setSelectedFaceAngle] = useState('auto')

    const handleFaceUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0]
        if (!file) return
        if (visitor && (visitor.face_data?.length || 0) >= 5) {
            setMessage({ type: 'error', text: 'Face data limit reached. Delete an image before adding more.' })
            if (faceInputRef.current) faceInputRef.current.value = ''
            return
        }
        setUploadingFace(true)
        setMessage(null)
        try {
            const angleHint = selectedFaceAngle === 'auto' ? undefined : selectedFaceAngle
            const res = await visitorService.uploadFaceImage(visitorId, file, angleHint)
            setMessage({ type: 'success', text: res.data.message || 'Face image uploaded and processed!' })
            fetchVisitor()
        } catch (err: any) {
            const detail = err.response?.data?.detail
            setMessage({ type: 'error', text: detail || 'Failed to upload face image' })
        } finally {
            setUploadingFace(false)
            if (faceInputRef.current) faceInputRef.current.value = ''
        }
    }

    // Guided multi-pose capture: MediaPipe detects head yaw/pitch live, auto-snaps
    // each missing angle, uploads with the angle hint so coverage maps correctly.
    const startGuidedCapture = () => {
        const captured = new Set(
            (visitor?.face_data || [])
                .map((face) => normalizeFaceAngle(face.face_angle))
                .filter((angle): angle is string => Boolean(angle))
        )
        const allPoses = FACE_ANGLE_OPTIONS.filter((o) => o.value !== 'auto').map((o) => o.value)
        const remainingSlots = 5 - (visitor?.face_data?.length || 0)
        if (remainingSlots <= 0) {
            setMessage({ type: 'error', text: 'Face data limit reached. Delete an image before guided capture.' })
            return
        }
        const queue = allPoses.filter((p) => !captured.has(p)).slice(0, remainingSlots)
        if (queue.length === 0) {
            setMessage({ type: 'success', text: 'All face angles are already captured for this visitor.' })
            return
        }
        stopCamera() // wizard owns its own camera stream
        setMessage(null)
        setGuidedQueue(queue)
        setGuidedActive(true)
    }

    const handleGuidedCapture = async (angle: string, file: File) => {
        await visitorService.uploadFaceImage(visitorId, file, angle)
        fetchVisitor()
    }

    const handleGuidedFinish = (capturedAngles: string[]) => {
        setGuidedActive(false)
        setMessage({
            type: 'success',
            text: capturedAngles.length > 0
                ? `Guided capture complete — ${capturedAngles.length} pose${capturedAngles.length === 1 ? '' : 's'} enrolled.`
                : 'Guided capture finished without new captures.',
        })
        fetchVisitor()
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

    // S14: Batch upload handler
    const handleBatchUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files
        if (!files || files.length === 0) return
        if (faceLimitReached) {
            setMessage({ type: 'error', text: 'Face data limit reached. Delete an image before adding more.' })
            if (batchInputRef.current) batchInputRef.current.value = ''
            return
        }
        setBatchUploading(true)
        setBatchResults(null)
        setMessage(null)
        try {
            const res = await modelService.batchUpload(visitorId, Array.from(files))
            setBatchResults({ processed: res.data.processed || res.data.success_count || files.length, failed: res.data.failed || res.data.error_count || 0 })
            setMessage({ type: 'success', text: `Batch upload complete: ${res.data.processed || res.data.success_count || files.length} processed` })
            fetchVisitor()
        } catch (err: any) {
            const detail = err.response?.data?.detail
            setMessage({ type: 'error', text: detail || 'Batch upload failed' })
        } finally {
            setBatchUploading(false)
            if (batchInputRef.current) batchInputRef.current.value = ''
        }
    }

    // S16: Save adaptive threshold
    const handleSaveThreshold = async () => {
        setSavingThreshold(true)
        setMessage(null)
        try {
            await accuracyService.setVisitorThreshold(visitorId, {
                custom_threshold: customThreshold,
                auto_learn: autoLearn,
            })
            setMessage({ type: 'success', text: 'Recognition settings saved!' })
        } catch {
            setMessage({ type: 'error', text: 'Failed to save recognition settings' })
        } finally {
            setSavingThreshold(false)
        }
    }

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

    if (!visitor) {
        return (
            <div className="min-h-screen">
                <Navbar />
                <main className="pt-24 pb-20 px-6 container mx-auto">
                    <div className="glass-card p-12 text-center">
                        <AlertCircle size={48} className="text-red-400 mx-auto mb-4" />
                        <h2 className="text-2xl font-bold mb-2">Visitor Not Found</h2>
                        <p className="text-gray-400 mb-6">The visitor you are looking for does not exist.</p>
                        <button
                            onClick={() => router.push('/visitors')}
                            className="bg-brand-600 hover:bg-brand-700 text-white px-6 py-3 rounded-lg font-medium transition-colors"
                        >
                            Back to Visitors
                        </button>
                    </div>
                </main>
            </div>
        )
    }

    const faceEntries = [...(visitor.face_data || [])].sort((a, b) => {
        if (a.is_primary !== b.is_primary) {
            return a.is_primary ? -1 : 1
        }
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    })

    const maxFaceEntries = 5
    const faceLimitReached = (visitor.face_data?.length || 0) >= maxFaceEntries
    const availableAngles = new Set(
        (visitor.face_data || [])
            .map((face) => normalizeFaceAngle(face.face_angle))
            .filter((angle): angle is string => Boolean(angle))
    )
    const requiredAngles = FACE_ANGLE_OPTIONS.filter((option) => option.value !== 'auto')
    const missingAngles = requiredAngles.filter((option) => !availableAngles.has(option.value))

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-24 px-6 container mx-auto">
                {/* Breadcrumb */}
                <nav className="flex items-center gap-2 text-xs text-gray-500 mb-6">
                    <Link href="/" className="hover:text-white transition-colors">Dashboard</Link>
                    <ChevronRight size={12} />
                    <Link href="/visitors" className="hover:text-white transition-colors">Visitors</Link>
                    <ChevronRight size={12} />
                    <span className="text-gray-300">{visitor?.name || 'Visitor Detail'}</span>
                </nav>

                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                >
                    {/* Back button + title */}
                    <div className="flex items-center gap-4 mb-8">
                        <button
                            onClick={() => router.push('/visitors')}
                            className="p-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                        >
                            <ArrowLeft size={20} />
                        </button>
                        <div className="w-16 h-16 rounded-2xl bg-gray-800 border border-white/5 overflow-hidden shrink-0">
                            {getStaticMediaUrl(visitor.primary_face_image_url) ? (
                                <MediaImage
                                    sources={[visitor.primary_face_image_url]}
                                    alt={visitor.name || 'Visitor'}
                                    className="w-full h-full object-cover"
                                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                                />
                            ) : (
                                <div className="w-full h-full flex items-center justify-center">
                                    <User className="text-gray-600" size={28} />
                                </div>
                            )}
                        </div>
                        <div className="flex-1">
                            <h1 className="text-3xl font-extrabold bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
                                {visitor.name || 'Unknown Visitor'}
                            </h1>
                            <div className="flex items-center gap-3 mt-1">
                                {visitor.is_known ? (
                                    <span className="text-xs bg-green-400/10 text-green-400 px-2 py-1 rounded">Known</span>
                                ) : (
                                    <span className="text-xs bg-yellow-400/10 text-yellow-400 px-2 py-1 rounded">Unknown</span>
                                )}
                                {!visitor.is_active && (
                                    <span className="text-xs bg-red-400/10 text-red-400 px-2 py-1 rounded">Inactive</span>
                                )}
                                <span className="text-sm text-gray-500">
                                    Created {new Date(visitor.created_at).toLocaleDateString()}
                                </span>
                                {(visitor.face_count || 0) > 0 && (
                                    <span className="text-xs bg-brand-500/10 text-brand-400 px-2 py-1 rounded">
                                        {visitor.face_count} face{visitor.face_count === 1 ? '' : 's'}
                                    </span>
                                )}
                            </div>
                        </div>
                        <div className="flex gap-2">
                            {editing ? (
                                <>
                                    <button
                                        onClick={() => setEditing(false)}
                                        className="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        <X size={16} /> Cancel
                                    </button>
                                    <button
                                        onClick={handleSave}
                                        disabled={saving}
                                        className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        <Save size={16} /> {saving ? 'Saving...' : 'Save'}
                                    </button>
                                </>
                            ) : (
                                <>
                                    <Link
                                        href={`/settings/consent?visitor_id=${visitor.id}`}
                                        className="bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                        title="Manage data-processing consent for this visitor"
                                    >
                                        <ShieldCheck size={16} /> Consent
                                    </Link>
                                    <button
                                        onClick={() => setEditing(true)}
                                        className="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        <Edit2 size={16} /> Edit
                                    </button>
                                    <button
                                        onClick={handleDelete}
                                        className="bg-red-500/10 hover:bg-red-500/20 text-red-400 px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        <Trash2 size={16} /> Delete
                                    </button>
                                </>
                            )}
                        </div>
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
                        {/* Visitor Details */}
                        <div className="lg:col-span-2 space-y-6">
                            <div className="glass-card p-6">
                                <div className="flex items-center gap-3 mb-6">
                                    <div className="p-2 bg-brand-500/10 rounded-lg">
                                        <User className="text-brand-500" size={24} />
                                    </div>
                                    <h2 className="text-xl font-bold">Details</h2>
                                </div>

                                {editing ? (
                                    <div className="space-y-4">
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            <div>
                                                <label className="block text-sm font-medium text-gray-300 mb-2">Name</label>
                                                <input
                                                    type="text"
                                                    value={formData.name}
                                                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                                    className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors"
                                                    placeholder="Visitor name"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-sm font-medium text-gray-300 mb-2">Email</label>
                                                <input
                                                    type="email"
                                                    value={formData.email}
                                                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                                                    className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors"
                                                    placeholder="visitor@example.com"
                                                />
                                            </div>
                                        </div>
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                            <div>
                                                <label className="block text-sm font-medium text-gray-300 mb-2">Phone</label>
                                                <input
                                                    type="text"
                                                    value={formData.phone}
                                                    onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                                                    className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors"
                                                    placeholder="+1 234 567 8900"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-sm font-medium text-gray-300 mb-2">Description</label>
                                                <input
                                                    type="text"
                                                    value={formData.description}
                                                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                                                    className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors"
                                                    placeholder="Brief description"
                                                />
                                            </div>
                                        </div>
                                        <div>
                                            <label className="block text-sm font-medium text-gray-300 mb-2">Notes</label>
                                            <textarea
                                                value={formData.notes}
                                                onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                                                rows={3}
                                                className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors resize-none"
                                                placeholder="Additional notes..."
                                            />
                                        </div>
                                        <div className="flex gap-6">
                                            <label className="flex items-center gap-2 cursor-pointer">
                                                <input
                                                    type="checkbox"
                                                    checked={formData.is_known}
                                                    onChange={(e) => setFormData({ ...formData, is_known: e.target.checked })}
                                                    className="w-4 h-4 accent-brand-500 rounded"
                                                />
                                                <span className="text-sm text-gray-300">Known Visitor</span>
                                            </label>
                                            <label className="flex items-center gap-2 cursor-pointer">
                                                <input
                                                    type="checkbox"
                                                    checked={formData.is_active}
                                                    onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                                                    className="w-4 h-4 accent-brand-500 rounded"
                                                />
                                                <span className="text-sm text-gray-300">Active</span>
                                            </label>
                                        </div>
                                    </div>
                                ) : (
                                    <div className="space-y-4">
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                            <div className="flex items-center gap-3">
                                                <Mail size={18} className="text-gray-500" />
                                                <div>
                                                    <p className="text-xs text-gray-500">Email</p>
                                                    <p className="text-gray-200">{visitor.email || 'Not provided'}</p>
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-3">
                                                <Phone size={18} className="text-gray-500" />
                                                <div>
                                                    <p className="text-xs text-gray-500">Phone</p>
                                                    <p className="text-gray-200">{visitor.phone || 'Not provided'}</p>
                                                </div>
                                            </div>
                                        </div>
                                        {visitor.description && (
                                            <div className="flex items-start gap-3">
                                                <FileText size={18} className="text-gray-500 mt-0.5" />
                                                <div>
                                                    <p className="text-xs text-gray-500">Description</p>
                                                    <p className="text-gray-200">{visitor.description}</p>
                                                </div>
                                            </div>
                                        )}
                                        {visitor.notes && (
                                            <div className="flex items-start gap-3">
                                                <StickyNote size={18} className="text-gray-500 mt-0.5" />
                                                <div>
                                                    <p className="text-xs text-gray-500">Notes</p>
                                                    <p className="text-gray-300">{visitor.notes}</p>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* Face Data */}
                            <div className="glass-card p-6">
                                <div className="flex items-center justify-between mb-6">
                                    <div className="flex items-center gap-3">
                                        <div className="p-2 bg-purple-500/10 rounded-lg">
                                            <ImagePlus className="text-purple-400" size={24} />
                                        </div>
                                        <h2 className="text-xl font-bold">Face Data</h2>
                                        <span className="text-sm text-gray-500">({visitor.face_data?.length || 0} entries)</span>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2">
                                        {/* Visual angle selector replaces dropdown */}
                                        {/* S14: Batch Upload */}
                                        <input
                                            ref={batchInputRef}
                                            type="file"
                                            accept="image/*"
                                            multiple
                                            onChange={handleBatchUpload}
                                            className="hidden"
                                        />
                                        <button
                                            onClick={() => batchInputRef.current?.click()}
                                            disabled={batchUploading || faceLimitReached}
                                            className="bg-gray-800 hover:bg-gray-700 disabled:opacity-50 text-white px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                            title="Upload multiple face images at once"
                                        >
                                            {batchUploading ? (
                                                <><Loader size={16} className="animate-spin" /> Uploading...</>
                                            ) : (
                                                <><FolderUp size={16} /> Batch Upload</>
                                            )}
                                        </button>
                                        {/* Single upload */}
                                        <input
                                            ref={faceInputRef}
                                            type="file"
                                            accept="image/*"
                                            onChange={handleFaceUpload}
                                            className="hidden"
                                        />
                                        <button
                                            onClick={() => faceInputRef.current?.click()}
                                            disabled={uploadingFace || faceLimitReached}
                                            className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                        >
                                            {uploadingFace ? (
                                                <><Loader size={16} className="animate-spin" /> Processing...</>
                                            ) : (
                                                <><Upload size={16} /> Upload Face</>
                                            )}
                                        </button>
                                    </div>
                                </div>

                                {batchResults && (
                                    <div className="mb-4 p-3 bg-blue-500/10 border border-blue-500/20 rounded-lg text-sm text-blue-400 flex items-center gap-2">
                                        <CheckCircle size={16} />
                                        <span>Batch upload: {batchResults.processed} processed, {batchResults.failed} failed</span>
                                        {batchResults.failed > 0 && (
                                            <button
                                                onClick={() => batchInputRef.current?.click()}
                                                className="ml-auto text-xs px-2.5 py-1 rounded bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 font-medium transition-colors"
                                            >
                                                Retry failed
                                            </button>
                                        )}
                                    </div>
                                )}

                                {faceLimitReached && (
                                    <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-sm text-amber-300 flex items-center gap-2">
                                        <AlertCircle size={16} />
                                        Face data limit reached ({maxFaceEntries}). Delete an image to add more.
                                    </div>
                                )}

                                {/* Visual angle selector for uploads */}
                                <div className="mb-4">
                                    <p className="text-xs font-medium text-gray-500 mb-2">Select face angle for next upload:</p>
                                    <VisualAngleSelector value={selectedFaceAngle} onChange={setSelectedFaceAngle} />
                                </div>

                                <div className="mb-4 p-3 rounded-lg border border-white/5 bg-gray-900/40">
                                    <div className="flex flex-wrap items-center gap-2 text-xs">
                                        <span className="text-gray-500">Angle coverage:</span>
                                        {requiredAngles.map((option) => {
                                            const isPresent = availableAngles.has(option.value)
                                            return (
                                                <span
                                                    key={option.value}
                                                    className={`px-2 py-1 rounded ${isPresent
                                                            ? 'bg-green-500/10 text-green-300'
                                                            : 'bg-amber-500/10 text-amber-300'
                                                        }`}
                                                >
                                                    {option.label}
                                                </span>
                                            )
                                        })}
                                    </div>
                                    {missingAngles.length > 0 ? (
                                        <div className="mt-2">
                                            <p className="text-xs text-amber-300">
                                                Missing: {missingAngles.map((angle) => angle.label).join(', ')}
                                            </p>
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    setSelectedFaceAngle(missingAngles[0].value)
                                                    imageInputRef.current?.click()
                                                }}
                                                className="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 text-xs font-medium transition-colors"
                                            >
                                                <Upload size={12} /> Upload {missingAngles[0].label} angle
                                            </button>
                                        </div>
                                    ) : (
                                        <p className="mt-2 text-xs text-green-300">All required angles captured.</p>
                                    )}
                                </div>

                                {!visitor.face_data || visitor.face_data.length === 0 ? (
                                    <div className="text-center py-8 text-gray-500">
                                        <ImagePlus size={32} className="mx-auto mb-2 opacity-50" />
                                        <p>No face data registered for this visitor.</p>
                                        <p className="text-sm mt-1">Upload images or video below, or let the AI add face data automatically when this visitor is identified.</p>
                                    </div>
                                ) : (
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        {faceEntries.map((face: FaceData) => (
                                            <div
                                                key={face.id}
                                                className="bg-gray-900/50 rounded-lg p-4 border border-gray-800 hover:border-gray-700 transition-colors"
                                            >
                                                <div className="flex items-start justify-between mb-3">
                                                    <div className="flex items-center gap-2">
                                                        {face.is_primary && (
                                                            <Star size={14} className="text-yellow-400 fill-yellow-400" />
                                                        )}
                                                        <span className="text-sm font-medium">
                                                            {face.is_primary ? 'Primary' : 'Secondary'}
                                                        </span>
                                                    </div>
                                                    <div className="flex items-center gap-2">
                                                        {!face.is_primary && (
                                                            <button
                                                                onClick={() => handleSetPrimaryFace(face.id)}
                                                                disabled={primaryFaceUpdatingId === face.id}
                                                                className="px-2.5 py-1.5 text-xs font-medium rounded-lg bg-yellow-500/10 hover:bg-yellow-500/20 text-yellow-300 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                                                            >
                                                                {primaryFaceUpdatingId === face.id ? (
                                                                    <Loader size={12} className="animate-spin" />
                                                                ) : (
                                                                    <Star size={12} />
                                                                )}
                                                                {primaryFaceUpdatingId === face.id ? 'Updating' : 'Set Primary'}
                                                            </button>
                                                        )}
                                                        <button
                                                            onClick={() => handleDeleteFace(face.id)}
                                                            className="p-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded transition-colors"
                                                        >
                                                            <Trash2 size={12} />
                                                        </button>
                                                    </div>
                                                </div>

                                                {face.image_url && !brokenMediaUrls[face.image_url] && (
                                                    <div className="w-full h-32 bg-gray-800 rounded-lg mb-3 overflow-hidden">
                                                        <MediaImage
                                                            sources={[face.image_url]}
                                                            alt="Face"
                                                            className="w-full h-full object-cover"
                                                            onError={() => {
                                                                setBrokenMediaUrls((prev) => ({ ...prev, [face.image_url!]: true }))
                                                            }}
                                                        />
                                                    </div>
                                                )}

                                                <div className="space-y-1 text-xs text-gray-400">
                                                    <div className="flex justify-between">
                                                        <span>Quality Score</span>
                                                        <span className={`font-medium ${face.quality_score >= 0.7 ? 'text-green-400' : face.quality_score >= 0.4 ? 'text-yellow-400' : 'text-red-400'}`}>
                                                            {(face.quality_score * 100).toFixed(0)}%
                                                        </span>
                                                    </div>
                                                    <div className="flex justify-between">
                                                        <span>Angle</span>
                                                        <span>{formatFaceAngle(face.face_angle)}</span>
                                                    </div>
                                                    <div className="flex justify-between">
                                                        <span>Added</span>
                                                        <span>{new Date(face.created_at).toLocaleDateString()}</span>
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <div
                                id="media-enrollment"
                                ref={mediaEnrollmentRef}
                                className="glass-card p-6 scroll-mt-28"
                            >
                                <div className="flex items-center gap-3 mb-6">
                                    <div className="p-2 bg-cyan-500/10 rounded-lg">
                                        <Video className="text-cyan-400" size={24} />
                                    </div>
                                    <div>
                                        <h2 className="text-xl font-bold">Media Enrollment</h2>
                                        <p className="text-sm text-gray-500">
                                            Upload images, attach a video, or record from the camera to build this visitor&apos;s recognition profile.
                                        </p>
                                    </div>
                                </div>

                                {(primaryFace || enrolledFaceImages.length > 0 || enrolledVideoUrls.length > 0) && (
                                    <div className="mb-6 rounded-xl border border-white/10 bg-white/5 p-4 space-y-4">
                                        <div className="flex items-center justify-between gap-3">
                                            <div>
                                                <h3 className="text-sm font-semibold text-white">Current Enrolled Media</h3>
                                                <p className="text-xs text-gray-500">
                                                    Primary face, all face images, and uploaded videos already linked to this visitor.
                                                </p>
                                            </div>
                                        </div>

                                        {primaryFace?.image_url && !brokenMediaUrls[primaryFace.image_url] && (
                                            <div className="overflow-hidden rounded-xl border border-yellow-500/20 bg-black">
                                                <div className="flex items-center justify-between border-b border-white/10 bg-yellow-500/10 px-3 py-2">
                                                    <span className="text-xs font-semibold uppercase tracking-widest text-yellow-300">
                                                        Primary Face
                                                    </span>
                                                    <span className="text-xs text-yellow-200/80">
                                                        {formatFaceAngle(primaryFace.face_angle)}
                                                    </span>
                                                </div>
                                                <MediaImage
                                                    sources={[primaryFace.image_url]}
                                                    alt="Primary face"
                                                    className="h-52 w-full object-cover"
                                                    onError={() => {
                                                        setBrokenMediaUrls((prev) => ({ ...prev, [primaryFace.image_url!]: true }))
                                                    }}
                                                />
                                            </div>
                                        )}

                                        {enrolledFaceImages.length > 0 && (
                                            <div>
                                                <p className="mb-2 text-xs font-medium uppercase tracking-widest text-gray-500">
                                                    Face Images
                                                </p>
                                                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                                                    {enrolledFaceImages.map((face) => {
                                                        const mediaUrl = face.image_url ? getStaticMediaUrl(face.image_url) : null
                                                        if (!mediaUrl || (face.image_url && brokenMediaUrls[face.image_url])) {
                                                            return null
                                                        }
                                                        return (
                                                            <div key={face.id} className="overflow-hidden rounded-xl border border-white/10 bg-gray-900/60">
                                                                <MediaImage
                                                                    sources={[face.image_url]}
                                                                    alt={face.is_primary ? 'Primary face image' : 'Face image'}
                                                                    className="h-28 w-full object-cover"
                                                                    onError={() => {
                                                                        if (!face.image_url) return
                                                                        setBrokenMediaUrls((prev) => ({ ...prev, [face.image_url!]: true }))
                                                                    }}
                                                                />
                                                                <div className="flex items-center justify-between px-2 py-2 text-[11px]">
                                                                    <span className={face.is_primary ? 'font-semibold text-yellow-300' : 'text-gray-400'}>
                                                                        {face.is_primary ? 'Primary' : formatFaceAngle(face.face_angle)}
                                                                    </span>
                                                                    <span className="text-gray-500">
                                                                        {(face.quality_score * 100).toFixed(0)}%
                                                                    </span>
                                                                </div>
                                                            </div>
                                                        )
                                                    })}
                                                </div>
                                            </div>
                                        )}

                                        {enrolledVideoUrls.length > 0 && (
                                            <div>
                                                <p className="mb-2 text-xs font-medium uppercase tracking-widest text-gray-500">
                                                    Uploaded Videos
                                                </p>
                                                <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                                                    {enrolledVideoUrls.map((videoUrl: string) => {
                                                        const mediaUrl = getStaticMediaUrl(videoUrl)
                                                        if (!mediaUrl || brokenMediaUrls[videoUrl]) {
                                                            return null
                                                        }
                                                        return (
                                                            <div key={videoUrl} className="overflow-hidden rounded-xl border border-white/10 bg-gray-900/60">
                                                                <video
                                                                    src={mediaUrl}
                                                                    controls
                                                                    preload="metadata"
                                                                    className="h-40 w-full bg-black object-cover"
                                                                    onError={() => {
                                                                        setBrokenMediaUrls((prev) => ({ ...prev, [videoUrl]: true }))
                                                                    }}
                                                                />
                                                                <div className="px-3 py-2 text-xs text-gray-400">
                                                                    Uploaded enrollment video
                                                                </div>
                                                            </div>
                                                        )
                                                    })}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}

                                <input
                                    ref={imageInputRef}
                                    type="file"
                                    accept="image/*"
                                    multiple
                                    onChange={handleImageSelection}
                                    className="hidden"
                                />
                                <input
                                    ref={videoInputRef}
                                    type="file"
                                    accept="video/*"
                                    onChange={handleVideoSelection}
                                    className="hidden"
                                />

                                <div className="flex flex-wrap gap-2 mb-4">
                                    <button
                                        type="button"
                                        onClick={() => imageInputRef.current?.click()}
                                        className="bg-gray-800 hover:bg-gray-700 text-white px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        <Upload size={16} /> Add Images
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => videoInputRef.current?.click()}
                                        className="bg-gray-800 hover:bg-gray-700 text-white px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        <Video size={16} /> Add Video
                                    </button>
                                    <button
                                        type="button"
                                        onClick={cameraActive ? stopCamera : () => startCamera()}
                                        className="bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-300 border border-cyan-500/20 px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        <Camera size={16} />
                                        {cameraActive ? 'Close Camera' : 'Open Camera'}
                                    </button>
                                    <button
                                        type="button"
                                        onClick={startGuidedCapture}
                                        disabled={guidedActive || faceLimitReached}
                                        title="Step-by-step photo capture for each face angle"
                                        className="bg-brand-500/10 hover:bg-brand-500/20 disabled:opacity-50 text-brand-300 border border-brand-500/20 px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        <ScanFace size={16} /> Guided Capture
                                    </button>
                                    {(selectedImages.length > 0 || selectedVideo) && (
                                        <button
                                            type="button"
                                            onClick={() => {
                                                resetMediaSelection()
                                                setMessage(null)
                                            }}
                                            className="bg-gray-800 hover:bg-gray-700 text-white px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                        >
                                            <X size={16} /> Clear
                                        </button>
                                    )}
                                </div>

                                {cameraActive && (
                                    <div className="rounded-xl overflow-hidden border border-white/10 bg-black mb-4">
                                        <video
                                            ref={cameraVideoRef}
                                            autoPlay
                                            muted
                                            playsInline
                                            className="w-full aspect-video object-cover bg-black"
                                        />
                                        <div className="flex items-center justify-between gap-3 px-4 py-3 bg-black/70">
                                            <div className="flex items-center gap-2">
                                                {recording ? (
                                                    <span className="text-xs font-bold text-red-400 uppercase tracking-wider">
                                                        Recording {Math.floor(recordingTime / 60)}:{String(recordingTime % 60).padStart(2, '0')}
                                                    </span>
                                                ) : (
                                                    <span className="text-xs font-bold text-white/60 uppercase tracking-wider">
                                                        Camera Ready
                                                    </span>
                                                )}
                                            </div>
                                            <div className="flex gap-2">
                                                {/* Camera flip button for mobile */}
                                                {!recording && (
                                                    <button
                                                        type="button"
                                                        onClick={flipCamera}
                                                        title={cameraFacingMode === 'user' ? 'Switch to rear camera (photograph someone else)' : 'Switch to front camera (self-verification)'}
                                                        className="bg-white/10 hover:bg-white/20 text-white px-3 py-2 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5"
                                                    >
                                                        <FlipHorizontal size={14} />
                                                        {cameraFacingMode === 'user' ? 'Rear' : 'Front'}
                                                    </button>
                                                )}
                                                {!recording ? (
                                                    <button
                                                        type="button"
                                                        onClick={startRecording}
                                                        className="bg-red-600 hover:bg-red-700 text-white px-3 py-2 rounded-lg text-xs font-medium transition-colors flex items-center gap-2"
                                                    >
                                                        <div className="w-2.5 h-2.5 rounded-full bg-white" />
                                                        Start Recording
                                                    </button>
                                                ) : (
                                                    <button
                                                        type="button"
                                                        onClick={stopRecording}
                                                        className="bg-white hover:bg-gray-200 text-red-600 px-3 py-2 rounded-lg text-xs font-medium transition-colors flex items-center gap-2"
                                                    >
                                                        <StopCircle size={14} /> Stop Recording
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                )}

                                {guidedActive && (
                                    <div className="mb-4">
                                        <GuidedFaceCapture
                                            angles={guidedQueue}
                                            onCapture={handleGuidedCapture}
                                            onFinish={handleGuidedFinish}
                                            onClose={() => {
                                                setGuidedActive(false)
                                                fetchVisitor()
                                            }}
                                        />
                                    </div>
                                )}

                                {(selectedImages.length > 0 || selectedVideo) && (
                                    <div className="rounded-xl border border-white/10 bg-white/5 p-4 mb-4 space-y-2 text-sm">
                                        {/* Per-file upload progress */}
                                        {selectedImages.map((file) => {
                                            const state = uploadProgress[file.name] || 'pending'
                                            return (
                                                <div key={file.name} className="flex items-center gap-3">
                                                    {state === 'done' && <CheckCircle2 size={14} className="text-green-400 shrink-0" />}
                                                    {state === 'error' && <AlertCircle size={14} className="text-red-400 shrink-0" />}
                                                    {state === 'uploading' && <Loader size={14} className="text-brand-400 animate-spin shrink-0" />}
                                                    {state === 'pending' && <div className="w-3.5 h-3.5 rounded-full border border-white/20 shrink-0" />}
                                                    <span className={`truncate text-xs ${state === 'done' ? 'text-green-400' : state === 'error' ? 'text-red-400' : 'text-gray-400'}`}>
                                                        {file.name}
                                                    </span>
                                                    <span className="ml-auto text-xs text-gray-600 shrink-0">
                                                        {state === 'done' ? 'Enrolled' : state === 'error' ? 'Failed' : state === 'uploading' ? 'Processing…' : 'Ready'}
                                                    </span>
                                                </div>
                                            )
                                        })}
                                        {selectedVideo && (
                                            <div className="flex items-center gap-2 text-gray-300 pt-1 border-t border-white/5">
                                                <Video size={14} className="text-cyan-400" />
                                                <span className="text-gray-500 text-xs">Video:</span>
                                                <span className="text-xs truncate">{selectedVideo.name}</span>
                                            </div>
                                        )}
                                    </div>
                                )}

                                <div className="flex items-center justify-between gap-4">
                                    <p className="text-xs text-gray-500">
                                        New faces found in this media will be added to the visitor. Use the face cards above to mark the best one as primary.
                                    </p>
                                    <button
                                        onClick={handleEnrollMedia}
                                        disabled={uploadingMedia || (selectedImages.length === 0 && !selectedVideo)}
                                        className="bg-cyan-500 hover:bg-cyan-600 disabled:opacity-50 text-white px-4 py-2.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        {uploadingMedia ? (
                                            <><Loader size={16} className="animate-spin" /> Processing...</>
                                        ) : (
                                            <><Upload size={16} /> Enroll Media</>
                                        )}
                                    </button>
                                </div>
                            </div>

                            {/* S16: Recognition Settings */}
                            <div className="glass-card p-6">
                                <div className="flex items-center gap-3 mb-6">
                                    <div className="p-2 bg-yellow-500/10 rounded-lg">
                                        <Sliders className="text-yellow-400" size={24} />
                                    </div>
                                    <div>
                                        <h2 className="text-xl font-bold">Recognition Settings</h2>
                                        <p className="text-sm text-gray-500">Per-visitor accuracy tuning</p>
                                    </div>
                                </div>

                                <div className="space-y-6">
                                    {/* Custom Threshold */}
                                    <div>
                                        <div className="flex items-center justify-between mb-2">
                                            <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
                                                <Sliders size={14} />
                                                Custom Confidence Threshold
                                            </label>
                                            <label className="flex items-center gap-2 cursor-pointer">
                                                <span className="text-xs text-gray-500">{customThreshold !== null ? 'Custom' : 'Default'}</span>
                                                <input
                                                    type="checkbox"
                                                    checked={customThreshold !== null}
                                                    onChange={(e) => setCustomThreshold(e.target.checked ? 0.6 : null)}
                                                    className="w-4 h-4 accent-brand-500 rounded"
                                                />
                                            </label>
                                        </div>
                                        {customThreshold !== null ? (
                                            <>
                                                <input
                                                    type="range"
                                                    min="0.3"
                                                    max="0.95"
                                                    step="0.05"
                                                    value={customThreshold}
                                                    onChange={(e) => setCustomThreshold(parseFloat(e.target.value))}
                                                    className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-brand-500"
                                                />
                                                <div className="flex justify-between text-xs text-gray-500 mt-1">
                                                    <span>Permissive (30%)</span>
                                                    <span className="font-medium text-brand-400">{(customThreshold * 100).toFixed(0)}%</span>
                                                    <span>Strict (95%)</span>
                                                </div>
                                                <p className="text-xs text-gray-500 mt-2">
                                                    Override the global threshold for this specific visitor. Useful for visitors who are harder or easier to recognize.
                                                </p>
                                                <div className={`mt-2 text-xs px-3 py-2 rounded-lg ${
                                                    customThreshold < 0.5
                                                        ? 'bg-red-500/10 text-red-300'
                                                        : customThreshold < 0.7
                                                        ? 'bg-amber-500/10 text-amber-300'
                                                        : 'bg-green-500/10 text-green-300'
                                                }`}>
                                                    {customThreshold < 0.5
                                                        ? '⚠ Very permissive — may produce false positives. This visitor could be matched to other people.'
                                                        : customThreshold < 0.7
                                                        ? 'Balanced — good trade-off between recall and precision for most visitors.'
                                                        : '✓ Strict — only high-confidence matches accepted. May miss some detections if lighting varies.'}
                                                </div>
                                            </>
                                        ) : (
                                            <p className="text-sm text-gray-500">Using the organization default threshold.</p>
                                        )}
                                    </div>

                                    {/* Auto-Learn Toggle */}
                                    <div>
                                        <label className="flex items-center justify-between p-4 bg-gray-900/30 rounded-lg cursor-pointer hover:bg-gray-900/50 transition-colors">
                                            <div className="flex items-center gap-3">
                                                <Brain size={18} className="text-green-400" />
                                                <div>
                                                    <p className="font-medium text-gray-200">Continuous Learning</p>
                                                    <p className="text-sm text-gray-500">Automatically add high-confidence detections as new face data to improve future recognition.</p>
                                                </div>
                                            </div>
                                            <input
                                                type="checkbox"
                                                checked={autoLearn}
                                                onChange={(e) => setAutoLearn(e.target.checked)}
                                                className="w-5 h-5 accent-brand-500 rounded ml-4 shrink-0"
                                            />
                                        </label>
                                    </div>

                                    {/* Save Button */}
                                    <button
                                        onClick={handleSaveThreshold}
                                        disabled={savingThreshold}
                                        className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        <Save size={16} />
                                        {savingThreshold ? 'Saving...' : 'Save Recognition Settings'}
                                    </button>
                                </div>
                            </div>
                        </div>

                        {/* Sidebar Stats */}
                        <div className="space-y-6">
                            <div className="glass-card p-6">
                                <h3 className="font-bold mb-4 text-gray-300">Quick Stats</h3>
                                <div className="space-y-4">
                                    <div className="flex justify-between items-center">
                                        <span className="text-gray-400 flex items-center gap-2">
                                            <Eye size={16} /> Total Visits
                                        </span>
                                        <span className="font-semibold text-xl">{visitor.log_count}</span>
                                    </div>
                                    <div className="flex justify-between items-center">
                                        <span className="text-gray-400 flex items-center gap-2">
                                            <ImagePlus size={16} /> Face Data
                                        </span>
                                        <span className="font-semibold text-xl">{visitor.face_data?.length || 0}</span>
                                    </div>
                                    <div className="flex justify-between items-center">
                                        <span className="text-gray-400 flex items-center gap-2">
                                            <Clock size={16} /> First Seen
                                        </span>
                                        <span className="text-sm">{new Date(visitor.created_at).toLocaleDateString()}</span>
                                    </div>
                                    {visitor.updated_at && (
                                        <div className="flex justify-between items-center">
                                            <span className="text-gray-400 flex items-center gap-2">
                                                <Clock size={16} /> Last Updated
                                            </span>
                                            <span className="text-sm">{new Date(visitor.updated_at).toLocaleDateString()}</span>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Detection History Timeline */}
                            <div className="glass-card p-6">
                                <div className="flex items-center justify-between mb-4">
                                    <h3 className="font-bold text-gray-300 flex items-center gap-2">
                                        <History size={16} /> Detection History
                                    </h3>
                                    <Link
                                        href={`/logs?visitor_id=${visitorId}`}
                                        className="text-xs text-brand-400 hover:text-brand-300 transition-colors"
                                    >
                                        View all →
                                    </Link>
                                </div>

                                {loadingHistory ? (
                                    <div className="space-y-3">
                                        {[1, 2, 3].map(i => (
                                            <div key={i} className="animate-pulse h-12 bg-white/5 rounded-lg" />
                                        ))}
                                    </div>
                                ) : detectionHistory.length === 0 ? (
                                    <p className="text-sm text-gray-500 text-center py-4">No detections recorded yet.</p>
                                ) : (
                                    <div className="space-y-2">
                                        {detectionHistory.slice(0, 8).map(log => {
                                            const pct = Math.round(log.confidence * 100)
                                            return (
                                                <Link
                                                    key={log.id}
                                                    href={`/logs/${log.id}`}
                                                    className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-white/5 transition-colors group"
                                                >
                                                    <div className={`w-2 h-2 rounded-full shrink-0 ${log.status === 'identified' ? 'bg-green-400' : log.status === 'reviewed' ? 'bg-blue-400' : 'bg-yellow-400'}`} />
                                                    <div className="flex-1 min-w-0">
                                                        <p className="text-xs text-gray-300 font-medium truncate">
                                                            {new Date(log.timestamp).toLocaleDateString()} · {new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                                        </p>
                                                        <div className="flex items-center gap-2">
                                                            <span className={`text-xs ${log.status === 'identified' ? 'text-green-400' : 'text-gray-500'}`}>
                                                                {log.status}
                                                            </span>
                                                            {pct > 0 && <ConfidencePill confidence={log.confidence} />}
                                                        </div>
                                                    </div>
                                                    <ChevronRight size={12} className="text-gray-600 group-hover:text-gray-400 shrink-0" />
                                                </Link>
                                            )
                                        })}
                                    </div>
                                )}
                            </div>

                            <div className="glass-card p-6">
                                <h3 className="font-bold mb-4 text-gray-300">Actions</h3>
                                <div className="space-y-2">
                                    <Link
                                        href={`/logs?visitor_id=${visitorId}`}
                                        className="w-full bg-gray-800 hover:bg-gray-700 text-white px-4 py-3 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
                                    >
                                        <Eye size={16} /> View All Logs
                                    </Link>
                                </div>
                            </div>

                            {visitor.metadata && Object.keys(visitor.metadata).length > 0 && (
                                <div className="glass-card p-6">
                                    <h3 className="font-bold mb-4 text-gray-300">Metadata</h3>
                                    <div className="space-y-2">
                                        {Object.entries(visitor.metadata).map(([key, value]) => (
                                            <div key={key} className="flex justify-between text-sm">
                                                <span className="text-gray-400">{key}</span>
                                                <span className="text-gray-200 text-right max-w-[220px] break-words font-mono text-xs">
                                                    {typeof value === 'object' && value !== null
                                                        ? JSON.stringify(value)
                                                        : String(value)}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </motion.div>
            </main>
        </div>
    )
}

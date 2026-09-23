'use client'

import React, { useState, useRef, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Video, Upload, CheckCircle, AlertCircle, Loader, Clock, Users, UserCheck, Camera, StopCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { useRouter } from 'next/navigation'
import Navbar from '@/components/Navbar'
import { videoService, VideoProcessingJob } from '@/services/api'

export default function UploadPage() {
    const router = useRouter()
    const [file, setFile] = useState<File | null>(null)
    const [uploading, setUploading] = useState(false)
    const [result, setResult] = useState<{ success: boolean; message: string } | null>(null)
    const [dragActive, setDragActive] = useState(false)
    const inputRef = useRef<HTMLInputElement>(null)
    const [fileError, setFileError] = useState<string | null>(null)

    const MAX_FILE_SIZE = 500 * 1024 * 1024 // 500 MB
    const ALLOWED_TYPES = ['video/mp4', 'video/webm', 'video/quicktime', 'video/x-msvideo', 'video/x-matroska']
    const ALLOWED_EXTENSIONS = ['.mp4', '.webm', '.mov', '.avi', '.mkv']

    const validateFile = (f: File): string | null => {
        if (f.size > MAX_FILE_SIZE) return `File too large (${(f.size / 1024 / 1024).toFixed(0)} MB). Maximum is 500 MB.`
        const ext = '.' + f.name.split('.').pop()?.toLowerCase()
        if (!ALLOWED_TYPES.includes(f.type) && !ALLOWED_EXTENSIONS.includes(ext)) {
            return `Unsupported format (${ext}). Accepted: ${ALLOWED_EXTENSIONS.join(', ')}`
        }
        return null
    }

    // Camera Recording State
    const [isRecording, setIsRecording] = useState(false)
    const [isCameraActive, setIsCameraActive] = useState(false)
    const [recordedChunks, setRecordedChunks] = useState<Blob[]>([])
    const [stream, setStream] = useState<MediaStream | null>(null)
    const videoRef = useRef<HTMLVideoElement>(null)
    const mediaRecorderRef = useRef<MediaRecorder | null>(null)
    const [recordingTime, setRecordingTime] = useState(0)
    const timerRef = useRef<NodeJS.Timeout | null>(null)

    useEffect(() => {
        if (isCameraActive && stream && videoRef.current) {
            videoRef.current.srcObject = stream
        }
    }, [isCameraActive, stream])

    const startCamera = async () => {
        try {
            const mediaStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true })
            setStream(mediaStream)
            setIsCameraActive(true)
        } catch (err) {
            console.error("Error accessing camera:", err)
            setResult({ success: false, message: "Could not access camera. Please check permissions." })
        }
    }

    const stopCamera = () => {
        if (stream) {
            stream.getTracks().forEach(track => track.stop())
            setStream(null)
        }
        setIsCameraActive(false)
        setIsRecording(false)
        if (timerRef.current) clearInterval(timerRef.current)
        setRecordingTime(0)
    }

    const startRecording = () => {
        if (!stream) return
        
        const chunks: Blob[] = []
        setRecordedChunks([])
        
        const mediaRecorder = new MediaRecorder(stream)
        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) chunks.push(e.data)
        }
        
        mediaRecorder.onstop = () => {
            const blob = new Blob(chunks, { type: 'video/webm' })
            const recordedFile = new File([blob], `recorded-video-${Date.now()}.webm`, { type: 'video/webm' })
            setFile(recordedFile)
            setRecordedChunks(chunks)
        }

        mediaRecorderRef.current = mediaRecorder
        mediaRecorder.start()
        setIsRecording(true)
        
        setRecordingTime(0)
        timerRef.current = setInterval(() => {
            setRecordingTime(prev => prev + 1)
        }, 1000)
    }

    const stopRecording = () => {
        if (mediaRecorderRef.current && isRecording) {
            mediaRecorderRef.current.stop()
            setIsRecording(false)
            if (timerRef.current) clearInterval(timerRef.current)
        }
    }

    const formatTime = (seconds: number) => {
        const mins = Math.floor(seconds / 60)
        const secs = seconds % 60
        return `${mins}:${secs.toString().padStart(2, '0')}`
    }

    // Processing status
    const [jobId, setJobId] = useState<string | null>(null)
    const [job, setJob] = useState<VideoProcessingJob | null>(null)
    const [polling, setPolling] = useState(false)
    const pollStartRef = useRef<number>(0)
    const POLL_TIMEOUT_MS = 30 * 60 * 1000 // 30 minutes

    const pollStatus = useCallback(async (id: string) => {
        // Check timeout
        if (Date.now() - pollStartRef.current > POLL_TIMEOUT_MS) {
            setPolling(false)
            setResult({ success: false, message: 'Processing timed out after 30 minutes. The job may still be running — check back later.' })
            return
        }
        try {
            const res = await videoService.getProcessingStatus(id)
            setJob(res.data)
            if (res.data.status === 'completed' || res.data.status === 'error') {
                setPolling(false)
            }
        } catch (err: any) {
            console.error("Polling error:", err)
        }
    }, [])

    useEffect(() => {
        if (!jobId || !polling) return
        const interval = setInterval(() => pollStatus(jobId), 2000)
        return () => clearInterval(interval)
    }, [jobId, polling, pollStatus])

    const handleDrag = (e: React.DragEvent) => {
        e.preventDefault()
        e.stopPropagation()
        if (e.type === 'dragenter' || e.type === 'dragover') setDragActive(true)
        else if (e.type === 'dragleave') setDragActive(false)
    }

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault()
        e.stopPropagation()
        setDragActive(false)
        setFileError(null)
        if (e.dataTransfer.files?.[0]) {
            const err = validateFile(e.dataTransfer.files[0])
            if (err) { setFileError(err); return }
            setFile(e.dataTransfer.files[0])
            setResult(null)
            setJob(null)
            setJobId(null)
        }
    }

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setFileError(null)
        if (e.target.files?.[0]) {
            const err = validateFile(e.target.files[0])
            if (err) { setFileError(err); return }
            setFile(e.target.files[0])
            setResult(null)
            setJob(null)
            setJobId(null)
        }
    }

    const handleUpload = async () => {
        if (!file) return

        setUploading(true)
        setResult(null)
        setJob(null)
        setJobId(null)

        try {
            const res = await videoService.uploadVideo(file)
            const data = res.data
            setResult({
                success: true,
                message: `Video uploaded successfully! Processing has been triggered.`,
            })
            if (data.job_id) {
                setJobId(data.job_id)
                pollStartRef.current = Date.now()
                setPolling(true)
                pollStatus(data.job_id)
            }
            setFile(null)
        } catch (err: any) {
            if (err.response?.status === 401) {
                router.push('/login')
                return
            }
            setResult({
                success: false,
                message: err.response?.data?.detail || 'Upload failed. Please try again.',
            })
        } finally {
            setUploading(false)
        }
    }

    const formatSize = (bytes: number) => {
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    }

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'queued': return <Clock size={18} className="text-yellow-400" />
            case 'processing': return <Loader size={18} className="text-blue-400 animate-spin" />
            case 'completed': return <CheckCircle size={18} className="text-green-400" />
            case 'error': return <AlertCircle size={18} className="text-red-400" />
            default: return <Clock size={18} className="text-gray-400" />
        }
    }

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'queued': return 'border-yellow-500/20 bg-yellow-500/5'
            case 'processing': return 'border-blue-500/20 bg-blue-500/5'
            case 'completed': return 'border-green-500/20 bg-green-500/5'
            case 'error': return 'border-red-500/20 bg-red-500/5'
            default: return 'border-gray-500/20 bg-gray-500/5'
        }
    }

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-20 px-6 container mx-auto max-w-2xl">
                <div className="mb-8">
                    <div className="flex justify-between items-center mb-1">
                        <h1 className="text-3xl font-bold">Upload Video</h1>
                        <div className="flex gap-2">
                            {!isCameraActive ? (
                                <button
                                    onClick={startCamera}
                                    className="bg-brand-600/20 hover:bg-brand-600/30 text-brand-500 border border-brand-500/20 px-4 py-2 rounded-lg font-medium text-sm transition-all flex items-center gap-2"
                                >
                                    <Camera size={18} /> Open Camera
                                </button>
                            ) : (
                                <button
                                    onClick={stopCamera}
                                    className="bg-red-600/20 hover:bg-red-600/30 text-red-500 border border-red-500/20 px-4 py-2 rounded-lg font-medium text-sm transition-all flex items-center gap-2"
                                >
                                    <RefreshCw size={18} /> Switch to File
                                </button>
                            )}
                        </div>
                    </div>
                    <p className="text-gray-400">Upload a video file or record directly to detect and identify visitors using AI.</p>
                </div>

                <div className="bg-brand-500/5 border border-brand-500/10 p-4 rounded-2xl mb-6 flex gap-4 items-center">
                    <div className="w-10 h-10 rounded-full bg-brand-500/20 flex items-center justify-center text-brand-400 shrink-0">
                        <ShieldCheck size={20} />
                    </div>
                    <div>
                        <h4 className="text-sm font-bold text-white">Private Biometric Processing</h4>
                        <p className="text-[11px] text-gray-500">Video data is analyzed locally. Face embeddings are anonymized using high-entropy hashing before storage. No raw video is shared with external vendors.</p>
                    </div>
                </div>

                {/* Camera View */}
                <AnimatePresence>
                    {isCameraActive && (
                        <motion.div
                            initial={{ opacity: 0, scale: 0.95 }}
                            animate={{ opacity: 1, scale: 1 }}
                            exit={{ opacity: 0, scale: 0.95 }}
                            className="glass-card overflow-hidden mb-6 relative group"
                        >
                            <video
                                ref={videoRef}
                                autoPlay
                                muted
                                playsInline
                                className="w-full aspect-video object-cover bg-black"
                            />
                            
                            <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent flex flex-col justify-end p-6">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-3">
                                        {isRecording && (
                                            <div className="flex items-center gap-2 bg-red-600/80 px-3 py-1 rounded-full animate-pulse">
                                                <div className="w-2 h-2 bg-white rounded-full" />
                                                <span className="text-xs font-bold text-white uppercase tracking-wider">{formatTime(recordingTime)}</span>
                                            </div>
                                        )}
                                        {!isRecording && (
                                            <span className="text-xs font-bold text-white/60 uppercase tracking-wider">Camera Ready</span>
                                        )}
                                    </div>
                                    
                                    <div className="flex gap-4">
                                        {!isRecording ? (
                                            <button
                                                onClick={startRecording}
                                                className="w-14 h-14 bg-red-600 hover:bg-red-700 rounded-full flex items-center justify-center transition-all shadow-lg hover:scale-105 active:scale-95"
                                            >
                                                <div className="w-6 h-6 bg-white rounded-full" />
                                            </button>
                                        ) : (
                                            <button
                                                onClick={stopRecording}
                                                className="w-14 h-14 bg-white hover:bg-gray-200 rounded-full flex items-center justify-center transition-all shadow-lg hover:scale-105 active:scale-95"
                                            >
                                                <StopCircle className="text-red-600" size={32} />
                                            </button>
                                        )}
                                    </div>
                                    <div className="w-24" /> {/* Spacer */}
                                </div>
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>

                {/* Drop Zone */}
                {!isCameraActive && (
                    <div
                        onDragEnter={handleDrag}
                        onDragLeave={handleDrag}
                        onDragOver={handleDrag}
                        onDrop={handleDrop}
                        onClick={() => inputRef.current?.click()}
                        className={`glass-card p-12 border-dashed border-2 flex flex-col items-center justify-center text-center cursor-pointer transition-all ${
                            dragActive ? 'border-brand-500 bg-brand-500/5' : 'border-white/20 hover:border-brand-500/50'
                        }`}
                    >
                        <input
                            ref={inputRef}
                            type="file"
                            accept="video/*"
                            onChange={handleFileChange}
                            className="hidden"
                        />
                        <motion.div
                            animate={{ scale: dragActive ? 1.1 : 1 }}
                            className="w-20 h-20 bg-brand-500/10 rounded-full flex items-center justify-center mb-6"
                        >
                            <Upload className="text-brand-500" size={32} />
                        </motion.div>
                        <h3 className="text-lg font-bold mb-2">
                            {dragActive ? 'Drop your video here' : 'Drag & drop or click to select'}
                        </h3>
                        <p className="text-sm text-gray-400">Supports MP4, AVI, MOV, MKV formats · Max 500 MB</p>
                        {fileError && (
                            <p className="text-sm text-red-400 mt-2 flex items-center gap-1.5">
                                <AlertCircle size={14} /> {fileError}
                            </p>
                        )}
                    </div>
                )}

                {/* Selected File Info */}
                {file && (
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="glass-card p-5 mt-4"
                    >
                        <div className="flex items-center justify-between mb-4">
                            <div className="flex items-center gap-3">
                                <Video size={20} className="text-brand-500" />
                                <div>
                                    <p className="font-medium text-sm">{file.name}</p>
                                    <p className="text-xs text-gray-400">{formatSize(file.size)}</p>
                                </div>
                            </div>
                            <button
                                onClick={handleUpload}
                                disabled={uploading}
                                className="bg-brand-600 hover:bg-brand-700 text-white px-6 py-2.5 rounded-xl font-bold text-sm transition-all flex items-center gap-2 disabled:opacity-50 shadow-lg shadow-brand-600/20"
                            >
                                {uploading ? (
                                    <>
                                        <Loader size={16} className="animate-spin" /> Uploading...
                                    </>
                                ) : (
                                    <>
                                        <Upload size={16} /> Start Analysis
                                    </>
                                )}
                            </button>
                        </div>
                        {uploading && (
                            <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                                <motion.div 
                                    className="h-full bg-brand-500"
                                    initial={{ width: '0%' }}
                                    animate={{ width: '90%' }}
                                    transition={{ duration: 15, ease: 'linear' }}
                                />
                            </div>
                        )}
                    </motion.div>
                )}

                {/* Result */}
                {result && (
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className={`mt-4 p-4 rounded-lg flex items-start gap-3 ${
                            result.success
                                ? 'bg-green-500/10 border border-green-500/20'
                                : 'bg-red-500/10 border border-red-500/20'
                        }`}
                    >
                        {result.success ? (
                            <CheckCircle size={20} className="text-green-400 shrink-0 mt-0.5" />
                        ) : (
                            <AlertCircle size={20} className="text-red-400 shrink-0 mt-0.5" />
                        )}
                        <p className={`text-sm ${result.success ? 'text-green-400' : 'text-red-400'}`}>
                            {result.message}
                        </p>
                    </motion.div>
                )}

                {/* Processing Status */}
                {job && (
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className={`mt-4 p-5 rounded-lg border ${getStatusColor(job.status)}`}
                    >
                        <div className="flex items-center gap-3 mb-3">
                            {getStatusIcon(job.status)}
                            <h3 className="font-bold text-sm capitalize">Processing Status: {job.status}</h3>
                        </div>
                        {job.message && (
                            <p className="text-sm text-gray-300 mb-3">{job.message}</p>
                        )}
                        {(job.status === 'completed') && (
                            <div className="space-y-3">
                                <div className="flex gap-6 text-sm">
                                    <div className="flex items-center gap-2 text-gray-300">
                                        <Users size={16} className="text-blue-400" />
                                        <span>People Detected: <strong>{job.people_detected}</strong></span>
                                    </div>
                                    <div className="flex items-center gap-2 text-gray-300">
                                        <UserCheck size={16} className="text-green-400" />
                                        <span>Identified: <strong>{job.people_identified}</strong></span>
                                    </div>
                                </div>
                                {/* Quality signal */}
                                {job.people_detected > 0 && (
                                    <div className={`text-xs px-3 py-2 rounded-lg ${
                                        (job.people_identified / job.people_detected) >= 0.8
                                            ? 'bg-green-500/10 text-green-300'
                                            : (job.people_identified / job.people_detected) >= 0.4
                                            ? 'bg-yellow-500/10 text-yellow-300'
                                            : 'bg-red-500/10 text-red-300'
                                    }`}>
                                        {(job.people_identified / job.people_detected) >= 0.8
                                            ? `✓ High quality — ${Math.round((job.people_identified / job.people_detected) * 100)}% of detected people were identified`
                                            : (job.people_identified / job.people_detected) >= 0.4
                                            ? `⚠ Moderate quality — ${Math.round((job.people_identified / job.people_detected) * 100)}% identified. Consider enrolling more visitors.`
                                            : `Low identification rate (${Math.round((job.people_identified / job.people_detected) * 100)}%). Enroll more visitor face data for better results.`}
                                    </div>
                                )}
                            </div>
                        )}
                        {polling && (
                            <div className="mt-4 space-y-2">
                                <div className="flex items-center justify-between text-[10px] font-black uppercase text-gray-500 tracking-widest">
                                    <span>AI Pipelines Active</span>
                                    <span>Syncing...</span>
                                </div>
                                <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                                    <motion.div 
                                        className="h-full bg-brand-400"
                                        animate={{ 
                                            x: [-100, 400],
                                            opacity: [0.3, 1, 0.3]
                                        }}
                                        transition={{ 
                                            repeat: Infinity, 
                                            duration: 2,
                                            ease: "linear"
                                        }}
                                        style={{ width: '40%' }}
                                    />
                                </div>
                                <p className="text-[10px] text-gray-500 text-center font-bold uppercase tracking-wider">
                                    Analyzing biometric metadata and cross-referencing subject shards
                                </p>
                            </div>
                        )}
                    </motion.div>
                )}

                {/* How it works */}
                <div className="glass-card p-6 mt-8">
                    <h3 className="font-bold mb-4">How it works</h3>
                    <div className="space-y-3 text-sm text-gray-400">
                        <div className="flex gap-3">
                            <span className="w-6 h-6 bg-brand-500/20 text-brand-500 rounded-full flex items-center justify-center text-xs font-bold shrink-0">1</span>
                            <p>Upload a video file from your camera or surveillance system</p>
                        </div>
                        <div className="flex gap-3">
                            <span className="w-6 h-6 bg-brand-500/20 text-brand-500 rounded-full flex items-center justify-center text-xs font-bold shrink-0">2</span>
                            <p>AI detects and tracks all people in the video using YOLOv8</p>
                        </div>
                        <div className="flex gap-3">
                            <span className="w-6 h-6 bg-brand-500/20 text-brand-500 rounded-full flex items-center justify-center text-xs font-bold shrink-0">3</span>
                            <p>Face embeddings are extracted using ArcFace and matched against known visitors</p>
                        </div>
                        <div className="flex gap-3">
                            <span className="w-6 h-6 bg-brand-500/20 text-brand-500 rounded-full flex items-center justify-center text-xs font-bold shrink-0">4</span>
                            <p>Results appear in the Detection Logs for review and assignment</p>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    )
}

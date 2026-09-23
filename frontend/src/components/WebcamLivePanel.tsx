'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { AlertCircle, Camera, Loader, Play, RefreshCw, StopCircle, UserCheck, UserX } from 'lucide-react'
import { cameraSessionService } from '@/services/api'
import type { CameraSession, DetectionResult, PersonBox } from '@/services/api'

type NormalizedBBox = {
    x1: number
    y1: number
    x2: number
    y2: number
}

type VideoLayout = {
    sourceWidth: number
    sourceHeight: number
    containerWidth: number
    containerHeight: number
}

// Session creation currently takes ~35s against the live backend/database.
// Keep this above the observed latency so the UI does not fail early.
const SESSION_START_TIMEOUT_MS = 60000
// Frame analysis is heavier than the old 15s budget against the live AI service.
const FRAME_PROCESS_TIMEOUT_MS = 45000
const CAMERA_ACCESS_TIMEOUT_MS = 15000

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
    let timeoutId: ReturnType<typeof setTimeout> | null = null
    const timeout = new Promise<never>((_, reject) => {
        timeoutId = setTimeout(() => reject(new Error(message)), timeoutMs)
    })

    try {
        return await Promise.race([promise, timeout])
    } finally {
        if (timeoutId) clearTimeout(timeoutId)
    }
}

function isLocalSecureHost(hostname: string) {
    return hostname === 'localhost' || hostname === '127.0.0.1'
}

function describeCameraAccessError(error: unknown): string {
    const mediaError = error as DOMException & { message?: string }
    const name = mediaError?.name || ''

    if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
        return 'Camera access was blocked. Allow camera permission for this site, then retry in Chrome, Edge, or Firefox.'
    }

    if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
        return 'No camera was found on this machine. Connect a webcam and try again.'
    }

    if (name === 'NotReadableError' || name === 'TrackStartError') {
        return 'The camera is already in use by another application. Close the other app and try again.'
    }

    if (name === 'OverconstrainedError' || name === 'ConstraintNotSatisfiedError') {
        return 'This browser could not start the requested camera stream. Try another camera or browser.'
    }

    if (name === 'SecurityError') {
        return 'Camera access is blocked by the current browser security context. Open SentinelCV on HTTPS or localhost and try again.'
    }

    if (mediaError?.message) {
        return mediaError.message
    }

    return 'Could not access the webcam. Open this page in a regular browser window, allow camera permission, and try again.'
}

function toNumber(value: unknown): number | null {
    const num = Number(value)
    return Number.isFinite(num) ? num : null
}

function normalizeBBox(rawBBox: Record<string, unknown> | null | undefined): NormalizedBBox | null {
    if (!rawBBox) return null

    const x1 = toNumber(rawBBox.x1)
    const y1 = toNumber(rawBBox.y1)
    const x2 = toNumber(rawBBox.x2)
    const y2 = toNumber(rawBBox.y2)
    if (x1 !== null && y1 !== null && x2 !== null && y2 !== null) {
        return { x1, y1, x2, y2 }
    }

    const x = toNumber(rawBBox.x)
    const y = toNumber(rawBBox.y)
    const w = toNumber(rawBBox.w)
    const h = toNumber(rawBBox.h)
    if (x !== null && y !== null && w !== null && h !== null) {
        return { x1: x, y1: y, x2: x + w, y2: y + h }
    }

    return null
}

// Project a source-resolution bbox onto the rendered (object-contain) video.
// Returns pixel left/top/width/height within the container, or null when the
// layout isn't ready or the box is degenerate.
function projectBox(bbox: NormalizedBBox, layout: VideoLayout) {
    if (
        layout.sourceWidth <= 0 ||
        layout.sourceHeight <= 0 ||
        layout.containerWidth <= 0 ||
        layout.containerHeight <= 0
    ) {
        return null
    }

    const scale = Math.min(
        layout.containerWidth / layout.sourceWidth,
        layout.containerHeight / layout.sourceHeight,
    )
    const renderedWidth = layout.sourceWidth * scale
    const renderedHeight = layout.sourceHeight * scale
    const offsetX = (layout.containerWidth - renderedWidth) / 2
    const offsetY = (layout.containerHeight - renderedHeight) / 2

    const x1 = Math.max(0, Math.min(layout.sourceWidth, bbox.x1))
    const y1 = Math.max(0, Math.min(layout.sourceHeight, bbox.y1))
    const x2 = Math.max(0, Math.min(layout.sourceWidth, bbox.x2))
    const y2 = Math.max(0, Math.min(layout.sourceHeight, bbox.y2))
    if (x2 <= x1 || y2 <= y1) return null

    return {
        left: offsetX + (x1 / layout.sourceWidth) * renderedWidth,
        top: offsetY + (y1 / layout.sourceHeight) * renderedHeight,
        width: ((x2 - x1) / layout.sourceWidth) * renderedWidth,
        height: ((y2 - y1) / layout.sourceHeight) * renderedHeight,
    }
}

function getDetectionLabel(detection: DetectionResult) {
    if (detection.identified) {
        const name = detection.visitor_name || 'Identified'
        if (detection.visitor_id) {
            return `${name} | ID: ${detection.visitor_id}`
        }
        return name
    }
    return 'Unidentified subject'
}

export default function WebcamLivePanel() {
    const videoContainerRef = useRef<HTMLDivElement>(null)
    const videoRef = useRef<HTMLVideoElement>(null)
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const streamRef = useRef<MediaStream | null>(null)
    const sessionIdRef = useRef<string | null>(null)
    const intervalRef = useRef<number | null>(null)
    const captureLockRef = useRef(false)

    const [stream, setStream] = useState<MediaStream | null>(null)
    const [active, setActive] = useState(false)
    const [starting, setStarting] = useState(false)
    const [stopping, setStopping] = useState(false)
    const [status, setStatus] = useState('Idle')
    const [error, setError] = useState<string | null>(null)
    const [session, setSession] = useState<CameraSession | null>(null)
    const [frameCount, setFrameCount] = useState(0)
    const [lastCaptureAt, setLastCaptureAt] = useState<string | null>(null)
    const [processingMs, setProcessingMs] = useState<number | null>(null)
    const [aiMs, setAiMs] = useState<number | null>(null)
    const [identifyMs, setIdentifyMs] = useState<number | null>(null)
    const [detections, setDetections] = useState<DetectionResult[]>([])
    const [persons, setPersons] = useState<PersonBox[]>([])
    const [supported, setSupported] = useState(true)
    const [videoLayout, setVideoLayout] = useState<VideoLayout>({
        sourceWidth: 0,
        sourceHeight: 0,
        containerWidth: 0,
        containerHeight: 0,
    })

    const refreshVideoLayout = useCallback(() => {
        const video = videoRef.current
        const container = videoContainerRef.current
        if (!video || !container) return

        if (!video.videoWidth || !video.videoHeight) return

        const rect = container.getBoundingClientRect()
        if (!rect.width || !rect.height) return

        setVideoLayout((previous) => {
            const next: VideoLayout = {
                sourceWidth: video.videoWidth,
                sourceHeight: video.videoHeight,
                containerWidth: rect.width,
                containerHeight: rect.height,
            }

            if (
                previous.sourceWidth === next.sourceWidth &&
                previous.sourceHeight === next.sourceHeight &&
                previous.containerWidth === next.containerWidth &&
                previous.containerHeight === next.containerHeight
            ) {
                return previous
            }
            return next
        })
    }, [])

    const stopWebcam = useCallback(async () => {
        setStopping(true)
        try {
            if (intervalRef.current) {
                clearInterval(intervalRef.current)
                intervalRef.current = null
            }
            if (sessionIdRef.current) {
                await cameraSessionService.endSession(sessionIdRef.current)
            }
        } catch {
            // Session shutdown is best-effort.
        }

        if (streamRef.current) {
            streamRef.current.getTracks().forEach((track) => track.stop())
            streamRef.current = null
        }

        if (videoRef.current) {
            videoRef.current.srcObject = null
        }

        sessionIdRef.current = null
        setStream(null)
        setActive(false)
        setSession(null)
        setDetections([])
        setPersons([])
        setFrameCount(0)
        setLastCaptureAt(null)
        setProcessingMs(null)
        setStatus('Stopped')
        setError(null)
        setVideoLayout({ sourceWidth: 0, sourceHeight: 0, containerWidth: 0, containerHeight: 0 })
        setStopping(false)
    }, [])

    const captureFrame = useCallback(async () => {
        if (!active || captureLockRef.current || !sessionIdRef.current) return
        if (!videoRef.current || !canvasRef.current) return
        if (videoRef.current.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return
        if (!videoRef.current.videoWidth || !videoRef.current.videoHeight) return

        const context = canvasRef.current.getContext('2d')
        if (!context) return

        captureLockRef.current = true
        try {
            canvasRef.current.width = videoRef.current.videoWidth
            canvasRef.current.height = videoRef.current.videoHeight
            context.drawImage(videoRef.current, 0, 0, canvasRef.current.width, canvasRef.current.height)

            const frameData = canvasRef.current.toDataURL('image/jpeg', 0.85)
            const res = await withTimeout(
                cameraSessionService.processFrame(sessionIdRef.current, frameData),
                FRAME_PROCESS_TIMEOUT_MS,
                'Webcam analysis timed out. Please try again.',
            )
            setDetections(res.data.detections || [])
            setPersons(res.data.persons || [])
            setFrameCount((prev) => prev + 1)
            setProcessingMs(res.data.processing_time_ms)
            setAiMs(res.data.ai_processing_time_ms ?? res.data.ai_roundtrip_time_ms ?? null)
            setIdentifyMs(res.data.average_identification_time_ms ?? res.data.identification_time_ms ?? null)
            setLastCaptureAt(new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' }))
            setStatus(res.data.detections?.length ? 'Faces detected' : 'No faces detected')
            setError(null)
            refreshVideoLayout()
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Webcam analysis failed.')
        } finally {
            captureLockRef.current = false
        }
    }, [active, refreshVideoLayout])

    const startWebcam = async () => {
        if (starting || active) return
        if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
            setSupported(false)
            setError('This browser does not support webcam access.')
            return
        }

        if (
            typeof window !== 'undefined' &&
            !window.isSecureContext &&
            !isLocalSecureHost(window.location.hostname)
        ) {
            setError('Camera access requires HTTPS or localhost. Open SentinelCV from a secure browser origin and try again.')
            return
        }

        setStarting(true)
        setError(null)
        setStatus('Requesting camera access...')
        setDetections([])
        setPersons([])
        setFrameCount(0)
        setProcessingMs(null)
        setAiMs(null)
        setIdentifyMs(null)
        setLastCaptureAt(null)

        let mediaStream: MediaStream
        try {
            mediaStream = await withTimeout(
                navigator.mediaDevices.getUserMedia({ video: true, audio: false }),
                CAMERA_ACCESS_TIMEOUT_MS,
                'Camera permission was not granted in time. Please allow camera access and try again.',
            )
        } catch (err: any) {
            console.error('Webcam access failed:', err)
            setStream(null)
            setActive(false)
            sessionIdRef.current = null
            setStatus('Idle')
            setError(describeCameraAccessError(err))
            setStarting(false)
            return
        }

        streamRef.current = mediaStream
        setStream(mediaStream)
        setActive(true)
        setStatus('Preview live; starting analysis...')

        try {
            const sessionRes = await withTimeout(
                cameraSessionService.startSession({
                    settings: {
                        source: 'browser_webcam',
                        auto_capture: true,
                        capture_interval_ms: 2500,
                    },
                }),
                SESSION_START_TIMEOUT_MS,
                'Webcam analysis session is taking longer than expected. Please retry.',
            )

            sessionIdRef.current = sessionRes.data.id
            setSession(sessionRes.data)
            setStatus('Live')
            setError(null)
        } catch (err: any) {
            const timeoutMessage = 'Webcam analysis session is taking longer than expected. Please retry.'
            if (err?.message !== timeoutMessage) {
                console.error('Webcam analysis session failed:', err)
            }
            sessionIdRef.current = null
            setSession(null)
            setStatus('Preview live; analysis unavailable')
            setError(err?.message === timeoutMessage ? err.message : err.response?.data?.detail || 'Webcam analysis session failed.')
        } finally {
            setStarting(false)
        }
    }

    useEffect(() => {
        if (active && stream && videoRef.current) {
            videoRef.current.srcObject = stream
            window.requestAnimationFrame(() => refreshVideoLayout())
        }
    }, [active, stream, refreshVideoLayout])

    useEffect(() => {
        if (!active) return

        const tick = () => {
            void captureFrame()
        }

        const startTimer = window.setTimeout(tick, 1200)
        intervalRef.current = window.setInterval(tick, 2500)

        return () => {
            window.clearTimeout(startTimer)
            if (intervalRef.current) {
                clearInterval(intervalRef.current)
                intervalRef.current = null
            }
        }
    }, [active, captureFrame])

    useEffect(() => {
        return () => {
            void stopWebcam()
        }
    }, [stopWebcam])

    useEffect(() => {
        if (!active) return

        const container = videoContainerRef.current
        if (!container) return

        const onResize = () => refreshVideoLayout()

        window.addEventListener('resize', onResize)

        let observer: ResizeObserver | null = null
        if (typeof ResizeObserver !== 'undefined') {
            observer = new ResizeObserver(onResize)
            observer.observe(container)
        }

        return () => {
            window.removeEventListener('resize', onResize)
            observer?.disconnect()
        }
    }, [active, refreshVideoLayout])

    const identifiedCount = detections.filter((item) => item.identified).length

    // White boxes: a person/body was detected (YOLO). Drawn behind face boxes.
    const personOverlays = persons
        .map((person, index) => {
            const bbox = normalizeBBox(person.bbox as unknown as Record<string, unknown>)
            if (!bbox) return null
            const projected = projectBox(bbox, videoLayout)
            if (!projected) return null
            return { key: `person-${index}`, ...projected }
        })
        .filter((item): item is {
            key: string
            left: number
            top: number
            width: number
            height: number
        } => Boolean(item))

    // Face boxes: green = face found, red = matched to a known visitor.
    const overlays = detections
        .map((detection, index) => {
            const bbox = normalizeBBox(detection.bbox as Record<string, unknown>)
            if (!bbox) return null
            const projected = projectBox(bbox, videoLayout)
            if (!projected) return null
            return {
                key: `${detection.visitor_id || 'unknown'}-${index}`,
                ...projected,
                detection,
            }
        })
        .filter((item): item is {
            key: string
            left: number
            top: number
            width: number
            height: number
            detection: DetectionResult
        } => Boolean(item))

    return (
        <section className="glass-card p-6 space-y-5">
            <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-2xl bg-brand-500/10 text-brand-400">
                        <Camera size={18} />
                    </div>
                    <div>
                        <h2 className="text-xl font-black tracking-tight">Webcam Monitor</h2>
                        <p className="text-sm text-gray-500">Browser camera preview with live frame analysis.</p>
                    </div>
                </div>
                {!active ? (
                    <button
                        onClick={startWebcam}
                        disabled={starting}
                        className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-bold text-white hover:bg-brand-500 disabled:opacity-60 transition-colors"
                    >
                        {starting ? <Loader size={16} className="animate-spin" /> : <Play size={16} />}
                        {starting ? 'Starting...' : 'Open webcam'}
                    </button>
                ) : (
                    <button
                        onClick={() => void stopWebcam()}
                        disabled={stopping}
                        className="inline-flex items-center gap-2 rounded-xl bg-red-500/10 px-4 py-2.5 text-sm font-bold text-red-300 hover:bg-red-500/20 disabled:opacity-60 transition-colors border border-red-500/20"
                    >
                        {stopping ? <Loader size={16} className="animate-spin" /> : <StopCircle size={16} />}
                        {stopping ? 'Stopping...' : 'Stop webcam'}
                    </button>
                )}
            </div>

            {error && (
                <div className="rounded-2xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300 flex items-start gap-3">
                    <AlertCircle size={16} className="mt-0.5 shrink-0" />
                    <span>{error}</span>
                </div>
            )}

            {!supported && (
                <div className="rounded-2xl border border-yellow-500/20 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-300">
                    Your browser does not support webcam access.
                </div>
            )}

            <div ref={videoContainerRef} className="relative overflow-hidden rounded-2xl border border-white/10 bg-black">
                <video
                    ref={videoRef}
                    autoPlay
                    muted
                    playsInline
                    className="w-full aspect-video object-contain bg-black"
                    onLoadedMetadata={refreshVideoLayout}
                    onPlay={refreshVideoLayout}
                />
                {active && personOverlays.map((overlay) => (
                    <div
                        key={overlay.key}
                        className="absolute pointer-events-none border-2 border-white/80 rounded-md shadow-[0_0_0_1px_rgba(0,0,0,0.45)]"
                        style={{
                            left: `${overlay.left}px`,
                            top: `${overlay.top}px`,
                            width: `${overlay.width}px`,
                            height: `${overlay.height}px`,
                        }}
                    >
                        <div className="absolute top-0 left-0 rounded-br-md bg-white/85 px-2 py-1 text-[10px] font-bold tracking-[0.08em] text-black">
                            Human
                        </div>
                    </div>
                ))}
                {active && overlays.map((overlay) => {
                    const identified = overlay.detection.identified
                    const label = identified ? getDetectionLabel(overlay.detection) : 'Face detected'

                    return (
                        <div
                            key={overlay.key}
                            className={`absolute pointer-events-none border-2 ${identified ? 'border-red-400' : 'border-green-400'} rounded-md shadow-[0_0_0_1px_rgba(0,0,0,0.35)]`}
                            style={{
                                left: `${overlay.left}px`,
                                top: `${overlay.top}px`,
                                width: `${overlay.width}px`,
                                height: `${overlay.height}px`,
                            }}
                        >
                            <div
                                className={`absolute top-0 left-0 max-w-[22rem] truncate rounded-br-md px-2 py-1 text-[10px] font-bold tracking-[0.08em] text-white ${identified ? 'bg-red-500/90' : 'bg-green-500/90'}`}
                                title={label}
                            >
                                {label}
                            </div>
                        </div>
                    )
                })}
                {!active && (
                    <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-gray-950 to-black">
                        <div className="text-center px-6">
                            <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center mx-auto mb-4">
                                <Camera size={26} className="text-gray-600" />
                            </div>
                            <h3 className="font-bold text-white mb-2">Webcam preview is off</h3>
                            <p className="text-sm text-gray-500 max-w-xs">
                                Open the webcam to see your browser camera here and run live face analysis.
                            </p>
                        </div>
                    </div>
                )}
                <div className="absolute top-3 left-3 flex flex-wrap items-center gap-2">
                    <span className={`text-[10px] font-bold uppercase tracking-[0.2em] px-2 py-1 rounded-full border ${
                        active ? 'bg-green-500/15 text-green-300 border-green-500/20' : 'bg-white/10 text-gray-300 border-white/10'
                    }`}>
                        {active ? 'Live' : 'Idle'}
                    </span>
                    <span className="text-[10px] font-medium text-white/70 bg-black/40 px-2 py-1 rounded-full">
                        {status}
                    </span>
                </div>
                {active && (
                    <div className="absolute top-3 right-3 flex flex-col gap-1 rounded-lg bg-black/55 px-2.5 py-2 backdrop-blur-sm border border-white/10">
                        <span className="flex items-center gap-1.5 text-[10px] font-semibold text-white/80">
                            <span className="inline-block h-2.5 w-2.5 rounded-sm border-2 border-white/80" />
                            Human
                        </span>
                        <span className="flex items-center gap-1.5 text-[10px] font-semibold text-white/80">
                            <span className="inline-block h-2.5 w-2.5 rounded-sm border-2 border-green-400" />
                            Face detected
                        </span>
                        <span className="flex items-center gap-1.5 text-[10px] font-semibold text-white/80">
                            <span className="inline-block h-2.5 w-2.5 rounded-sm border-2 border-red-400" />
                            Known visitor
                        </span>
                    </div>
                )}
                <div className="absolute bottom-3 left-3 right-3 flex flex-col gap-3">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                        <div className="rounded-xl bg-black/55 border border-white/10 px-3 py-2 backdrop-blur-sm">
                            <p className="text-[10px] uppercase tracking-[0.2em] text-white/50">Session</p>
                            <p className="text-sm font-semibold text-white truncate">{session?.id ? session.id.slice(0, 8).toUpperCase() : 'None'}</p>
                        </div>
                        <div className="rounded-xl bg-black/55 border border-white/10 px-3 py-2 backdrop-blur-sm">
                            <p className="text-[10px] uppercase tracking-[0.2em] text-white/50">Frames</p>
                            <p className="text-sm font-semibold text-white tabular-nums">{frameCount}</p>
                        </div>
                        <div className="rounded-xl bg-black/55 border border-white/10 px-3 py-2 backdrop-blur-sm">
                            <p className="text-[10px] uppercase tracking-[0.2em] text-white/50">Faces</p>
                            <p className="text-sm font-semibold text-white tabular-nums">{detections.length}</p>
                        </div>
                        <div className="rounded-xl bg-black/55 border border-white/10 px-3 py-2 backdrop-blur-sm">
                            <p className="text-[10px] uppercase tracking-[0.2em] text-white/50">Processing</p>
                            <p className="text-sm font-semibold text-white tabular-nums">{processingMs ? `${processingMs.toFixed(0)} ms` : '...'}</p>
                        </div>
                        <div className="rounded-xl bg-black/55 border border-white/10 px-3 py-2 backdrop-blur-sm">
                            <p className="text-[10px] uppercase tracking-[0.2em] text-white/50">AI</p>
                            <p className="text-sm font-semibold text-white tabular-nums">{aiMs != null ? `${aiMs.toFixed(0)} ms` : '...'}</p>
                        </div>
                        <div className="rounded-xl bg-black/55 border border-white/10 px-3 py-2 backdrop-blur-sm">
                            <p className="text-[10px] uppercase tracking-[0.2em] text-white/50">Identify</p>
                            <p className="text-sm font-semibold text-white tabular-nums">{identifyMs != null ? `${identifyMs.toFixed(0)} ms` : '...'}</p>
                        </div>
                    </div>
                </div>
            </div>

            <canvas ref={canvasRef} className="hidden" />

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                    <p className="text-xs uppercase tracking-[0.25em] text-gray-500 mb-2">Last capture</p>
                    <p className="text-sm font-semibold text-white">{lastCaptureAt || 'Waiting for webcam'}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                    <p className="text-xs uppercase tracking-[0.25em] text-gray-500 mb-2">Identified</p>
                    <p className="text-sm font-semibold text-green-300">{identifiedCount}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                    <p className="text-xs uppercase tracking-[0.25em] text-gray-500 mb-2">Status</p>
                    <p className="text-sm font-semibold text-white">{status}</p>
                </div>
            </div>

            <div className="space-y-3">
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-bold uppercase tracking-[0.25em] text-gray-500">Recent detections</h3>
                    <div className="flex items-center gap-1 text-xs text-gray-500">
                        <RefreshCw size={12} className={active ? 'animate-spin text-brand-400' : 'text-gray-500'} />
                        <span>Auto-refreshing</span>
                    </div>
                </div>

                {detections.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.02] p-5 text-sm text-gray-500">
                        No faces detected yet. Point the webcam toward a face and wait for the next frame analysis.
                    </div>
                ) : (
                    <div className="space-y-2">
                        {detections.map((detection, index) => (
                            <div key={`${detection.visitor_id || 'unknown'}-${index}`} className="flex items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3">
                                <div className="min-w-0">
                                    <p className="font-semibold text-white truncate">{getDetectionLabel(detection)}</p>
                                    <p className="text-xs text-gray-500 mt-1">
                                        Confidence {(detection.confidence * 100).toFixed(0)}%
                                    </p>
                                </div>
                                {detection.identified ? (
                                    <span className="inline-flex items-center gap-1.5 rounded-full bg-green-500/10 px-2.5 py-1 text-xs font-semibold text-green-300 border border-green-500/20">
                                        <UserCheck size={12} />
                                        Identified
                                    </span>
                                ) : (
                                    <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 px-2.5 py-1 text-xs font-semibold text-red-300 border border-red-500/20">
                                        <UserX size={12} />
                                        Unidentified
                                    </span>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </section>
    )
}

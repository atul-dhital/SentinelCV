'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Camera as CameraIcon, AlertCircle, Loader } from 'lucide-react'
import { cameraService, type Camera, type DetectionResult } from '@/services/api'

type Props = {
    camera: Camera
}

async function readCameraFeedError(err: any): Promise<string> {
    const responseData = err?.response?.data
    if (responseData instanceof Blob) {
        try {
            const text = await responseData.text()
            if (!text) return 'Feed unavailable'
            try {
                const parsed = JSON.parse(text)
                return parsed.detail || 'Feed unavailable'
            } catch {
                return text
            }
        } catch {
            return 'Feed unavailable'
        }
    }

    if (typeof responseData?.detail === 'string') {
        return responseData.detail
    }

    if (typeof responseData === 'string' && responseData.trim()) {
        return responseData
    }

    return 'Feed unavailable'
}

function detectionLabel(detection: DetectionResult) {
    if (!detection.identified) return 'Unidentified'
    const name = detection.visitor_name || 'Identified'
    return `${name} ${(detection.confidence * 100).toFixed(0)}%`
}

export default function LiveFeedTile({ camera }: Props) {
    const [frameSrc, setFrameSrc] = useState<string | null>(null)
    const [detections, setDetections] = useState<DetectionResult[]>([])
    const [sourceSize, setSourceSize] = useState({ width: 0, height: 0 })
    const [containerSize, setContainerSize] = useState({ width: 0, height: 0 })
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [lastUpdated, setLastUpdated] = useState<string | null>(null)
    const containerRef = useRef<HTMLDivElement>(null)
    const requestIdRef = useRef(0)

    const fetchFrame = useCallback(async () => {
        if (!camera.is_active || !camera.rtsp_url) {
            setLoading(false)
            setError('No live feed configured')
            return
        }

        const requestId = ++requestIdRef.current
        setLoading(true)
        try {
            const res = await cameraService.getCameraStreamFrameAnalyzed(camera.id)
            if (requestId !== requestIdRef.current) return

            setFrameSrc(`data:image/jpeg;base64,${res.data.frame_data}`)
            setDetections(res.data.detections || [])
            if (res.data.width > 0 && res.data.height > 0) {
                setSourceSize({ width: res.data.width, height: res.data.height })
            }
            setError(null)
            setLastUpdated(new Date().toLocaleTimeString())
        } catch (err: any) {
            if (requestId !== requestIdRef.current) return
            const detail = await readCameraFeedError(err)
            setError(detail)
        } finally {
            if (requestId === requestIdRef.current) {
                setLoading(false)
            }
        }
    }, [camera.id, camera.is_active, camera.rtsp_url])

    useEffect(() => {
        if (!camera.is_active || !camera.rtsp_url) {
            setLoading(false)
            setError('No live feed configured')
            return () => {}
        }

        fetchFrame()
        const interval = window.setInterval(fetchFrame, 5000)

        return () => {
            window.clearInterval(interval)
            requestIdRef.current += 1
        }
    }, [fetchFrame, camera.is_active, camera.rtsp_url])

    // Track container size so detection boxes scale with the rendered image
    useEffect(() => {
        const container = containerRef.current
        if (!container || typeof ResizeObserver === 'undefined') return

        const update = () => {
            const rect = container.getBoundingClientRect()
            setContainerSize((prev) =>
                prev.width === rect.width && prev.height === rect.height
                    ? prev
                    : { width: rect.width, height: rect.height }
            )
        }
        update()
        const observer = new ResizeObserver(update)
        observer.observe(container)
        return () => observer.disconnect()
    }, [])

    const isOffline = !camera.is_active || !camera.rtsp_url || Boolean(error)

    // Map source-pixel bboxes onto the object-cover rendered image
    const overlays = (() => {
        if (!frameSrc || sourceSize.width <= 0 || sourceSize.height <= 0) return []
        if (containerSize.width <= 0 || containerSize.height <= 0) return []

        const scale = Math.max(
            containerSize.width / sourceSize.width,
            containerSize.height / sourceSize.height,
        )
        const offsetX = (containerSize.width - sourceSize.width * scale) / 2
        const offsetY = (containerSize.height - sourceSize.height * scale) / 2

        return detections
            .map((detection, index) => {
                const { x1, y1, x2, y2 } = detection.bbox || ({} as DetectionResult['bbox'])
                if (![x1, y1, x2, y2].every((v) => Number.isFinite(v))) return null
                if (x2 <= x1 || y2 <= y1) return null
                return {
                    key: `${detection.visitor_id || 'unknown'}-${index}`,
                    left: offsetX + x1 * scale,
                    top: offsetY + y1 * scale,
                    width: (x2 - x1) * scale,
                    height: (y2 - y1) * scale,
                    detection,
                }
            })
            .filter((item): item is NonNullable<typeof item> => Boolean(item))
    })()

    return (
        <div className="relative rounded-2xl overflow-hidden border border-white/10 bg-black/60">
            <div ref={containerRef} className="aspect-video relative bg-black overflow-hidden">
                {frameSrc ? (
                    <img
                        src={frameSrc}
                        alt={camera.name}
                        className="w-full h-full object-cover"
                        onLoad={(e) => {
                            // Fallback when JPEG header parsing failed server-side
                            const img = e.currentTarget
                            if (sourceSize.width === 0 && img.naturalWidth > 0) {
                                setSourceSize({ width: img.naturalWidth, height: img.naturalHeight })
                            }
                        }}
                    />
                ) : (
                    <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-gray-950 to-black">
                        {loading ? (
                            <div className="flex flex-col items-center gap-3 text-gray-400">
                                <Loader size={28} className="animate-spin text-brand-400" />
                                <span className="text-xs uppercase tracking-[0.3em] font-bold">Loading feed</span>
                            </div>
                        ) : (
                            <div className="flex flex-col items-center gap-3 text-gray-500">
                                {isOffline ? <AlertCircle size={28} className="text-red-400" /> : <CameraIcon size={28} />}
                                <span className="text-sm text-center max-w-[16rem] px-4">
                                    {error || 'Waiting for camera feed'}
                                </span>
                            </div>
                        )}
                    </div>
                )}

                {overlays.map((overlay) => {
                    const identified = overlay.detection.identified
                    const label = detectionLabel(overlay.detection)
                    return (
                        <div
                            key={overlay.key}
                            className={`absolute pointer-events-none border-2 ${identified ? 'border-green-400' : 'border-red-400'} rounded-md shadow-[0_0_0_1px_rgba(0,0,0,0.35)]`}
                            style={{
                                left: `${overlay.left}px`,
                                top: `${overlay.top}px`,
                                width: `${overlay.width}px`,
                                height: `${overlay.height}px`,
                            }}
                        >
                            <div
                                className={`absolute -top-px -left-px max-w-[14rem] truncate rounded-br-md rounded-tl-md px-1.5 py-0.5 text-[9px] font-bold tracking-[0.06em] text-white ${identified ? 'bg-green-500/90' : 'bg-red-500/90'}`}
                                title={label}
                            >
                                {label}
                            </div>
                        </div>
                    )
                })}

                <div className="absolute top-3 left-3 flex items-center gap-2">
                    <span className={`text-[10px] font-bold uppercase tracking-[0.2em] px-2 py-1 rounded-full border ${
                        isOffline
                            ? 'bg-red-500/15 text-red-300 border-red-500/20'
                            : 'bg-green-500/15 text-green-300 border-green-500/20'
                    }`}>
                        {isOffline ? 'Offline' : 'Live'}
                    </span>
                    {lastUpdated && (
                        <span className="text-[10px] font-mono font-medium text-white/80 bg-black/60 backdrop-blur-sm px-2 py-1 rounded-full">
                            {lastUpdated}
                        </span>
                    )}
                    {!isOffline && detections.length > 0 && (
                        <span className="text-[10px] font-bold text-white/90 bg-black/60 backdrop-blur-sm px-2 py-1 rounded-full">
                            {detections.filter((d) => d.identified).length}/{detections.length} identified
                        </span>
                    )}
                </div>

                <div className="absolute bottom-3 left-3 right-3 flex items-end justify-between gap-3">
                    <div className="min-w-0">
                        <p className="text-sm font-bold text-white truncate">{camera.name}</p>
                        <p className="text-xs text-white/60 truncate">{camera.location || 'No location'}</p>
                    </div>
                    <div className="shrink-0 text-right">
                        <p className="text-[10px] uppercase tracking-[0.2em] text-white/50">Status</p>
                        <p className="text-xs font-semibold text-white/80">{camera.status}</p>
                    </div>
                </div>
            </div>
        </div>
    )
}

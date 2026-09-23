'use client'

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Camera, CheckCircle2, Loader, SkipForward, X, FlipHorizontal, ScanFace } from 'lucide-react'

// Self-hosted MediaPipe assets (public/mediapipe) — no CDN so CSP default-src 'self' holds.
const MEDIAPIPE_WASM_PATH = '/mediapipe/wasm'
const MEDIAPIPE_MODEL_PATH = '/mediapipe/face_landmarker.task'

// How long (ms) the head must hold the target pose before auto-capture fires.
const STABLE_HOLD_MS = 1000

export interface GuidedPoseDefinition {
    key: string
    label: string
    emoji: string
    instruction: string
    yawMin?: number
    yawMax?: number
    pitchMin?: number
    pitchMax?: number
    absYawMin?: number // pose valid when |yaw| within [absYawMin, absYawMax] — side does not matter
    absYawMax?: number
}

// Yaw sign: positive = face turned toward the user's left (camera +X).
// Backend normalizes profile_left/right to 'profile', so profile accepts either side.
export const GUIDED_POSES: GuidedPoseDefinition[] = [
    {
        key: 'frontal', label: 'Frontal', emoji: '😐',
        instruction: 'Look straight at the camera',
        yawMin: -12, yawMax: 12, pitchMin: -12, pitchMax: 12,
    },
    {
        key: '45_left', label: '45° Left', emoji: '↖️',
        instruction: 'Turn your head 45° to your left',
        yawMin: 25, yawMax: 60,
    },
    {
        key: '45_right', label: '45° Right', emoji: '↗️',
        instruction: 'Turn your head 45° to your right',
        yawMin: -60, yawMax: -25,
    },
    {
        key: 'profile', label: 'Profile', emoji: '👤',
        instruction: 'Turn your head fully to either side',
        absYawMin: 65, absYawMax: 120,
    },
    {
        key: 'top', label: 'Top', emoji: '⬇️',
        instruction: 'Tilt your chin down toward your chest',
        pitchMin: -60, pitchMax: -18,
    },
]

type PoseStatus = 'pending' | 'capturing' | 'done' | 'error'

interface HeadPose {
    yaw: number
    pitch: number
}

interface GuidedFaceCaptureProps {
    /** Pose keys to walk through; defaults to all five. */
    angles?: string[]
    /**
     * Called per captured pose. Throw / reject to keep the wizard on the same
     * pose (e.g. backend rejected the image); resolve to advance.
     */
    onCapture: (angle: string, file: File) => Promise<void> | void
    /** Called once every requested pose is captured or skipped. */
    onFinish: (capturedAngles: string[]) => void
    onClose: () => void
}

function isPoseMatch(pose: HeadPose, target: GuidedPoseDefinition): boolean {
    if (target.absYawMin !== undefined) {
        const absYaw = Math.abs(pose.yaw)
        if (absYaw < target.absYawMin || absYaw > (target.absYawMax ?? 180)) return false
    } else if (target.yawMin !== undefined) {
        if (pose.yaw < target.yawMin || pose.yaw > (target.yawMax ?? 180)) return false
    }
    if (target.pitchMin !== undefined) {
        if (pose.pitch < target.pitchMin || pose.pitch > (target.pitchMax ?? 90)) return false
    }
    // Poses that only constrain yaw should still reject extreme pitch (and vice versa)
    if (target.pitchMin === undefined && Math.abs(pose.pitch) > 25) return false
    return true
}

function poseHint(pose: HeadPose, target: GuidedPoseDefinition): string {
    if (target.absYawMin !== undefined) {
        if (Math.abs(pose.yaw) < target.absYawMin) return 'Turn your head further to the side'
        return 'Turn back slightly toward the camera'
    }
    if (target.yawMin !== undefined && pose.yaw < target.yawMin) {
        return target.yawMin > 0 ? 'Turn a little more to your left' : 'Turn back slightly to your left'
    }
    if (target.yawMax !== undefined && pose.yaw > target.yawMax) {
        return target.yawMax < 0 ? 'Turn a little more to your right' : 'Turn back slightly to your right'
    }
    if (target.pitchMin !== undefined && pose.pitch < target.pitchMin) return 'Lift your head a little'
    if (target.pitchMax !== undefined && pose.pitch > target.pitchMax) return 'Tilt your head down a little more'
    return 'Hold still…'
}

export default function GuidedFaceCapture({ angles, onCapture, onFinish, onClose }: GuidedFaceCaptureProps) {
    const anglesKey = angles && angles.length > 0 ? angles.join('|') : ''
    const poses = useMemo(
        () =>
            anglesKey
                ? anglesKey
                      .split('|')
                      .map((key) => GUIDED_POSES.find((p) => p.key === key))
                      .filter((p): p is GuidedPoseDefinition => Boolean(p))
                : GUIDED_POSES,
        [anglesKey]
    )

    const videoRef = useRef<HTMLVideoElement>(null)
    const streamRef = useRef<MediaStream | null>(null)
    const landmarkerRef = useRef<any>(null)
    const rafRef = useRef<number | null>(null)
    const stableSinceRef = useRef<number | null>(null)
    const busyRef = useRef(false)
    const stepIndexRef = useRef(0)
    const capturedRef = useRef<string[]>([])

    const [cameraError, setCameraError] = useState<string | null>(null)
    const [detectorReady, setDetectorReady] = useState(false)
    const [detectorFailed, setDetectorFailed] = useState(false)
    const [stepIndex, setStepIndex] = useState(0)
    const [status, setStatus] = useState<Record<string, PoseStatus>>(
        () => Object.fromEntries(poses.map((p) => [p.key, 'pending' as PoseStatus]))
    )
    const [faceVisible, setFaceVisible] = useState(false)
    const [hint, setHint] = useState('Starting camera…')
    const [holdProgress, setHoldProgress] = useState(0) // 0..1 while pose held
    const [errorText, setErrorText] = useState<string | null>(null)
    const [facingMode, setFacingMode] = useState<'user' | 'environment'>('user')
    const [livePose, setLivePose] = useState<HeadPose | null>(null)

    stepIndexRef.current = stepIndex
    const currentPose = poses[stepIndex]

    const stopEverything = useCallback(() => {
        if (rafRef.current !== null) {
            cancelAnimationFrame(rafRef.current)
            rafRef.current = null
        }
        streamRef.current?.getTracks().forEach((t) => t.stop())
        streamRef.current = null
        landmarkerRef.current?.close?.()
        landmarkerRef.current = null
    }, [])

    const startCamera = useCallback(async (mode: 'user' | 'environment') => {
        streamRef.current?.getTracks().forEach((t) => t.stop())
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: mode, width: { ideal: 1280 }, height: { ideal: 720 } },
                audio: false,
            })
            streamRef.current = stream
            if (videoRef.current) {
                videoRef.current.srcObject = stream
                await videoRef.current.play().catch(() => undefined)
            }
            setCameraError(null)
        } catch {
            setCameraError('Could not access the camera. Allow permissions and try again.')
        }
    }, [])

    // Boot: camera + landmarker
    useEffect(() => {
        let cancelled = false

        const boot = async () => {
            if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
                setCameraError('Camera is not supported in this browser.')
                return
            }
            await startCamera(facingMode)
            if (cancelled) return
            try {
                const vision = await import('@mediapipe/tasks-vision')
                const fileset = await vision.FilesetResolver.forVisionTasks(MEDIAPIPE_WASM_PATH)
                if (cancelled) return
                landmarkerRef.current = await vision.FaceLandmarker.createFromOptions(fileset, {
                    baseOptions: { modelAssetPath: MEDIAPIPE_MODEL_PATH, delegate: 'GPU' },
                    runningMode: 'VIDEO',
                    numFaces: 1,
                    outputFacialTransformationMatrixes: true,
                })
                if (cancelled) {
                    landmarkerRef.current?.close?.()
                    return
                }
                setDetectorReady(true)
            } catch {
                // Model/wasm failed to load — wizard still works with the manual capture button.
                setDetectorFailed(true)
            }
        }

        void boot()
        return () => {
            cancelled = true
            stopEverything()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const captureFrame = useCallback((): Promise<File> => {
        const video = videoRef.current
        if (!video || !video.videoWidth) {
            return Promise.reject(new Error('Camera is still starting'))
        }
        const canvas = document.createElement('canvas')
        canvas.width = video.videoWidth
        canvas.height = video.videoHeight
        const ctx = canvas.getContext('2d')
        if (!ctx) return Promise.reject(new Error('Canvas unavailable'))
        ctx.drawImage(video, 0, 0)
        return new Promise((resolve, reject) =>
            canvas.toBlob(
                (blob) => {
                    if (!blob) return reject(new Error('Could not capture frame'))
                    const key = poses[stepIndexRef.current]?.key || 'face'
                    resolve(new File([blob], `guided-${key}-${Date.now()}.jpg`, { type: 'image/jpeg' }))
                },
                'image/jpeg',
                0.92
            )
        )
    }, [poses])

    const advance = useCallback(
        (fromKey: string, captured: boolean) => {
            if (captured) capturedRef.current = [...capturedRef.current, fromKey]
            const next = stepIndexRef.current + 1
            if (next >= poses.length) {
                stopEverything()
                onFinish(capturedRef.current)
            } else {
                setStepIndex(next)
                stableSinceRef.current = null
                setHoldProgress(0)
            }
        },
        [poses.length, onFinish, stopEverything]
    )

    const handleCapture = useCallback(async () => {
        const pose = poses[stepIndexRef.current]
        if (!pose || busyRef.current) return
        busyRef.current = true
        setErrorText(null)
        setStatus((prev) => ({ ...prev, [pose.key]: 'capturing' }))
        try {
            const file = await captureFrame()
            await onCapture(pose.key, file)
            setStatus((prev) => ({ ...prev, [pose.key]: 'done' }))
            advance(pose.key, true)
        } catch (err: any) {
            setStatus((prev) => ({ ...prev, [pose.key]: 'error' }))
            const detail = err?.response?.data?.detail || err?.message
            setErrorText(detail || `Could not enroll the ${pose.label} pose. Adjust and try again.`)
            stableSinceRef.current = null
            setHoldProgress(0)
        } finally {
            busyRef.current = false
        }
    }, [poses, captureFrame, onCapture, advance])

    const handleSkip = useCallback(() => {
        const pose = poses[stepIndexRef.current]
        if (!pose || busyRef.current) return
        setErrorText(null)
        advance(pose.key, false)
    }, [poses, advance])

    // Detection loop: estimate yaw/pitch each frame, auto-capture after a stable hold.
    useEffect(() => {
        if (!detectorReady) return

        const tick = () => {
            rafRef.current = requestAnimationFrame(tick)
            const video = videoRef.current
            const landmarker = landmarkerRef.current
            const pose = poses[stepIndexRef.current]
            if (!video || !landmarker || !pose || video.readyState < 2 || busyRef.current) return

            let result: any
            try {
                result = landmarker.detectForVideo(video, performance.now())
            } catch {
                return
            }

            const matrix = result?.facialTransformationMatrixes?.[0]?.data
            if (!matrix) {
                setFaceVisible(false)
                setLivePose(null)
                setHint('No face detected — center your face in the frame')
                stableSinceRef.current = null
                setHoldProgress(0)
                return
            }

            // Column-major 4x4: column 2 (m[8..10]) is the face's outward Z axis in
            // camera space. Frontal ⇒ z ≈ (0,0,1); decompose into yaw/pitch.
            const zx = matrix[8]
            const zy = matrix[9]
            const zz = matrix[10]
            const yaw = (Math.atan2(zx, zz) * 180) / Math.PI
            const pitch = (Math.atan2(zy, Math.hypot(zx, zz)) * 180) / Math.PI
            const head: HeadPose = { yaw, pitch }

            setFaceVisible(true)
            setLivePose(head)

            if (isPoseMatch(head, pose)) {
                const now = performance.now()
                if (stableSinceRef.current === null) stableSinceRef.current = now
                const held = now - stableSinceRef.current
                setHoldProgress(Math.min(held / STABLE_HOLD_MS, 1))
                setHint('Hold still…')
                if (held >= STABLE_HOLD_MS) {
                    stableSinceRef.current = null
                    setHoldProgress(0)
                    void handleCapture()
                }
            } else {
                stableSinceRef.current = null
                setHoldProgress(0)
                setHint(poseHint(head, pose))
            }
        }

        rafRef.current = requestAnimationFrame(tick)
        return () => {
            if (rafRef.current !== null) cancelAnimationFrame(rafRef.current)
            rafRef.current = null
        }
    }, [detectorReady, poses, handleCapture])

    const flipCamera = () => {
        const next = facingMode === 'user' ? 'environment' : 'user'
        setFacingMode(next)
        void startCamera(next)
    }

    const closeWizard = () => {
        stopEverything()
        onClose()
    }

    if (!currentPose) return null
    const currentStatus = status[currentPose.key]

    return (
        <div className="rounded-xl overflow-hidden border border-brand-500/30 bg-black">
            {/* Video + overlay */}
            <div className="relative">
                <video
                    ref={videoRef}
                    autoPlay
                    muted
                    playsInline
                    className={`w-full aspect-video object-cover bg-black ${facingMode === 'user' ? 'scale-x-[-1]' : ''}`}
                />
                {/* Hold-progress ring */}
                {holdProgress > 0 && (
                    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                        <div className="relative w-20 h-20">
                            <svg viewBox="0 0 80 80" className="w-20 h-20 -rotate-90">
                                <circle cx="40" cy="40" r="34" fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="6" />
                                <circle
                                    cx="40" cy="40" r="34" fill="none" stroke="#22d3ee" strokeWidth="6"
                                    strokeLinecap="round"
                                    strokeDasharray={2 * Math.PI * 34}
                                    strokeDashoffset={(1 - holdProgress) * 2 * Math.PI * 34}
                                />
                            </svg>
                            <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-cyan-300">
                                {Math.ceil((1 - holdProgress) * (STABLE_HOLD_MS / 1000))}s
                            </span>
                        </div>
                    </div>
                )}
                {/* Status banner */}
                <div className="absolute top-3 left-3 right-3 flex items-center justify-between gap-2">
                    <span className={`text-xs font-medium px-2.5 py-1.5 rounded-lg backdrop-blur ${
                        cameraError || (!faceVisible && detectorReady)
                            ? 'bg-amber-500/20 text-amber-200'
                            : 'bg-black/50 text-white'
                    }`}>
                        {cameraError
                            ? cameraError
                            : currentStatus === 'capturing'
                            ? 'Processing…'
                            : detectorReady
                            ? hint
                            : detectorFailed
                            ? 'Auto-detect unavailable — use Capture button'
                            : 'Loading face detector…'}
                    </span>
                    {detectorReady && livePose && (
                        <span className="text-[10px] font-mono px-2 py-1 rounded bg-black/50 text-gray-400 shrink-0">
                            yaw {livePose.yaw.toFixed(0)}° · pitch {livePose.pitch.toFixed(0)}°
                        </span>
                    )}
                </div>
            </div>

            {/* Controls */}
            <div className="px-4 py-4 bg-black/80 space-y-3">
                <div className="flex flex-wrap items-center gap-1.5">
                    {poses.map((p, idx) => {
                        const st = status[p.key]
                        const cls = st === 'done'
                            ? 'bg-green-500/15 text-green-300'
                            : st === 'error'
                            ? 'bg-red-500/15 text-red-300'
                            : idx === stepIndex
                            ? 'bg-brand-500/20 text-brand-300 border border-brand-500/40'
                            : 'bg-white/5 text-gray-500'
                        return (
                            <span key={p.key} className={`px-2 py-1 rounded text-[11px] font-medium ${cls}`}>
                                {st === 'done' ? '✓ ' : ''}{p.label}
                            </span>
                        )
                    })}
                </div>

                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <p className="text-sm font-semibold text-white">
                            <span className="mr-1.5">{currentPose.emoji}</span>
                            {currentPose.label}
                            <span className="ml-2 text-xs font-normal text-gray-500">
                                Pose {stepIndex + 1} of {poses.length}
                            </span>
                        </p>
                        <p className="text-xs text-gray-400 mt-0.5">{currentPose.instruction}</p>
                        {detectorReady && (
                            <p className="text-[11px] text-cyan-300/80 mt-0.5 flex items-center gap-1">
                                <ScanFace size={11} /> Auto-captures after holding the pose for 1 second
                            </p>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <button
                            type="button"
                            onClick={flipCamera}
                            disabled={currentStatus === 'capturing'}
                            title="Switch camera"
                            className="bg-white/10 hover:bg-white/20 disabled:opacity-50 text-white px-3 py-2 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5"
                        >
                            <FlipHorizontal size={14} />
                        </button>
                        <button
                            type="button"
                            onClick={handleSkip}
                            disabled={currentStatus === 'capturing'}
                            className="bg-white/10 hover:bg-white/20 disabled:opacity-50 text-white px-3 py-2 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5"
                        >
                            <SkipForward size={14} /> Skip
                        </button>
                        <button
                            type="button"
                            onClick={handleCapture}
                            disabled={currentStatus === 'capturing' || !!cameraError}
                            className="bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-xs font-medium transition-colors flex items-center gap-2"
                        >
                            {currentStatus === 'capturing' ? (
                                <><Loader size={14} className="animate-spin" /> Processing…</>
                            ) : (
                                <><Camera size={14} /> Capture Now</>
                            )}
                        </button>
                        <button
                            type="button"
                            onClick={closeWizard}
                            disabled={currentStatus === 'capturing'}
                            className="bg-red-500/10 hover:bg-red-500/20 disabled:opacity-50 text-red-400 px-3 py-2 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5"
                        >
                            <X size={14} /> Close
                        </button>
                    </div>
                </div>

                {errorText && (
                    <p className="text-xs text-red-400">{errorText}</p>
                )}
                {capturedRef.current.length > 0 && (
                    <p className="text-[11px] text-green-400/80 flex items-center gap-1">
                        <CheckCircle2 size={11} /> {capturedRef.current.length} pose{capturedRef.current.length === 1 ? '' : 's'} captured
                    </p>
                )}
            </div>
        </div>
    )
}

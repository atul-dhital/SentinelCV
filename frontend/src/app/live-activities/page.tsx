'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { Activity, AlertCircle, ArrowRight, Camera, Clock, Eye, MapPin, Plus, Pencil, RefreshCw, Trash2, UserCheck, UserX, Users, Video, WifiOff, X } from 'lucide-react'
import Navbar from '@/components/Navbar'
import LiveFeedTile from '@/components/LiveFeedTile'
import WebcamLivePanel from '@/components/WebcamLivePanel'
import MediaImage from '@/components/MediaImage'
import { analyticsService, authService, cameraService, logService, realtimeService } from '@/services/api'
import type { Camera as CameraType, DashboardStats, UserInfo, VisitorLog } from '@/services/api'
import { getStaticMediaUrl } from '@/lib/utils'
import { dedupeStreamLogs, getSourceLabel } from '@/lib/streamLogs'
import { useConfirm } from '@/components/ui/ConfirmDialog'

interface SystemHealth {
  ai_service_status: string
  avg_processing_time_ms: number
  total_processed_today: number
  error_rate: number
  storage_used_mb: number
}

const emptyStats: DashboardStats = { identified_count: 0, unidentified_count: 0, total_events: 0, total_visitors: 0, pending_review: 0, cameras_online: 0 }

const age = (ts: string) => {
  const mins = Math.floor((Date.now() - new Date(ts).getTime()) / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  return hrs < 24 ? `${hrs}h ago` : `${Math.floor(hrs / 24)}d ago`
}

const cameraTone = (camera: CameraType) => {
  if (!camera.is_active) return 'bg-white/5 text-gray-400 border-white/10'
  if (!camera.rtsp_url) return 'bg-yellow-500/10 text-yellow-300 border-yellow-500/20'
  if (camera.status === 'online') return 'bg-green-500/10 text-green-300 border-green-500/20'
  if (camera.status === 'error') return 'bg-red-500/10 text-red-300 border-red-500/20'
  return 'bg-blue-500/10 text-blue-300 border-blue-500/20'
}

const cameraStatusLabel = (camera: CameraType) => {
  if (!camera.is_active) return 'Disabled'
  if (!camera.rtsp_url) return 'No stream'
  if (camera.status === 'online') return 'Live'
  if (camera.status === 'error') return 'Feed error'
  return camera.status || 'Offline'
}


const activityLabel = (log: VisitorLog) => {
  if (log.identified) return log.visitor_name || (log.visitor_id ? `Subject PR-${log.visitor_id.slice(0, 8).toUpperCase()}` : 'Identified subject')
  return log.visitor_id ? `Subject PR-${log.visitor_id.slice(0, 8).toUpperCase()}- unknown` : 'Unidentified subject'
}

const activityImage = (log: VisitorLog) => getStaticMediaUrl(log.visitor_image_url || log.face_image_path)

// Live-updating relative timestamp
function SyncedAtLabel({ timestamp }: { timestamp: number }) {
  const [, forceUpdate] = React.useState(0)
  React.useEffect(() => {
    const iv = setInterval(() => forceUpdate(n => n + 1), 5000)
    return () => clearInterval(iv)
  }, [])
  const secsAgo = Math.floor((Date.now() - timestamp) / 1000)
  const label = secsAgo < 5 ? 'just now' : secsAgo < 60 ? `${secsAgo}s ago` : `${Math.floor(secsAgo / 60)}m ago`
  return <span>Updated {label}</span>
}

const badge = (status: string, confidence: number) => {
  if (status === 'identified') return <span className="text-xs text-green-400 bg-green-400/10 px-2 py-1 rounded-full border border-green-400/20">Identified {(confidence * 100).toFixed(0)}%</span>
  if (status === 'unidentified') return <span className="text-xs text-red-400 bg-red-400/10 px-2 py-1 rounded-full border border-red-400/20">Unidentified</span>
  if (status === 'reviewed') return <span className="text-xs text-blue-400 bg-blue-400/10 px-2 py-1 rounded-full border border-blue-400/20">Reviewed</span>
  return <span className="text-xs text-yellow-400 bg-yellow-400/10 px-2 py-1 rounded-full border border-yellow-400/20">Detected</span>
}

export default function LiveActivitiesPage() {
  const router = useRouter()
  const confirm = useConfirm()
  const lastRealtimeRefreshRef = useRef(0)
  const [stats, setStats] = useState<DashboardStats>(emptyStats)
  const [currentUser, setCurrentUser] = useState<UserInfo | null>(null)
  const [cameras, setCameras] = useState<CameraType[]>([])
  const [logs, setLogs] = useState<VisitorLog[]>([])
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncedAt, setSyncedAt] = useState<number | null>(null)
  const [wsConnected, setWsConnected] = useState(true)
  const [reconnectIn, setReconnectIn] = useState<number | null>(null)
  const retryNowRef = useRef<(() => void) | null>(null)
  const [cameraModalOpen, setCameraModalOpen] = useState(false)
  const [editingCamera, setEditingCamera] = useState<CameraType | null>(null)
  const [cameraSaving, setCameraSaving] = useState(false)
  const [cameraActionMessage, setCameraActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [cameraForm, setCameraForm] = useState({ name: '', rtsp_url: '', location: '', is_active: true })

  const fetchData = useCallback(async () => {
    try {
      const [statsRes, camerasRes, logsRes, healthRes] = await Promise.all([
        logService.getDashboardStats().catch(() => ({ data: { identified_count: 0, unidentified_count: 0, total_events: 0, total_visitors: 0, pending_review: 0, cameras_online: 0 } })),
        cameraService.getCameras().catch(() => ({ data: [] as CameraType[] })),
        logService.getLogs({ limit: 80 }).catch(() => ({ data: { items: [] as VisitorLog[], total: 0, page: 1, limit: 80, pages: 1 } })),
        analyticsService.getSystemHealth().catch(() => ({ data: null })),
      ])
      setStats(statsRes.data)
      setCameras(camerasRes.data || [])
      setLogs(dedupeStreamLogs(logsRes.data.items || [], 12))
      if (healthRes.data) setHealth(healthRes.data)
      setSyncedAt(Date.now())
    } catch (err: any) {
      if (err.response?.status === 401) {
        router.push('/login')
        return
      }
      console.error('Failed to fetch live activities:', err)
    } finally {
      setLoading(false)
    }
  }, [router])

  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null
    let mounted = true

    const start = async () => {
      const ok = await authService.ensureSession()
      if (!mounted) return
      if (!ok) {
        router.push('/login')
        return
      }
      await fetchData()
      interval = setInterval(fetchData, 15000)
    }

    void start()
    return () => {
      mounted = false
      if (interval) clearInterval(interval)
    }
  }, [fetchData, router])

  const markRealtimeSync = useCallback(() => {
    setSyncedAt(Date.now())
  }, [])

  const refreshFromRealtime = useCallback((force = false) => {
    const now = Date.now()
    if (!force && now - lastRealtimeRefreshRef.current < 5000) {
      markRealtimeSync()
      return
    }
    lastRealtimeRefreshRef.current = now
    markRealtimeSync()
    void fetchData()
  }, [fetchData, markRealtimeSync])

  const upsertCameraFromRealtime = useCallback((payload: any) => {
    if (!payload?.id) return
    setCameras((prev) => {
      const index = prev.findIndex((camera) => camera.id === payload.id)
      if (index === -1) {
        return [payload as CameraType, ...prev]
      }
      const next = [...prev]
      next[index] = { ...next[index], ...payload }
      return next
    })
    markRealtimeSync()
  }, [markRealtimeSync])

  const removeCameraFromRealtime = useCallback((cameraId?: string) => {
    if (!cameraId) return
    setCameras((prev) => prev.filter((camera) => camera.id !== cameraId))
    markRealtimeSync()
  }, [markRealtimeSync])

  useEffect(() => {
    authService.me()
      .then((res) => setCurrentUser(res.data))
      .catch(() => setCurrentUser(null))
  }, [])

  useEffect(() => {
    let ws: WebSocket | null = null
    let pingTimer: ReturnType<typeof setInterval> | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let countdownTimer: ReturnType<typeof setInterval> | null = null
    let mounted = true

    const clearCountdown = () => {
      if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null }
      setReconnectIn(null)
    }

    const scheduleReconnect = (delaySecs: number) => {
      if (!mounted) return
      setWsConnected(false)
      setReconnectIn(delaySecs)
      let remaining = delaySecs
      countdownTimer = setInterval(() => {
        remaining -= 1
        if (remaining <= 0) {
          clearCountdown()
        } else {
          setReconnectIn(remaining)
        }
      }, 1000)
      reconnectTimer = setTimeout(() => {
        clearCountdown()
        void connect()
      }, delaySecs * 1000)
    }

    const connect = async () => {
      try {
        const meRes = await authService.me()
        ws = new WebSocket(realtimeService.dashboardSocketUrl(meRes.data.organization_id))
        ws.onopen = () => {
          setWsConnected(true)
          setReconnectIn(null)
          pingTimer = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('ping'), 20000)
        }
        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data)
            switch (msg.type) {
              case 'camera.status_changed':
              case 'camera.created':
              case 'camera.updated':
                upsertCameraFromRealtime(msg.payload)
                break
              case 'camera.deleted':
                removeCameraFromRealtime(msg.payload?.id)
                break
              case 'camera.frame_processed':
                refreshFromRealtime(false)
                break
              case 'log.created':
                refreshFromRealtime(true)
                break
              default:
                refreshFromRealtime(false)
                break
            }
          } catch {
            refreshFromRealtime(false)
          }
        }
        ws.onclose = () => { if (mounted) scheduleReconnect(5) }
      } catch {
        if (mounted) scheduleReconnect(5)
      }
    }

    retryNowRef.current = () => {
      if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
      clearCountdown()
      void connect()
    }

    void authService.ensureSession().then((ok) => {
      if (ok) {
        void connect()
      }
    })
    return () => {
      mounted = false
      retryNowRef.current = null
      if (pingTimer) clearInterval(pingTimer)
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (countdownTimer) clearInterval(countdownTimer)
      if (ws) ws.close()
    }
  }, [refreshFromRealtime, removeCameraFromRealtime, upsertCameraFromRealtime])

  const canManageCameras = currentUser?.role === 'admin'

  const openAddCameraModal = () => {
    setEditingCamera(null)
    setCameraForm({ name: '', rtsp_url: '', location: '', is_active: true })
    setCameraActionMessage(null)
    setCameraModalOpen(true)
  }

  const openEditCameraModal = (camera: CameraType) => {
    setEditingCamera(camera)
    setCameraForm({
      name: camera.name || '',
      rtsp_url: camera.rtsp_url || '',
      location: camera.location || '',
      is_active: camera.is_active,
    })
    setCameraActionMessage(null)
    setCameraModalOpen(true)
  }

  const closeCameraModal = () => {
    setCameraModalOpen(false)
    setEditingCamera(null)
    setCameraSaving(false)
    setCameraActionMessage(null)
  }

  const handleSaveCamera = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!cameraForm.name.trim()) {
      setCameraActionMessage({ type: 'error', text: 'Camera name is required.' })
      return
    }

    setCameraSaving(true)
    setCameraActionMessage(null)

    try {
      if (editingCamera) {
        await cameraService.updateCamera(editingCamera.id, {
          name: cameraForm.name.trim(),
          rtsp_url: cameraForm.rtsp_url.trim() || undefined,
          location: cameraForm.location.trim() || undefined,
          is_active: cameraForm.is_active,
        })
        setCameraActionMessage({ type: 'success', text: 'Camera updated successfully.' })
      } else {
        await cameraService.createCamera({
          name: cameraForm.name.trim(),
          rtsp_url: cameraForm.rtsp_url.trim() || undefined,
          location: cameraForm.location.trim() || undefined,
        })
        setCameraActionMessage({ type: 'success', text: 'Camera added successfully.' })
      }

      await fetchData()
      setCameraModalOpen(false)
      setEditingCamera(null)
    } catch (err: any) {
      setCameraActionMessage({
        type: 'error',
        text: err.response?.data?.detail || 'Unable to save camera.',
      })
    } finally {
      setCameraSaving(false)
    }
  }

  const handleTestCamera = async (cameraId: string) => {
    setCameraActionMessage(null)
    try {
      const res = await cameraService.testCamera(cameraId)
      const statusText = res.data?.status === 'connected' ? 'Camera feed is reachable.' : res.data?.error || 'Camera test completed.'
      setCameraActionMessage({ type: 'success', text: statusText })
      await fetchData()
    } catch (err: any) {
      setCameraActionMessage({
        type: 'error',
        text: err.response?.data?.detail || 'Camera test failed.',
      })
    }
  }

  const handleDeleteCamera = async (camera: CameraType) => {
    const ok = await confirm({
      kind: 'danger',
      title: `Delete camera "${camera.name}"?`,
      description: 'The live feed will stop immediately. Historical logs and detections are preserved.',
      confirmLabel: 'Delete camera',
    })
    if (!ok) return

    setCameraActionMessage(null)
    try {
      await cameraService.deleteCamera(camera.id)
      setCameraActionMessage({ type: 'success', text: 'Camera deleted.' })
      await fetchData()
    } catch (err: any) {
      setCameraActionMessage({
        type: 'error',
        text: err.response?.data?.detail || 'Unable to delete camera.',
      })
    }
  }

  const sortedCameras = [...cameras].sort((a, b) => {
    if (a.is_active !== b.is_active) return a.is_active ? -1 : 1
    if ((a.status === 'online') !== (b.status === 'online')) return a.status === 'online' ? -1 : 1
    return a.name.localeCompare(b.name)
  })
  const readyCount = cameras.filter((camera) => Boolean(camera.rtsp_url)).length
  const liveCount = cameras.filter((camera) => camera.is_active && camera.rtsp_url && camera.status === 'online').length
  const heroMetrics = [
    { label: 'Live cameras', value: liveCount || stats.cameras_online, icon: Activity, tone: 'text-green-400' },
    { label: 'Feed ready', value: readyCount, icon: Video, tone: 'text-brand-400' },
    { label: 'Recognized', value: stats.identified_count, icon: UserCheck, tone: 'text-blue-400' },
    { label: 'Needs review', value: stats.pending_review, icon: UserX, tone: 'text-yellow-400' },
  ]

  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="pt-28 pb-20 px-6 container mx-auto">
        <div className="glass-card p-8 md:p-10 mb-10 relative overflow-hidden">
          <div className="absolute -top-12 -right-12 w-56 h-56 bg-brand-500/10 blur-[120px]" />
          <div className="absolute -bottom-10 -left-10 w-40 h-40 bg-cyan-500/10 blur-[100px]" />
          <div className="relative">
            <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-brand-500 animate-pulse" />
              <span className="text-xs font-bold text-brand-400 uppercase tracking-[0.3em] leading-none">Operations Console</span>
              <span className="text-xs text-gray-500">Live camera wall and identification stream</span>
            </motion.div>
            <motion.h1 initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} className="text-4xl md:text-6xl font-black tracking-tight mb-4 bg-gradient-to-b from-white via-white to-white/40 bg-clip-text text-transparent">
              Live Activities
            </motion.h1>
            <p className="text-gray-400 text-lg max-w-3xl leading-relaxed">
              Watch every camera, every detection, and every identification in one place. This view is built for live monitoring, not summaries.
            </p>
            <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 mt-6">
              {heroMetrics.map((item) => (
                <div key={item.label} className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3">
                  <div className="flex items-center gap-2 text-xs uppercase tracking-[0.24em] text-gray-500">
                    <item.icon size={13} className={item.tone} />
                    <span>{item.label}</span>
                  </div>
                  <div className="mt-2 text-2xl font-black tabular-nums text-white">
                    {loading ? '...' : item.value.toLocaleString()}
                  </div>
                </div>
              ))}
            </div>

            {!wsConnected && (
              <div role="alert" className="mt-4 flex items-center gap-3 rounded-2xl border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-300">
                <WifiOff size={16} className="shrink-0" />
                <span className="flex-1">
                  Live feed disconnected.
                  {reconnectIn !== null ? ` Reconnecting in ${reconnectIn}s…` : ' Reconnecting…'}
                </span>
                <button
                  onClick={() => retryNowRef.current?.()}
                  className="shrink-0 rounded-xl border border-yellow-500/40 bg-yellow-500/20 px-3 py-1 text-xs font-semibold text-yellow-200 hover:bg-yellow-500/30 transition-colors"
                >
                  Retry now
                </button>
              </div>
            )}

            {syncedAt && (
              <div className="mt-4 flex items-center gap-2 text-sm text-gray-500">
                <RefreshCw size={14} className={loading ? 'animate-spin text-brand-400' : 'text-brand-400'} />
                <SyncedAtLabel timestamp={syncedAt} />
              </div>
            )}

            <div className="flex flex-wrap gap-3 mt-6">
              {canManageCameras && (
                <button
                  onClick={openAddCameraModal}
                  className="inline-flex items-center gap-2 rounded-2xl bg-brand-600 px-4 py-3 text-sm font-bold text-white hover:bg-brand-500 transition-colors shadow-lg shadow-brand-600/20"
                >
                  <Plus size={16} />
                  Add Camera
                </button>
              )}
              <Link href="/upload" className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white hover:bg-white/10 transition-colors">
                <Video size={16} className="text-brand-400" />
                Upload Video
              </Link>
              <Link href="/visitors" className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white hover:bg-white/10 transition-colors">
                <Users size={16} className="text-blue-400" />
                Visitors
              </Link>
              <Link href="/logs" className="inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white hover:bg-white/10 transition-colors">
                <Activity size={16} className="text-purple-400" />
                Logs
              </Link>
            </div>

            {cameraActionMessage && (
              <div
                className={`mt-6 rounded-2xl border px-4 py-3 text-sm ${
                  cameraActionMessage.type === 'success'
                    ? 'border-green-500/20 bg-green-500/10 text-green-300'
                    : 'border-red-500/20 bg-red-500/10 text-red-300'
                }`}
              >
                {cameraActionMessage.text}
              </div>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">
          <div className="xl:col-span-8 space-y-8">
            <section className="space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-2xl font-black tracking-tight">Browser Webcam</h2>
                  <p className="text-gray-500 text-sm mt-1">
                    Open your local camera, then capture live frames for recognition.
                  </p>
                </div>
                <div className="text-xs uppercase tracking-[0.25em] text-gray-500">
                  First thing to check if you can’t see the webcam
                </div>
              </div>
              <WebcamLivePanel />
            </section>

            <section className="space-y-5">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-2xl font-black tracking-tight">Camera Wall</h2>
                  <p className="text-gray-500 text-sm mt-1">Every configured camera, with a live snapshot and quick drill-down to its logs.</p>
                </div>
                <Link href="/logs" className="text-brand-400 text-sm font-bold flex items-center gap-2 hover:text-brand-300 transition-colors group">
                  Open activity logs <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />
                </Link>
              </div>

              {loading ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {[1, 2, 3, 4].map((i) => <div key={i} className="glass-card p-4 animate-pulse h-[28rem]" />)}
                </div>
              ) : sortedCameras.length === 0 ? (
                <div className="glass-card p-16 text-center border-dashed border-2 border-white/5 bg-transparent">
                  <div className="w-20 h-20 bg-white/5 rounded-full flex items-center justify-center mx-auto mb-6"><Camera size={40} className="text-gray-600" /></div>
                  <h3 className="text-xl font-bold mb-2 text-white">No cameras configured</h3>
                  <p className="text-gray-500 max-w-lg mx-auto">Once camera records exist, the live wall will show every feed here with identification activity beside it.</p>
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {sortedCameras.map((camera, index) => (
                    <motion.div key={camera.id} initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }} className="glass-card p-4 space-y-4">
                      <LiveFeedTile camera={camera} />
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <h3 className="font-bold text-lg text-white truncate">{camera.name}</h3>
                          <p className="text-sm text-gray-500 flex items-center gap-1.5 mt-1"><MapPin size={14} /><span className="truncate">{camera.location || 'No location set'}</span></p>
                        </div>
                        <div className="text-right shrink-0">
                          <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold border ${cameraTone(camera)}`}>
                            {cameraStatusLabel(camera)}
                            {camera.status !== 'online' && camera.last_seen && (
                              <span className="ml-1 opacity-70">· {age(camera.last_seen)}</span>
                            )}
                          </span>
                          <p className="text-[10px] uppercase tracking-[0.2em] text-gray-500 mt-2">{camera.last_seen ? `Last seen ${age(camera.last_seen)}` : 'No recent ping'}</p>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Link href={`/logs?camera_id=${camera.id}`} className="inline-flex items-center gap-2 rounded-xl border border-brand-500/20 bg-brand-500/10 px-3 py-2 text-sm font-semibold text-brand-300 hover:bg-brand-500/20 transition-colors"><Eye size={14} />View camera logs</Link>
                        <button
                          onClick={() => handleTestCamera(camera.id)}
                          className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm font-semibold text-white hover:bg-white/10 transition-colors"
                        >
                          <RefreshCw size={14} />
                          Test feed
                        </button>
                        {canManageCameras && (
                          <>
                            <button
                              onClick={() => openEditCameraModal(camera)}
                              className="inline-flex items-center gap-2 rounded-xl border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-sm font-semibold text-blue-300 hover:bg-blue-500/20 transition-colors"
                            >
                              <Pencil size={14} />
                              Edit
                            </button>
                            <button
                              onClick={() => handleDeleteCamera(camera)}
                              className="inline-flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-300 hover:bg-red-500/20 transition-colors"
                            >
                              <Trash2 size={14} />
                              Delete
                            </button>
                          </>
                        )}
                        <span className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-gray-400"><Clock size={14} />Live snapshots refresh automatically</span>
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}
            </section>
          </div>

          <div className="xl:col-span-4 space-y-8">
            <section className="glass-card p-6">
              <div className="flex items-center justify-between gap-4 mb-5">
                <div className="flex items-center gap-3">
                  <RefreshCw className={`text-brand-500 ${loading ? 'animate-spin' : ''}`} size={18} />
                  <h2 className="text-xl font-black tracking-tight">Live Identifications</h2>
                </div>
                <span className="text-xs text-gray-500 uppercase tracking-[0.25em]">Newest first</span>
              </div>

              {logs.length === 0 ? (
                <div className="text-center py-12">
                  <Activity size={36} className="mx-auto text-gray-600 mb-4" />
                  <h3 className="font-bold text-white mb-2">No live detections yet</h3>
                  <p className="text-sm text-gray-500">Detected faces and identification events will appear here as they happen.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {logs.map((log, index) => (
                    <motion.div key={log.id} initial={{ opacity: 0, x: 14 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: index * 0.04 }} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 hover:bg-white/[0.05] transition-colors">
                      <div className="flex items-start gap-3">
                        <div className="relative shrink-0">
                          <div className="w-16 h-16 rounded-2xl overflow-hidden bg-gray-900 ring-1 ring-white/10">
                            {activityImage(log) ? (
                              <MediaImage
                                sources={[log.visitor_image_url, log.face_image_path]}
                                alt={activityLabel(log)}
                                className="w-full h-full object-cover"
                                fallback={<div className="w-full h-full flex items-center justify-center"><Users size={24} className="text-gray-700" /></div>}
                              />
                            ) : <div className="w-full h-full flex items-center justify-center"><Users size={24} className="text-gray-700" /></div>}
                          </div>
                          <div className="absolute -bottom-1 -right-1 bg-gray-950 p-1 rounded-md border border-white/10"><Activity size={10} className="text-brand-400" /></div>
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <h3 className="font-bold text-white truncate">{activityLabel(log)}</h3>
                              <p className="text-xs text-gray-500 mt-1 truncate">{getSourceLabel(log, cameras)}</p>
                            </div>
                            {badge(log.status, log.confidence)}
                          </div>
                          <div className="flex items-center gap-2 text-xs text-gray-500 mt-3"><Clock size={12} /><span>{age(log.timestamp)}</span><span className="w-1 h-1 rounded-full bg-gray-700" /><span>{(log.confidence * 100).toFixed(0)}% confidence</span></div>
                          <div className="flex flex-wrap gap-2 mt-4">
                            <Link href={`/logs/${log.id}`} className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-white hover:border-brand-500/30 hover:bg-brand-500/10 transition-colors"><Eye size={13} />Review log</Link>
                            {log.identified && log.visitor_id && <Link href={`/visitors/${log.visitor_id}`} className="inline-flex items-center gap-2 rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2 text-xs font-semibold text-green-300 hover:bg-green-500/20 transition-colors"><ArrowRight size={13} />Open visitor</Link>}
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}
            </section>

            <section className="glass-card p-6">
              <div className="flex items-center gap-3 mb-5">
                <AlertCircle size={18} className="text-brand-400" />
                <h2 className="text-xl font-black tracking-tight">System Pulse</h2>
              </div>
              {health ? (
                <div className="space-y-4 text-sm">
                  <div className="flex justify-between gap-4"><span className="text-gray-500">AI Status</span><span className={health.ai_service_status === 'healthy' ? 'text-green-400' : 'text-yellow-400'}>{health.ai_service_status}</span></div>
                  <div className="flex justify-between gap-4"><span className="text-gray-500">Processed Today</span><span className="text-white font-semibold">{health.total_processed_today}</span></div>
                  <div className="flex justify-between gap-4"><span className="text-gray-500">Average Processing</span><span className="text-white font-semibold">{health.avg_processing_time_ms.toFixed(0)} ms</span></div>
                  <div className="flex justify-between gap-4"><span className="text-gray-500">Error Rate</span><span className="text-white font-semibold">{(health.error_rate * 100).toFixed(1)}%</span></div>
                  <div className="flex justify-between gap-4"><span className="text-gray-500">Storage Used</span><span className="text-white font-semibold">{health.storage_used_mb.toFixed(0)} MB</span></div>
                </div>
              ) : (
                <p className="text-sm text-gray-500">System health data is unavailable right now.</p>
              )}
            </section>
          </div>
        </div>

        {cameraModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
            <div className="w-full max-w-2xl glass-card border border-white/10 p-6 md:p-8 relative">
              <button
                onClick={closeCameraModal}
                className="absolute top-4 right-4 p-2 rounded-xl text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
                aria-label="Close camera form"
              >
                <X size={18} />
              </button>

              <div className="flex items-center gap-3 mb-6">
                <div className="p-3 rounded-2xl bg-brand-500/10 text-brand-400">
                  <Camera size={22} />
                </div>
                <div>
                  <h2 className="text-2xl font-black tracking-tight">
                    {editingCamera ? 'Edit Camera' : 'Add Camera'}
                  </h2>
                  <p className="text-sm text-gray-500">
                    Create a new stream source or update an existing camera record.
                  </p>
                </div>
              </div>

              {cameraActionMessage && (
                <div
                  className={`mb-5 rounded-2xl border px-4 py-3 text-sm ${
                    cameraActionMessage.type === 'success'
                      ? 'border-green-500/20 bg-green-500/10 text-green-300'
                      : 'border-red-500/20 bg-red-500/10 text-red-300'
                  }`}
                >
                  {cameraActionMessage.text}
                </div>
              )}

              <form onSubmit={handleSaveCamera} className="space-y-4">
                <div>
                  <label className="block text-sm font-semibold text-gray-300 mb-2">Camera name</label>
                  <input
                    value={cameraForm.name}
                    onChange={(event) => setCameraForm((prev) => ({ ...prev, name: event.target.value }))}
                    className="w-full rounded-2xl border border-white/10 bg-black/30 px-4 py-3 text-white outline-none focus:border-brand-500"
                    placeholder="Front entrance camera"
                  />
                </div>

                <div>
                  <label className="block text-sm font-semibold text-gray-300 mb-2">RTSP URL</label>
                  <input
                    value={cameraForm.rtsp_url}
                    onChange={(event) => setCameraForm((prev) => ({ ...prev, rtsp_url: event.target.value }))}
                    className={`w-full rounded-2xl border bg-black/30 px-4 py-3 text-white outline-none focus:border-brand-500 ${
                      cameraForm.rtsp_url && !cameraForm.rtsp_url.match(/^rtsp:\/\/.+/) ? 'border-red-500/50' : 'border-white/10'
                    }`}
                    placeholder="rtsp://username:password@host:port/path"
                  />
                  {cameraForm.rtsp_url && !cameraForm.rtsp_url.match(/^rtsp:\/\/.+/) && (
                    <p className="text-xs text-red-400 mt-1">URL must start with rtsp:// — e.g. rtsp://admin:pass@192.168.1.100:554/stream</p>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-semibold text-gray-300 mb-2">Location</label>
                  <input
                    value={cameraForm.location}
                    onChange={(event) => setCameraForm((prev) => ({ ...prev, location: event.target.value }))}
                    className="w-full rounded-2xl border border-white/10 bg-black/30 px-4 py-3 text-white outline-none focus:border-brand-500"
                    placeholder="Lobby, gate, parking lot..."
                  />
                </div>

                {editingCamera && (
                  <label className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-gray-300">
                    <input
                      type="checkbox"
                      checked={cameraForm.is_active}
                      onChange={(event) => setCameraForm((prev) => ({ ...prev, is_active: event.target.checked }))}
                      className="h-4 w-4 accent-brand-500"
                    />
                    Camera is active
                  </label>
                )}

                <div className="flex flex-col sm:flex-row gap-3 pt-2">
                  <button
                    type="button"
                    onClick={closeCameraModal}
                    className="flex-1 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-semibold text-white hover:bg-white/10 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={cameraSaving}
                    className="flex-1 rounded-2xl bg-brand-600 px-4 py-3 text-sm font-bold text-white hover:bg-brand-500 disabled:opacity-50 transition-colors"
                  >
                    {cameraSaving ? 'Saving...' : editingCamera ? 'Save changes' : 'Add camera'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

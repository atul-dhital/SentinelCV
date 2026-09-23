'use client'

import React, { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Cpu, Plus, Pencil, Trash2, RefreshCw, Copy, Upload, AlertCircle, CheckCircle } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { authService, edgeDeviceService } from '@/services/api'
import type { EdgeDevice, EdgeDeviceEvent, UserInfo } from '@/services/api'
import { useConfirm } from '@/components/ui/ConfirmDialog'

const statusTone = (status: string) => {
    if (status === 'online') return 'bg-green-500/10 text-green-300 border-green-500/20'
    if (status === 'error') return 'bg-red-500/10 text-red-300 border-red-500/20'
    return 'bg-yellow-500/10 text-yellow-300 border-yellow-500/20'
}

const relativeTime = (timestamp?: string | null) => {
    if (!timestamp) return 'Never'
    const diffMs = Date.now() - new Date(timestamp).getTime()
    if (diffMs < 60000) return 'Just now'
    const mins = Math.floor(diffMs / 60000)
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    return `${days}d ago`
}

const emptyForm = {
    name: '',
    device_type: 'jetson',
    location: '',
    endpoint_url: '',
    ip_address: '',
    serial_number: '',
    tags: '',
    model_version_id: '',
    model_artifact_path: '',
}

const emptyExport = {
    model_path: '',
    input_shape: '1,3,224,224',
    output_path: '',
    model_name: '',
    opset_version: 13,
}

export default function EdgeDevicesPage() {
    const confirm = useConfirm()
    const [devices, setDevices] = useState<EdgeDevice[]>([])
    const [loading, setLoading] = useState(true)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [showForm, setShowForm] = useState(false)
    const [editing, setEditing] = useState<EdgeDevice | null>(null)
    const [form, setForm] = useState({ ...emptyForm })
    const [currentUser, setCurrentUser] = useState<UserInfo | null>(null)
    const [tokenReveal, setTokenReveal] = useState<string | null>(null)
    const [tokenDeviceName, setTokenDeviceName] = useState<string | null>(null)
    const [selectedDevice, setSelectedDevice] = useState<EdgeDevice | null>(null)
    const [events, setEvents] = useState<EdgeDeviceEvent[]>([])
    const [eventsLoading, setEventsLoading] = useState(false)
    const [exporting, setExporting] = useState(false)
    const [exportForm, setExportForm] = useState({ ...emptyExport })
    const [showExport, setShowExport] = useState(false)

    const canManage = currentUser?.role === 'admin'

    useEffect(() => {
        authService.me().then(res => setCurrentUser(res.data)).catch(() => setCurrentUser(null))
        fetchDevices()
    }, [])

    const fetchDevices = async () => {
        setLoading(true)
        try {
            const res = await edgeDeviceService.list()
            setDevices(res.data || [])
        } catch (err: any) {
            if (err.response?.status === 401) {
                window.location.href = '/login'
                return
            }
            setMessage({ type: 'error', text: 'Failed to load edge devices.' })
        } finally {
            setLoading(false)
        }
    }

    const openCreate = () => {
        setEditing(null)
        setForm({ ...emptyForm })
        setShowForm(true)
        setMessage(null)
    }

    const openEdit = (device: EdgeDevice) => {
        setEditing(device)
        setForm({
            name: device.name,
            device_type: device.device_type || 'jetson',
            location: device.location || '',
            endpoint_url: device.endpoint_url || '',
            ip_address: device.ip_address || '',
            serial_number: device.serial_number || '',
            tags: (device.tags || []).join(', '),
            model_version_id: device.model_version_id || '',
            model_artifact_path: device.model_artifact_path || '',
        })
        setShowForm(true)
        setMessage(null)
    }

    const closeForm = () => {
        setShowForm(false)
        setEditing(null)
    }

    const handleSave = async (event: React.FormEvent) => {
        event.preventDefault()
        if (!form.name.trim()) {
            setMessage({ type: 'error', text: 'Device name is required.' })
            return
        }

        const payload = {
            name: form.name.trim(),
            device_type: form.device_type.trim() || 'jetson',
            location: form.location.trim() || undefined,
            endpoint_url: form.endpoint_url.trim() || undefined,
            ip_address: form.ip_address.trim() || undefined,
            serial_number: form.serial_number.trim() || undefined,
            tags: form.tags
                ? form.tags.split(',').map(tag => tag.trim()).filter(Boolean)
                : undefined,
            model_version_id: form.model_version_id.trim() || undefined,
            model_artifact_path: form.model_artifact_path.trim() || undefined,
        }

        try {
            if (editing) {
                await edgeDeviceService.update(editing.id, payload)
                setMessage({ type: 'success', text: 'Edge device updated.' })
            } else {
                const res = await edgeDeviceService.create(payload)
                setTokenReveal(res.data.device_token)
                setTokenDeviceName(res.data.device.name)
                setMessage({ type: 'success', text: 'Edge device created. Copy the token now.' })
            }
            closeForm()
            fetchDevices()
        } catch (err: any) {
            setMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to save edge device.' })
        }
    }

    const deleteDevice = async (deviceId: string) => {
        const target = devices.find(d => d.id === deviceId)
        const ok = await confirm({
            kind: 'danger',
            title: target ? `Delete "${target.name}"?` : 'Delete edge device?',
            description: 'The device will stop posting events immediately. Its token will be invalidated.',
            confirmLabel: 'Delete device',
        })
        if (!ok) return
        try {
            await edgeDeviceService.delete(deviceId)
            fetchDevices()
        } catch {
            setMessage({ type: 'error', text: 'Failed to delete edge device.' })
        }
    }

    const rotateToken = async (device: EdgeDevice) => {
        const ok = await confirm({
            kind: 'danger',
            title: `Rotate token for "${device.name}"?`,
            description: 'The current token will stop working immediately. Update the device with the new token after rotation.',
            confirmLabel: 'Rotate token',
        })
        if (!ok) return
        try {
            const res = await edgeDeviceService.rotateToken(device.id)
            setTokenReveal(res.data.device_token)
            setTokenDeviceName(res.data.device.name)
            fetchDevices()
        } catch {
            setMessage({ type: 'error', text: 'Failed to rotate token.' })
        }
    }

    const copyToken = async () => {
        if (!tokenReveal) return
        try {
            await navigator.clipboard.writeText(tokenReveal)
            setMessage({ type: 'success', text: 'Token copied to clipboard.' })
        } catch {
            setMessage({ type: 'error', text: 'Failed to copy token.' })
        }
    }

    const selectDevice = async (device: EdgeDevice) => {
        setSelectedDevice(device)
        setEvents([])
        setEventsLoading(true)
        try {
            const res = await edgeDeviceService.listEvents(device.id)
            setEvents(res.data || [])
        } catch {
            setEvents([])
        } finally {
            setEventsLoading(false)
        }
    }

    const openExport = (device: EdgeDevice) => {
        setSelectedDevice(device)
        setExportForm({ ...emptyExport })
        setShowExport(true)
    }

    const handleExport = async (event: React.FormEvent) => {
        event.preventDefault()
        if (!selectedDevice) return
        if (!exportForm.model_path.trim()) {
            setMessage({ type: 'error', text: 'Model path is required.' })
            return
        }
        setExporting(true)
        try {
            const shape = exportForm.input_shape
                .split(',')
                .map(val => parseInt(val.trim(), 10))
                .filter(val => !Number.isNaN(val) && val > 0)
            await edgeDeviceService.exportOnnx(selectedDevice.id, {
                model_path: exportForm.model_path.trim(),
                input_shape: shape.length ? shape : undefined,
                output_path: exportForm.output_path.trim() || undefined,
                model_name: exportForm.model_name.trim() || undefined,
                opset_version: exportForm.opset_version || 13,
            })
            setMessage({ type: 'success', text: 'Edge export request completed.' })
            setShowExport(false)
            fetchDevices()
        } catch (err: any) {
            setMessage({ type: 'error', text: err.response?.data?.detail || 'Edge export failed.' })
        } finally {
            setExporting(false)
        }
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <div className="flex items-center justify-between gap-4 mb-8">
                    <div>
                        <h1 className="text-3xl font-bold flex items-center gap-3">
                            <Cpu className="text-brand-400" /> Edge Devices
                        </h1>
                        <p className="text-gray-400 mt-2">Manage edge deployments, sync status, and device alerts.</p>
                    </div>
                    {canManage && (
                        <button
                            onClick={openCreate}
                            className="flex items-center gap-2 px-4 py-2.5 bg-brand-500/20 text-brand-200 border border-brand-500/30 rounded-xl hover:bg-brand-500/30 transition"
                        >
                            <Plus size={18} /> Add device
                        </button>
                    )}
                </div>

                {message && (
                    <div className={`mb-6 px-4 py-3 rounded-xl border ${message.type === 'success'
                        ? 'bg-green-500/10 border-green-500/20 text-green-300'
                        : 'bg-red-500/10 border-red-500/20 text-red-300'
                        }`}>
                        {message.text}
                    </div>
                )}

                {loading ? (
                    <div className="text-gray-500">Loading edge devices...</div>
                ) : devices.length === 0 ? (
                    <div className="text-gray-500">No edge devices registered yet.</div>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        {devices.map((device) => (
                            <motion.div
                                key={device.id}
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="bg-white/5 border border-white/10 rounded-2xl p-5 hover:border-brand-500/30 transition"
                            >
                                <div className="flex items-start justify-between gap-4">
                                    <div>
                                        <h3 className="text-lg font-semibold">{device.name}</h3>
                                        <p className="text-xs text-gray-500">{device.device_type} - Token {device.token_prefix}</p>
                                    </div>
                                    <span className={`text-xs px-3 py-1 rounded-full border ${statusTone(device.status)}`}>
                                        {device.status}
                                    </span>
                                </div>

                                <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-gray-300">
                                    <div>
                                        <p className="text-xs text-gray-500">Last seen</p>
                                        <p>{relativeTime(device.last_seen)}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-gray-500">Last sync</p>
                                        <p>{relativeTime(device.last_sync_at)}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-gray-500">Sync status</p>
                                        <p className="capitalize">{device.last_sync_status || 'unknown'}</p>
                                    </div>
                                    <div>
                                        <p className="text-xs text-gray-500">Export</p>
                                        <p>{device.last_export_status || 'n/a'}</p>
                                    </div>
                                </div>

                                <div className="mt-4 flex flex-wrap gap-2">
                                    <button
                                        onClick={() => selectDevice(device)}
                                        className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs hover:bg-white/10"
                                    >
                                        View events
                                    </button>
                                    {canManage && (
                                        <>
                                            <button
                                                onClick={() => openEdit(device)}
                                                className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs hover:bg-white/10 flex items-center gap-1"
                                            >
                                                <Pencil size={12} /> Edit
                                            </button>
                                            <button
                                                onClick={() => rotateToken(device)}
                                                className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs hover:bg-white/10 flex items-center gap-1"
                                            >
                                                <RefreshCw size={12} /> Rotate token
                                            </button>
                                            <button
                                                onClick={() => openExport(device)}
                                                className="px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 text-xs hover:bg-white/10 flex items-center gap-1"
                                            >
                                                <Upload size={12} /> Export model
                                            </button>
                                            <button
                                                onClick={() => deleteDevice(device.id)}
                                                className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-300 hover:bg-red-500/20 flex items-center gap-1"
                                            >
                                                <Trash2 size={12} /> Delete
                                            </button>
                                        </>
                                    )}
                                </div>
                            </motion.div>
                        ))}
                    </div>
                )}

                <div className="mt-10">
                    <h2 className="text-xl font-semibold mb-3">Device events</h2>
                    {selectedDevice ? (
                        <div className="bg-white/5 border border-white/10 rounded-2xl p-5">
                            <div className="flex items-center justify-between mb-3">
                                <div>
                                    <p className="text-sm text-gray-400">{selectedDevice.name}</p>
                                    <p className="text-xs text-gray-500">{selectedDevice.device_type}</p>
                                </div>
                                <button
                                    onClick={() => selectDevice(selectedDevice)}
                                    className="text-xs text-gray-300 flex items-center gap-1"
                                >
                                    <RefreshCw size={12} /> Refresh
                                </button>
                            </div>
                            {eventsLoading ? (
                                <div className="text-gray-500">Loading events...</div>
                            ) : events.length === 0 ? (
                                <div className="text-gray-500">No events yet.</div>
                            ) : (
                                <div className="space-y-3">
                                    {events.map((eventItem) => (
                                        <div key={eventItem.id} className="p-3 rounded-xl border border-white/10 bg-black/40">
                                            <div className="flex items-center justify-between">
                                                <span className="text-sm font-semibold">{eventItem.title}</span>
                                                <span className="text-xs text-gray-500">{new Date(eventItem.created_at).toLocaleString()}</span>
                                            </div>
                                            <p className="text-xs text-gray-400 mt-1">{eventItem.message || 'No details provided.'}</p>
                                            <p className="text-[10px] text-gray-500 mt-2">{eventItem.event_type} - {eventItem.severity}</p>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    ) : (
                        <div className="text-gray-500">Select a device to view events.</div>
                    )}
                </div>
            </main>

            <AnimatePresence>
                {showForm && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center px-4"
                    >
                        <motion.div
                            initial={{ y: 20, opacity: 0 }}
                            animate={{ y: 0, opacity: 1 }}
                            exit={{ y: 20, opacity: 0 }}
                            className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-lg"
                        >
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-lg font-semibold">{editing ? 'Edit edge device' : 'Add edge device'}</h3>
                                <button onClick={closeForm} className="text-gray-500 hover:text-white">x</button>
                            </div>
                            <form onSubmit={handleSave} className="space-y-4">
                                <input
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                    placeholder="Device name"
                                    value={form.name}
                                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                                />
                                <div className="grid grid-cols-2 gap-3">
                                    <input
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                        placeholder="Device type (jetson, coral)"
                                        value={form.device_type}
                                        onChange={(e) => setForm({ ...form, device_type: e.target.value })}
                                    />
                                    <input
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                        placeholder="Location"
                                        value={form.location}
                                        onChange={(e) => setForm({ ...form, location: e.target.value })}
                                    />
                                </div>
                                <input
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                    placeholder="Endpoint URL"
                                    value={form.endpoint_url}
                                    onChange={(e) => setForm({ ...form, endpoint_url: e.target.value })}
                                />
                                <div className="grid grid-cols-2 gap-3">
                                    <input
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                        placeholder="IP address"
                                        value={form.ip_address}
                                        onChange={(e) => setForm({ ...form, ip_address: e.target.value })}
                                    />
                                    <input
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                        placeholder="Serial number"
                                        value={form.serial_number}
                                        onChange={(e) => setForm({ ...form, serial_number: e.target.value })}
                                    />
                                </div>
                                <input
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                    placeholder="Tags (comma-separated)"
                                    value={form.tags}
                                    onChange={(e) => setForm({ ...form, tags: e.target.value })}
                                />
                                <input
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                    placeholder="Model version ID"
                                    value={form.model_version_id}
                                    onChange={(e) => setForm({ ...form, model_version_id: e.target.value })}
                                />
                                <input
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                    placeholder="Model artifact path"
                                    value={form.model_artifact_path}
                                    onChange={(e) => setForm({ ...form, model_artifact_path: e.target.value })}
                                />
                                <button
                                    type="submit"
                                    className="w-full bg-brand-500/20 border border-brand-500/30 text-brand-200 rounded-xl py-2.5 flex items-center justify-center gap-2"
                                >
                                    <CheckCircle size={16} /> Save device
                                </button>
                            </form>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>

            <AnimatePresence>
                {tokenReveal && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center px-4"
                    >
                        <motion.div
                            initial={{ y: 20, opacity: 0 }}
                            animate={{ y: 0, opacity: 1 }}
                            exit={{ y: 20, opacity: 0 }}
                            className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-md"
                        >
                            <div className="flex items-center gap-3 mb-3 text-green-300">
                                <CheckCircle size={18} />
                                <h3 className="text-lg font-semibold">Edge token ready</h3>
                            </div>
                            <p className="text-sm text-gray-400 mb-4">Token for {tokenDeviceName || 'device'} (copy now, it will not be shown again).</p>
                            <div className="bg-black/40 border border-white/10 rounded-xl p-3 text-xs break-all font-mono text-gray-200">
                                {tokenReveal}
                            </div>
                            <div className="mt-4 flex items-center gap-2">
                                <button
                                    onClick={copyToken}
                                    className="flex-1 px-4 py-2 rounded-xl bg-brand-500/20 border border-brand-500/30 text-brand-200 flex items-center justify-center gap-2"
                                >
                                    <Copy size={14} /> Copy token
                                </button>
                                <button
                                    onClick={() => setTokenReveal(null)}
                                    className="px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-gray-300"
                                >
                                    Close
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>

            <AnimatePresence>
                {showExport && selectedDevice && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center px-4"
                    >
                        <motion.div
                            initial={{ y: 20, opacity: 0 }}
                            animate={{ y: 0, opacity: 1 }}
                            exit={{ y: 20, opacity: 0 }}
                            className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-lg"
                        >
                            <div className="flex items-center justify-between mb-4">
                                <h3 className="text-lg font-semibold">Export model for {selectedDevice.name}</h3>
                                <button onClick={() => setShowExport(false)} className="text-gray-500 hover:text-white">x</button>
                            </div>
                            <form onSubmit={handleExport} className="space-y-4">
                                <input
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                    placeholder="Model path (torch artifact)"
                                    value={exportForm.model_path}
                                    onChange={(e) => setExportForm({ ...exportForm, model_path: e.target.value })}
                                />
                                <div className="grid grid-cols-2 gap-3">
                                    <input
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                        placeholder="Input shape (1,3,224,224)"
                                        value={exportForm.input_shape}
                                        onChange={(e) => setExportForm({ ...exportForm, input_shape: e.target.value })}
                                    />
                                    <input
                                        className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                        placeholder="Opset version"
                                        type="number"
                                        value={exportForm.opset_version}
                                        onChange={(e) => setExportForm({ ...exportForm, opset_version: parseInt(e.target.value || '13', 10) })}
                                    />
                                </div>
                                <input
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                    placeholder="Output path (optional)"
                                    value={exportForm.output_path}
                                    onChange={(e) => setExportForm({ ...exportForm, output_path: e.target.value })}
                                />
                                <input
                                    className="w-full bg-black/40 border border-white/10 rounded-xl px-4 py-2 text-sm"
                                    placeholder="Model name (optional)"
                                    value={exportForm.model_name}
                                    onChange={(e) => setExportForm({ ...exportForm, model_name: e.target.value })}
                                />
                                <button
                                    type="submit"
                                    disabled={exporting}
                                    className="w-full bg-brand-500/20 border border-brand-500/30 text-brand-200 rounded-xl py-2.5 flex items-center justify-center gap-2 disabled:opacity-60"
                                >
                                    {exporting ? <RefreshCw size={16} className="animate-spin" /> : <Upload size={16} />}
                                    {exporting ? 'Exporting...' : 'Export ONNX'}
                                </button>
                                <div className="text-xs text-gray-500 flex items-center gap-2">
                                    <AlertCircle size={12} /> Ensure the AI service is running for export.
                                </div>
                            </form>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}

'use client'

import React, { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Webhook, KeyRound, Play, Plus, RefreshCw, Trash2, ShieldCheck, Copy } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { authService, webhookService, type UserInfo } from '@/services/api'
import type { ApiKeyItem, WebhookItem } from '@/types/integrations'
import { useConfirm } from '@/components/ui/ConfirmDialog'

const webhookFormDefaults = {
    url: '',
    events: 'visitor.detected,visitor.identified,visitor.unidentified',
    secret: '',
}

const apiKeyFormDefaults = {
    name: '',
    permissions: 'read',
}

export default function IntegrationsPage() {
    const confirm = useConfirm()
    const [user, setUser] = useState<UserInfo | null>(null)
    const [loading, setLoading] = useState(true)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [webhooks, setWebhooks] = useState<WebhookItem[]>([])
    const [apiKeys, setApiKeys] = useState<ApiKeyItem[]>([])
    const [selectedWebhookId, setSelectedWebhookId] = useState<string | null>(null)
    const [webhookLogs, setWebhookLogs] = useState<any[]>([])
    const [logLoading, setLogLoading] = useState(false)
    const [newWebhook, setNewWebhook] = useState(webhookFormDefaults)
    const [newApiKey, setNewApiKey] = useState(apiKeyFormDefaults)
    const [revealedKey, setRevealedKey] = useState<string | null>(null)

    const canManage = user?.role === 'admin'

    useEffect(() => {
        const bootstrap = async () => {
            try {
                const meRes = await authService.me()
                const nextUser = meRes.data
                setUser(nextUser)

                if (nextUser?.role === 'admin') {
                    await Promise.all([fetchWebhooks(true), fetchApiKeys(true)])
                } else {
                    setWebhooks([])
                    setApiKeys([])
                    setWebhookLogs([])
                    setSelectedWebhookId(null)
                }
            } catch {
                setUser(null)
            } finally {
                setLoading(false)
            }
        }

        bootstrap().catch(() => setLoading(false))
    }, [])

    const fetchWebhooks = async (force = false) => {
        if (!force && !canManage) return
        try {
            const res = await webhookService.list()
            setWebhooks(res.data || [])
        } catch {
            setWebhooks([])
        }
    }

    const fetchApiKeys = async (force = false) => {
        if (!force && !canManage) return
        try {
            const res = await webhookService.listApiKeys()
            setApiKeys(res.data || [])
        } catch {
            setApiKeys([])
        }
    }

    const fetchLogs = async (webhookId: string) => {
        if (!canManage) return
        setSelectedWebhookId(webhookId)
        setLogLoading(true)
        try {
            const res = await webhookService.getLogs(webhookId)
            setWebhookLogs(res.data || [])
        } catch {
            setWebhookLogs([])
        } finally {
            setLogLoading(false)
        }
    }

    const createWebhook = async (event: React.FormEvent) => {
        event.preventDefault()
        if (!canManage) return
        try {
            await webhookService.create({
                url: newWebhook.url,
                events: newWebhook.events.split(',').map((item) => item.trim()).filter(Boolean),
                secret: newWebhook.secret || undefined,
            })
            setMessage({ type: 'success', text: 'Webhook created.' })
            setNewWebhook(webhookFormDefaults)
            await fetchWebhooks()
        } catch (error: any) {
            setMessage({ type: 'error', text: error.response?.data?.detail || 'Failed to create webhook.' })
        }
    }

    const createApiKey = async (event: React.FormEvent) => {
        event.preventDefault()
        if (!canManage) return
        try {
            const res = await webhookService.createApiKey({
                name: newApiKey.name,
                permissions: newApiKey.permissions.split(',').map((item) => item.trim()).filter(Boolean),
            })
            setRevealedKey(res.data.full_key)
            setMessage({ type: 'success', text: 'API key created. Copy it now.' })
            setNewApiKey(apiKeyFormDefaults)
            await fetchApiKeys()
        } catch (error: any) {
            setMessage({ type: 'error', text: error.response?.data?.detail || 'Failed to create API key.' })
        }
    }

    const testWebhook = async (webhookId: string) => {
        if (!canManage) return
        try {
            await webhookService.test(webhookId)
            setMessage({ type: 'success', text: 'Test webhook sent.' })
            await fetchLogs(webhookId)
        } catch (error: any) {
            setMessage({ type: 'error', text: error.response?.data?.detail || 'Webhook test failed.' })
        }
    }

    const deleteWebhook = async (webhookId: string) => {
        if (!canManage) return
        const target = webhooks.find(w => w.id === webhookId)
        const ok = await confirm({
            kind: 'danger',
            title: target ? `Delete webhook for ${target.url}?` : 'Delete webhook?',
            description: 'The endpoint will stop receiving events immediately.',
            confirmLabel: 'Delete webhook',
        })
        if (!ok) return
        try {
            await webhookService.delete(webhookId)
            setMessage({ type: 'success', text: 'Webhook deleted.' })
            await fetchWebhooks()
        } catch {
            setMessage({ type: 'error', text: 'Failed to delete webhook.' })
        }
    }

    const deleteApiKey = async (apiKeyId: string) => {
        if (!canManage) return
        const target = apiKeys.find(k => k.id === apiKeyId)
        const ok = await confirm({
            kind: 'danger',
            title: target ? `Revoke API key "${target.name}"?` : 'Revoke API key?',
            description: 'Any client using this key will immediately fail to authenticate. This cannot be undone.',
            confirmLabel: 'Revoke key',
        })
        if (!ok) return
        try {
            await webhookService.deleteApiKey(apiKeyId)
            setMessage({ type: 'success', text: 'API key revoked.' })
            await fetchApiKeys()
        } catch {
            setMessage({ type: 'error', text: 'Failed to revoke API key.' })
        }
    }

    const copyKey = async () => {
        if (!revealedKey) return
        await navigator.clipboard.writeText(revealedKey)
        setMessage({ type: 'success', text: 'API key copied.' })
    }

    if (loading) {
        return (
            <div className="min-h-screen bg-[#050505] text-white">
                <Navbar />
                <main className="pt-28 px-6 max-w-6xl mx-auto">
                    <div className="animate-pulse space-y-6">
                        <div className="h-10 w-72 bg-white/10 rounded-xl" />
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                            <div className="h-80 bg-white/10 rounded-3xl" />
                            <div className="h-80 bg-white/10 rounded-3xl" />
                        </div>
                    </div>
                </main>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-6xl mx-auto">
                <div className="flex items-center justify-between gap-4 mb-8">
                    <div>
                        <h1 className="text-4xl font-extrabold bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent flex items-center gap-3">
                            <Webhook className="text-brand-400" /> Integrations
                        </h1>
                        <p className="text-gray-400 mt-2">Manage webhooks, signed event delivery, and API keys for external systems.</p>
                    </div>
                    {canManage && (
                        <div className="flex items-center gap-3 text-sm text-gray-400">
                            <ShieldCheck size={16} /> Admin access
                        </div>
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

                {revealedKey && (
                    <div className="mb-6 rounded-2xl border border-yellow-500/20 bg-yellow-500/10 p-4">
                        <div className="flex items-center justify-between gap-3 mb-3">
                            <p className="font-semibold text-yellow-200">New API key created</p>
                            <button onClick={() => setRevealedKey(null)} className="text-xs text-yellow-300/70 hover:text-yellow-200">Dismiss</button>
                        </div>
                        <div className="flex items-center gap-2">
                            <code className="flex-1 overflow-x-auto rounded-xl bg-black/30 px-3 py-2 text-sm font-mono text-yellow-100">{revealedKey}</code>
                            <button onClick={copyKey} className="rounded-xl border border-yellow-500/30 bg-yellow-500/20 px-3 py-2 text-yellow-100">
                                <Copy size={16} />
                            </button>
                        </div>
                    </div>
                )}

                {!canManage ? (
                    <section className="rounded-3xl border border-blue-500/20 bg-blue-500/10 p-6 text-blue-100">
                        <h2 className="text-xl font-bold mb-2">Admin access required</h2>
                        <p className="text-sm text-blue-100/80">
                            Webhooks, delivery logs, and API keys are restricted to organization admins because they expose outbound integrations and credential metadata.
                        </p>
                    </section>
                ) : (
                    <>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
                            <form onSubmit={createWebhook} className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-4">
                                <div className="flex items-center gap-3">
                                    <div className="rounded-xl bg-brand-500/10 p-2 text-brand-300"><Webhook size={20} /></div>
                                    <div>
                                        <h2 className="text-lg font-bold">Create Webhook</h2>
                                        <p className="text-sm text-gray-400">Send visitor and alert events to external systems.</p>
                                    </div>
                                </div>
                                <input
                                    value={newWebhook.url}
                                    onChange={(e) => setNewWebhook({ ...newWebhook, url: e.target.value })}
                                    className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                                    placeholder="https://example.com/webhooks/sentinelcv"
                                />
                                <input
                                    value={newWebhook.events}
                                    onChange={(e) => setNewWebhook({ ...newWebhook, events: e.target.value })}
                                    className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                                    placeholder="visitor.detected, visitor.identified"
                                />
                                <input
                                    value={newWebhook.secret}
                                    onChange={(e) => setNewWebhook({ ...newWebhook, secret: e.target.value })}
                                    className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                                    placeholder="Optional signing secret"
                                />
                                <button type="submit" className="inline-flex items-center gap-2 rounded-xl border border-brand-500/30 bg-brand-500/20 px-4 py-3 text-brand-100">
                                    <Plus size={16} /> Create webhook
                                </button>
                            </form>

                            <form onSubmit={createApiKey} className="rounded-3xl border border-white/10 bg-white/5 p-6 space-y-4">
                                <div className="flex items-center gap-3">
                                    <div className="rounded-xl bg-blue-500/10 p-2 text-blue-300"><KeyRound size={20} /></div>
                                    <div>
                                        <h2 className="text-lg font-bold">Create API Key</h2>
                                        <p className="text-sm text-gray-400">Generate credentials for external service access.</p>
                                    </div>
                                </div>
                                <input
                                    value={newApiKey.name}
                                    onChange={(e) => setNewApiKey({ ...newApiKey, name: e.target.value })}
                                    className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                                    placeholder="Integration name"
                                />
                                <input
                                    value={newApiKey.permissions}
                                    onChange={(e) => setNewApiKey({ ...newApiKey, permissions: e.target.value })}
                                    className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                                    placeholder="read, write"
                                />
                                <button type="submit" className="inline-flex items-center gap-2 rounded-xl border border-blue-500/30 bg-blue-500/20 px-4 py-3 text-blue-100">
                                    <Plus size={16} /> Create API key
                                </button>
                            </form>
                        </div>

                        <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_0.8fr] gap-6">
                            <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
                                <div className="flex items-center justify-between mb-5">
                                    <div>
                                        <h2 className="text-xl font-bold">Registered Webhooks</h2>
                                        <p className="text-sm text-gray-400">Delivery attempts use signed payloads when a secret is configured.</p>
                                    </div>
                                    <button onClick={() => { void fetchWebhooks() }} className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-gray-200">
                                        <RefreshCw size={14} /> Refresh
                                    </button>
                                </div>

                                <div className="space-y-4">
                                    {webhooks.length === 0 ? (
                                        <p className="text-sm text-gray-500">No webhooks have been configured yet.</p>
                                    ) : (
                                        webhooks.map((webhook) => (
                                            <div key={webhook.id} className="rounded-2xl border border-white/10 bg-black/30 p-4">
                                                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                                                    <div>
                                                        <p className="font-semibold">{webhook.url}</p>
                                                        <p className="text-xs text-gray-500 mt-1">{webhook.events?.length || 0} event types • {webhook.is_active ? 'active' : 'disabled'}</p>
                                                    </div>
                                                    <div className="flex flex-wrap gap-2">
                                                        <button onClick={() => fetchLogs(webhook.id)} className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-gray-200">View logs</button>
                                                        <button onClick={() => testWebhook(webhook.id)} className="rounded-xl border border-brand-500/30 bg-brand-500/20 px-3 py-2 text-xs text-brand-100 inline-flex items-center gap-1">
                                                            <Play size={12} /> Test
                                                        </button>
                                                        <button onClick={() => deleteWebhook(webhook.id)} className="rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200 inline-flex items-center gap-1">
                                                            <Trash2 size={12} /> Delete
                                                        </button>
                                                    </div>
                                                </div>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </section>

                            <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
                                <div className="flex items-center justify-between mb-5">
                                    <div>
                                        <h2 className="text-xl font-bold">API Keys</h2>
                                        <p className="text-sm text-gray-400">Display prefixes only; the full key is shown once at creation.</p>
                                    </div>
                                    <button onClick={() => { void fetchApiKeys() }} className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-gray-200">
                                        <RefreshCw size={14} /> Refresh
                                    </button>
                                </div>

                                <div className="space-y-4">
                                    {apiKeys.length === 0 ? (
                                        <p className="text-sm text-gray-500">No API keys exist yet.</p>
                                    ) : (
                                        apiKeys.map((apiKey) => (
                                            <div key={apiKey.id} className="rounded-2xl border border-white/10 bg-black/30 p-4">
                                                <div className="flex items-start justify-between gap-3">
                                                    <div>
                                                        <p className="font-semibold">{apiKey.name}</p>
                                                        <p className="text-xs text-gray-500 mt-1">Prefix {apiKey.key_prefix} • {apiKey.permissions?.join(', ') || 'read'}</p>
                                                    </div>
                                                    <button onClick={() => deleteApiKey(apiKey.id)} className="rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200 inline-flex items-center gap-1">
                                                        <Trash2 size={12} /> Revoke
                                                    </button>
                                                </div>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </section>
                        </div>

                        <section className="mt-6 rounded-3xl border border-white/10 bg-white/5 p-6">
                            <div className="flex items-center justify-between mb-4">
                                <div>
                                    <h2 className="text-xl font-bold">Webhook Logs</h2>
                                    <p className="text-sm text-gray-400">Recent delivery attempts for the selected webhook.</p>
                                </div>
                                {selectedWebhookId && <span className="text-xs text-gray-500">Webhook {selectedWebhookId}</span>}
                            </div>

                            {logLoading ? (
                                <p className="text-sm text-gray-500">Loading logs...</p>
                            ) : webhookLogs.length === 0 ? (
                                <p className="text-sm text-gray-500">Select a webhook and click View logs to inspect deliveries.</p>
                            ) : (
                                <div className="space-y-3">
                                    {webhookLogs.map((log) => (
                                        <div key={log.id} className="rounded-2xl border border-white/10 bg-black/30 p-4 flex items-center justify-between gap-4">
                                            <div>
                                                <p className="font-medium">{log.event}</p>
                                                <p className="text-xs text-gray-500 mt-1">Status {log.response_status ?? 'n/a'} • {new Date(log.created_at).toLocaleString()}</p>
                                            </div>
                                            <span className={`rounded-full px-3 py-1 text-xs border ${log.success ? 'border-green-500/20 bg-green-500/10 text-green-300' : 'border-red-500/20 bg-red-500/10 text-red-300'}`}>
                                                {log.success ? 'Delivered' : 'Failed'}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </section>
                    </>
                )}
            </main>

            <AnimatePresence>
                {message && (
                    <motion.div
                        initial={{ opacity: 0, y: 12 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 12 }}
                        className="fixed bottom-6 right-6 rounded-2xl border border-white/10 bg-black/80 px-4 py-3 text-sm backdrop-blur"
                    >
                        {message.text}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}

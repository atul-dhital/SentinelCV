'use client'

import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
    Save, Shield, Settings as SettingsIcon, AlertCircle, CheckCircle, Bell, Trash2, Clock,
    Webhook, Key, Plus, Eye, EyeOff, Copy, FileText, Download, UserX, RefreshCw
} from 'lucide-react'
import Navbar from '@/components/Navbar'
import { authService, orgService, Organization, webhookService, complianceService, alertService, type UserInfo } from '@/services/api'
import { useConfirm } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'
import { Switch } from '@/components/ui/Switch'

interface OrganizationStats {
    user_count: number
    visitor_count: number
    known_visitor_count: number
    total_logs: number
    identified_logs: number
    unidentified_logs: number
    embedding_count: number
    camera_count: number
}

interface WebhookItem {
    id: string
    url: string
    events: string[]
    is_active: boolean
    created_at: string
}

interface ApiKeyItem {
    id: string
    name: string
    key_prefix: string
    permissions: string[]
    is_active: boolean
    created_at: string
    last_used_at: string | null
}

interface RetentionPolicy {
    id: string
    entity_type: string
    retention_days: number
    auto_delete: boolean
    last_cleanup_at: string | null
    created_at: string
}

export default function SettingsPage() {
    const confirm = useConfirm()
    const toast = useToast()
    const [currentUser, setCurrentUser] = useState<UserInfo | null>(null)
    const [org, setOrg] = useState<Organization | null>(null)
    const [stats, setStats] = useState<OrganizationStats | null>(null)
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [activeSection, setActiveSection] = useState<'general' | 'webhooks' | 'api-keys' | 'retention' | 'gdpr' | 'alerts'>('general')

    // General settings form
    const emptyForm = { name: '', face_confidence_threshold: 0.6, log_retention_days: 90, notification_email: false, notification_unidentified: false, notification_email_address: '' }
    const [formData, setFormData] = useState(emptyForm)
    const [savedFormData, setSavedFormData] = useState(emptyForm)
    const isDirty = JSON.stringify(formData) !== JSON.stringify(savedFormData)

    // Webhooks state
    const [webhooks, setWebhooks] = useState<WebhookItem[]>([])
    const [showWebhookForm, setShowWebhookForm] = useState(false)
    const [webhookForm, setWebhookForm] = useState({ url: '', events: 'visitor.identified,visitor.unidentified', secret: '' })

    // API Keys state
    const [apiKeys, setApiKeys] = useState<ApiKeyItem[]>([])
    const [showApiKeyForm, setShowApiKeyForm] = useState(false)
    const [apiKeyForm, setApiKeyForm] = useState({ name: '', permissions: 'read' })
    const [newApiKey, setNewApiKey] = useState<string | null>(null)

    // Retention policies state
    const [retentionPolicies, setRetentionPolicies] = useState<RetentionPolicy[]>([])
    const [showRetentionForm, setShowRetentionForm] = useState(false)
    const [retentionForm, setRetentionForm] = useState({ entity_type: 'visitor_logs', retention_days: 90, auto_delete: false })
    const [cleanupRunning, setCleanupRunning] = useState(false)

    // GDPR state
    const [gdprVisitorId, setGdprVisitorId] = useState('')
    const [gdprLoading, setGdprLoading] = useState(false)

    // Alerts state
    const [alertConfig, setAlertConfig] = useState<any>(null)
    const [alertRules, setAlertRules] = useState<any[]>([])
    const [showAlertRuleForm, setShowAlertRuleForm] = useState(false)
    const [alertRuleForm, setAlertRuleForm] = useState({
        name: '',
        description: '',
        is_active: true,
        trigger_type: 'known',
        min_confidence: 0.5,
        action: 'email',
    })
    const canManage = currentUser?.role === 'admin'

    useEffect(() => {
        fetchData()
    }, [])

    useEffect(() => {
        if (!canManage) return
        if (activeSection === 'webhooks') fetchWebhooks()
        if (activeSection === 'api-keys') fetchApiKeys()
        if (activeSection === 'retention') fetchRetentionPolicies()
        if (activeSection === 'alerts') fetchAlerts()
    }, [activeSection, canManage])

    const fetchData = async () => {
        try {
            const [orgRes, statsRes, meRes] = await Promise.all([
                orgService.getMyOrg().catch(() => ({ data: { name: '', face_confidence_threshold: 0.6, log_retention_days: 90, notification_email: false, notification_unidentified: false } })),
                orgService.getStats().catch(() => ({ data: {} })),
                authService.me().catch(() => ({ data: null })),
            ])
            const orgData = orgRes.data as Organization
            setCurrentUser((meRes as { data: UserInfo | null }).data)
            setOrg(orgData)
            setStats(statsRes.data as any)
            const loaded = {
                name: orgData.name,
                face_confidence_threshold: orgData.face_confidence_threshold,
                log_retention_days: orgData.log_retention_days,
                notification_email: orgData.notification_email,
                notification_unidentified: orgData.notification_unidentified,
                notification_email_address: orgData.notification_email_address ?? '',
            }
            setFormData(loaded)
            setSavedFormData(loaded)
        } catch (err: any) {
            if (err.response?.status === 401) {
                window.location.href = '/login'
                return
            }
            console.error('Failed to fetch organization data:', err)
        } finally {
            setLoading(false)
        }
    }

    const handleSubmit = async (e?: React.FormEvent) => {
        e?.preventDefault()
        if (!canManage) return
        setSaving(true)
        try {
            await orgService.updateMyOrg(formData)
            setSavedFormData(formData)
            toast.success('Settings saved')
            fetchData()
        } catch {
            toast.error('Failed to save settings')
        } finally {
            setSaving(false)
        }
    }

    const handleDiscard = () => setFormData(savedFormData)

    // Webhook handlers
    const fetchWebhooks = async () => {
        try {
            const res = await webhookService.list()
            setWebhooks(res.data.items || res.data || [])
        } catch { /* ignore */ }
    }

    const createWebhook = async () => {
        if (!canManage) return
        try {
            await webhookService.create({
                url: webhookForm.url,
                events: webhookForm.events.split(',').map(e => e.trim()),
                secret: webhookForm.secret || undefined,
            })
            setMessage({ type: 'success', text: 'Webhook created!' })
            setShowWebhookForm(false)
            setWebhookForm({ url: '', events: 'visitor.identified,visitor.unidentified', secret: '' })
            fetchWebhooks()
        } catch {
            setMessage({ type: 'error', text: 'Failed to create webhook' })
        }
    }

    const deleteWebhook = async (id: string) => {
        if (!canManage) return
        const target = webhooks.find(w => w.id === id)
        const ok = await confirm({
            kind: 'danger',
            title: target ? `Delete webhook for ${target.url}?` : 'Delete webhook?',
            description: 'The endpoint will stop receiving events immediately.',
            confirmLabel: 'Delete webhook',
        })
        if (!ok) return
        try {
            await webhookService.delete(id)
            toast.success('Webhook deleted')
            fetchWebhooks()
        } catch {
            toast.error('Failed to delete webhook')
        }
    }

    const testWebhook = async (id: string) => {
        if (!canManage) return
        try {
            await webhookService.test(id)
            setMessage({ type: 'success', text: 'Test webhook sent!' })
        } catch {
            setMessage({ type: 'error', text: 'Webhook test failed' })
        }
    }

    // API Key handlers
    const fetchApiKeys = async () => {
        try {
            const res = await webhookService.listApiKeys()
            setApiKeys(res.data.items || res.data || [])
        } catch { /* ignore */ }
    }

    const createApiKey = async () => {
        if (!canManage) return
        try {
            const res = await webhookService.createApiKey({
                name: apiKeyForm.name,
                permissions: apiKeyForm.permissions.split(',').map(p => p.trim()),
            })
            setNewApiKey(res.data.full_key || null)
            setMessage({ type: 'success', text: 'API key created! Copy it now - it won\'t be shown again.' })
            setShowApiKeyForm(false)
            setApiKeyForm({ name: '', permissions: 'read' })
            fetchApiKeys()
        } catch {
            setMessage({ type: 'error', text: 'Failed to create API key' })
        }
    }

    const deleteApiKey = async (id: string) => {
        if (!canManage) return
        const target = apiKeys.find(k => k.id === id)
        const ok = await confirm({
            kind: 'danger',
            title: target ? `Revoke API key "${target.name}"?` : 'Revoke API key?',
            description: 'Any client using this key will immediately fail to authenticate. This cannot be undone.',
            confirmLabel: 'Revoke key',
        })
        if (!ok) return
        try {
            await webhookService.deleteApiKey(id)
            toast.success('API key revoked')
            fetchApiKeys()
        } catch {
            toast.error('Failed to delete API key')
        }
    }

    // Retention handlers
    const fetchRetentionPolicies = async () => {
        try {
            const res = await complianceService.getRetentionPolicies()
            setRetentionPolicies(res.data)
        } catch { /* ignore */ }
    }

    const createRetentionPolicy = async () => {
        if (!canManage) return
        try {
            await complianceService.createRetentionPolicy(retentionForm)
            setMessage({ type: 'success', text: 'Retention policy created!' })
            setShowRetentionForm(false)
            setRetentionForm({ entity_type: 'visitor_logs', retention_days: 90, auto_delete: false })
            fetchRetentionPolicies()
        } catch {
            setMessage({ type: 'error', text: 'Failed to create retention policy' })
        }
    }

    const runCleanup = async () => {
        if (!canManage) return
        setCleanupRunning(true)
        try {
            const res = await complianceService.runRetentionCleanup()
            const deletedCount = (res.data || []).reduce((total, item) => total + (item.records_deleted || 0), 0)
            setMessage({ type: 'success', text: `Cleanup complete: ${deletedCount} records removed` })
        } catch {
            setMessage({ type: 'error', text: 'Failed to run cleanup' })
        } finally {
            setCleanupRunning(false)
        }
    }

    // GDPR handlers
    const handleGdprExport = async () => {
        if (!canManage || !gdprVisitorId.trim()) return
        setGdprLoading(true)
        try {
            const res = await complianceService.gdprExport(gdprVisitorId.trim())
            const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `gdpr-export-${gdprVisitorId}.json`
            a.click()
            URL.revokeObjectURL(url)
            setMessage({ type: 'success', text: 'GDPR data exported!' })
        } catch {
            setMessage({ type: 'error', text: 'Failed to export visitor data' })
        } finally {
            setGdprLoading(false)
        }
    }

    const handleGdprDelete = async () => {
        if (!canManage || !gdprVisitorId.trim()) return
        const ok = await confirm({
            kind: 'danger',
            title: 'Permanently delete visitor data?',
            description: 'This removes ALL data for this visitor — face embeddings, detection logs, uploaded media. The action is GDPR-compliant right-to-erasure and cannot be undone.',
            confirmLabel: 'Delete all data',
            confirmPhrase: 'DELETE',
        })
        if (!ok) return
        setGdprLoading(true)
        try {
            await complianceService.gdprDelete(gdprVisitorId.trim())
            setMessage({ type: 'success', text: 'Visitor data permanently deleted (GDPR right to erasure)' })
            setGdprVisitorId('')
        } catch {
            setMessage({ type: 'error', text: 'Failed to delete visitor data' })
        } finally {
            setGdprLoading(false)
        }
    }

    // Alert handlers
    const fetchAlerts = async () => {
        try {
            const [configRes, rulesRes] = await Promise.all([
                alertService.getConfig().catch(() => ({ data: {} })),
                alertService.getRules().catch(() => ({ data: [] })),
            ])
            setAlertConfig(configRes.data)
            const rules = rulesRes.data
            setAlertRules(Array.isArray(rules) ? rules : (rules as any).items || [])
        } catch { /* ignore */ }
    }

    const updateAlertConfig = async (updates: any) => {
        if (!canManage) return
        try {
            const res = await alertService.updateConfig(updates)
            setAlertConfig(res.data)
            setMessage({ type: 'success', text: 'Alert settings saved!' })
        } catch {
            setMessage({ type: 'error', text: 'Failed to update alert settings' })
        }
    }

    const createAlertRule = async () => {
        if (!canManage) return
        try {
            await alertService.createRule(alertRuleForm)
            setMessage({ type: 'success', text: 'Alert rule created!' })
            setShowAlertRuleForm(false)
            setAlertRuleForm({
                name: '',
                description: '',
                is_active: true,
                trigger_type: 'known',
                min_confidence: 0.5,
                action: 'email',
            })
            await fetchAlerts()
        } catch {
            setMessage({ type: 'error', text: 'Failed to create alert rule' })
        }
    }

    const deleteAlertRule = async (ruleId: string) => {
        if (!canManage) return
        const target = alertRules.find((r: any) => r.id === ruleId)
        const ok = await confirm({
            kind: 'danger',
            title: target ? `Delete alert rule "${target.name}"?` : 'Delete alert rule?',
            description: 'Notifications for this rule will stop immediately.',
            confirmLabel: 'Delete rule',
        })
        if (!ok) return
        try {
            await alertService.deleteRule(ruleId)
            toast.success('Alert rule deleted')
            await fetchAlerts()
        } catch {
            toast.error('Failed to delete alert rule')
        }
    }

    if (loading) {
        return (
            <div className="min-h-screen">
                <Navbar />
                <main className="pt-24 pb-20 px-6 container mx-auto">
                    <div className="animate-pulse space-y-4">
                        <div className="h-8 bg-gray-800 rounded w-48"></div>
                        <div className="h-64 bg-gray-800 rounded"></div>
                    </div>
                </main>
            </div>
        )
    }

    const sections = canManage
        ? [
            { key: 'general' as const, label: 'General', icon: SettingsIcon },
            { key: 'alerts' as const, label: 'Alerts', icon: Bell },
            { key: 'webhooks' as const, label: 'Webhooks', icon: Webhook },
            { key: 'api-keys' as const, label: 'API Keys', icon: Key },
            { key: 'retention' as const, label: 'Retention', icon: Clock },
            { key: 'gdpr' as const, label: 'GDPR', icon: Shield },
        ]
        : [
            { key: 'general' as const, label: 'General', icon: SettingsIcon },
        ]

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-20 px-6 container mx-auto">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                >
                    <h1 className="text-4xl font-extrabold mb-3 bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
                        Settings
                    </h1>
                    <p className="text-gray-400 text-lg mb-6">Manage your organization settings, integrations, and compliance.</p>

                    {currentUser && !canManage && (
                        <div className="mb-6 rounded-lg border border-blue-500/20 bg-blue-500/10 p-4 text-blue-200">
                            Your role is read-only on this page. Contact an organization admin to change settings, integrations, or compliance policies.
                        </div>
                    )}

                    {message && (
                        <div className={`mb-6 p-4 rounded-lg flex items-center gap-3 ${message.type === 'success'
                                ? 'bg-green-500/10 text-green-400 border border-green-500/20'
                                : 'bg-red-500/10 text-red-400 border border-red-500/20'
                            }`}>
                            {message.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
                            {message.text}
                        </div>
                    )}

                    {/* New API key banner */}
                    {newApiKey && (
                        <div className="mb-6 p-4 rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-yellow-400">
                            <p className="font-bold mb-2">New API Key Created - Copy it now!</p>
                            <div className="flex items-center gap-2">
                                <code className="flex-1 bg-gray-900 px-3 py-2 rounded text-sm font-mono">{newApiKey}</code>
                                <button onClick={() => { navigator.clipboard.writeText(newApiKey); setMessage({ type: 'success', text: 'Copied!' }) }}
                                    className="p-2 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"><Copy size={16} /></button>
                            </div>
                            <button onClick={() => setNewApiKey(null)} className="text-xs mt-2 text-gray-500 hover:text-gray-300">Dismiss</button>
                        </div>
                    )}

                    {/* Section Tabs */}
                    <div className="flex gap-2 mb-8 overflow-x-auto pb-2">
                        {sections.map(s => (
                            <button
                                key={s.key}
                                onClick={() => setActiveSection(s.key)}
                                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors whitespace-nowrap ${activeSection === s.key
                                    ? 'bg-brand-600/20 text-brand-500'
                                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                                    }`}
                            >
                                <s.icon size={16} />
                                {s.label}
                            </button>
                        ))}
                    </div>

                    {/* General Settings */}
                    {activeSection === 'general' && (
                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                            <div className="lg:col-span-2 space-y-6">
                                <form onSubmit={(e) => { e.preventDefault(); void handleSubmit() }} className="glass-card p-6 space-y-6" id="general-settings-form">
                                    <div className="flex items-center gap-3 mb-2">
                                        <div className="p-2 bg-brand-500/10 rounded-lg"><SettingsIcon className="text-brand-500" size={24} /></div>
                                        <h2 className="text-xl font-bold">Organization Settings</h2>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">Organization Name</label>
                                        <input type="text" value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                            disabled={!canManage}
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-60" required />
                                    </div>
                                    <div id="confidence-threshold">
                                        <label className="block text-sm font-medium text-gray-300 mb-2">
                                            Face Recognition Confidence Threshold
                                            <span className="text-gray-500 ml-2">({(formData.face_confidence_threshold * 100).toFixed(0)}%)</span>
                                        </label>
                                        <input type="range" min="0.5" max="0.95" step="0.05" value={formData.face_confidence_threshold}
                                            disabled={!canManage}
                                            onChange={(e) => setFormData({ ...formData, face_confidence_threshold: parseFloat(e.target.value) })}
                                            className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-brand-500 disabled:cursor-not-allowed disabled:opacity-60" />
                                        <div className="flex justify-between text-xs text-gray-500 mt-1">
                                            <span>More permissive (50%)</span><span>Strict (95%)</span>
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2 flex items-center gap-2"><Clock size={16} /> Log Retention (Days)</label>
                                        <input type="number" min="7" max="365" value={formData.log_retention_days}
                                            disabled={!canManage}
                                            onChange={(e) => setFormData({ ...formData, log_retention_days: parseInt(e.target.value) || 90 })}
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-60" />
                                    </div>
                                </form>

                                <div className="glass-card p-6 space-y-4">
                                    <div className="flex items-center gap-3 mb-2">
                                        <div className="p-2 bg-blue-500/10 rounded-lg"><Bell className="text-blue-400" size={24} /></div>
                                        <h2 className="text-xl font-bold">Notifications</h2>
                                    </div>
                                    <div className="flex items-center justify-between p-4 bg-gray-900/30 rounded-lg hover:bg-gray-900/50 transition-colors">
                                        <div><p className="font-medium text-gray-200">Email Notifications</p><p className="text-sm text-gray-500">Receive email alerts for important events.</p></div>
                                        <Switch checked={formData.notification_email} onCheckedChange={(next) => setFormData({ ...formData, notification_email: next })} disabled={!canManage} label="Email notifications" />
                                    </div>
                                    <div className="flex items-center justify-between p-4 bg-gray-900/30 rounded-lg hover:bg-gray-900/50 transition-colors">
                                        <div><p className="font-medium text-gray-200">Unidentified Visitor Alerts</p><p className="text-sm text-gray-500">Get notified when unknown visitors are detected.</p></div>
                                        <Switch checked={formData.notification_unidentified} onCheckedChange={(next) => setFormData({ ...formData, notification_unidentified: next })} disabled={!canManage} label="Unidentified visitor alerts" />
                                    </div>
                                    <div className="p-4 bg-gray-900/30 rounded-lg space-y-2">
                                        <p className="font-medium text-gray-200">Alert Notification Address</p>
                                        <p className="text-sm text-gray-500">
                                            Optional email for alert notifications. Leave blank to send to all admin users.
                                        </p>
                                        <input
                                            type="email"
                                            value={formData.notification_email_address}
                                            onChange={(e) => setFormData({ ...formData, notification_email_address: e.target.value })}
                                            disabled={!canManage}
                                            placeholder="alerts@your-org.com"
                                            className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-brand-500/40 disabled:opacity-50"
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="space-y-6">
                                <div className="glass-card p-6">
                                    <h3 className="font-bold mb-4 text-gray-300">Organization Statistics</h3>
                                    <div className="space-y-4">
                                        {[
                                            { label: 'Users', value: stats?.user_count || 0 },
                                            { label: 'Total Visitors', value: stats?.visitor_count || 0 },
                                            { label: 'Known Visitors', value: stats?.known_visitor_count || 0 },
                                            { label: 'Cameras', value: stats?.camera_count || 0 },
                                            { label: 'Face Embeddings', value: stats?.embedding_count || 0 },
                                        ].map(s => (
                                            <div key={s.label} className="flex justify-between items-center">
                                                <span className="text-gray-400">{s.label}</span>
                                                <span className="font-semibold">{s.value}</span>
                                            </div>
                                        ))}
                                        <div className="border-t border-gray-700 pt-4 flex justify-between items-center">
                                            <span className="text-gray-400">Total Logs</span>
                                            <span className="font-semibold">{stats?.total_logs || 0}</span>
                                        </div>
                                    </div>
                                </div>

                                <div className="glass-card p-6">
                                    <div className="flex items-center gap-3 mb-4">
                                        <div className="p-2 bg-purple-500/10 rounded-lg"><Shield className="text-purple-400" size={24} /></div>
                                        <h2 className="text-lg font-bold">Credential Access</h2>
                                    </div>
                                    <p className="text-sm text-gray-400">
                                        Organization credentials are not displayed here. Admins can issue scoped API keys from the API Keys section, and full secrets are only shown once at creation time.
                                    </p>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Alerts Configuration Section */}
                    {activeSection === 'alerts' && (
                        <div className="space-y-6">
                            <div className="flex items-center justify-between">
                                <h2 className="text-xl font-bold flex items-center gap-2"><Bell size={20} className="text-brand-500" /> Alert Configuration</h2>
                                <button onClick={() => setShowAlertRuleForm(!showAlertRuleForm)}
                                    className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
                                    <Plus size={16} /> Create Rule
                                </button>
                            </div>

                            <div className="glass-card p-6 space-y-6">
                                <div>
                                    <h3 className="font-semibold text-lg mb-4 text-gray-200">Global Alert Settings</h3>
                                    <div className="space-y-4">
                                        <div className="flex items-center justify-between p-4 bg-gray-900/30 rounded-lg hover:bg-gray-900/50 transition-colors">
                                            <div><p className="font-medium text-gray-200">Alerts Enabled</p><p className="text-sm text-gray-500">Turn on/off all alerts for your organization</p></div>
                                            <Switch
                                                checked={alertConfig?.alerts_enabled || false}
                                                onCheckedChange={(next) => updateAlertConfig({ alerts_enabled: next })}
                                                label="Alerts enabled"
                                            />
                                        </div>
                                        <div className="flex items-center justify-between p-4 bg-gray-900/30 rounded-lg hover:bg-gray-900/50 transition-colors">
                                            <div><p className="font-medium text-gray-200">Email Alerts</p><p className="text-sm text-gray-500">Send email notifications when alerts trigger</p></div>
                                            <Switch
                                                checked={alertConfig?.email_alerts_enabled || false}
                                                onCheckedChange={(next) => updateAlertConfig({ email_alerts_enabled: next })}
                                                label="Email alerts"
                                            />
                                        </div>
                                        <div className="flex items-center justify-between p-4 bg-gray-900/30 rounded-lg hover:bg-gray-900/50 transition-colors">
                                            <div><p className="font-medium text-gray-200">Webhook Alerts</p><p className="text-sm text-gray-500">Send webhook notifications when alerts trigger</p></div>
                                            <Switch
                                                checked={alertConfig?.webhook_alerts_enabled || false}
                                                onCheckedChange={(next) => updateAlertConfig({ webhook_alerts_enabled: next })}
                                                label="Webhook alerts"
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-sm font-medium text-gray-300 mb-2">Minimum Confidence Threshold</label>
                                            <div className="flex items-center gap-3">
                                                <input type="range" min="0.4" max="0.95" step="0.05"
                                                    value={alertConfig?.min_confidence_threshold || 0.5}
                                                    onChange={(e) => updateAlertConfig({ min_confidence_threshold: parseFloat(e.target.value) })}
                                                    className="flex-1 h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-brand-500" />
                                                <span className="text-sm font-semibold text-gray-300 min-w-[3rem]">
                                                    {((alertConfig?.min_confidence_threshold || 0.5) * 100).toFixed(0)}%
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {showAlertRuleForm && (
                                <div className="glass-card p-6 space-y-4">
                                    <h3 className="font-semibold mb-3">Create Alert Rule</h3>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">Rule Name</label>
                                        <input type="text" value={alertRuleForm.name} onChange={(e) => setAlertRuleForm({ ...alertRuleForm, name: e.target.value })}
                                            placeholder="e.g. Known Visitor Detection Alert"
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 outline-none" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">Description</label>
                                        <input type="text" value={alertRuleForm.description} onChange={(e) => setAlertRuleForm({ ...alertRuleForm, description: e.target.value })}
                                            placeholder="What does this rule do?"
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 outline-none" />
                                    </div>
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-sm font-medium text-gray-300 mb-2">Trigger Type</label>
                                            <select value={alertRuleForm.trigger_type} onChange={(e) => setAlertRuleForm({ ...alertRuleForm, trigger_type: e.target.value })}
                                                className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 outline-none">
                                                <option value="known">Known Visitor</option>
                                                <option value="unknown">Unknown Visitor</option>
                                                <option value="liveness_fail">Liveness Failed</option>
                                                <option value="anomaly">Anomaly Detected</option>
                                            </select>
                                        </div>
                                        <div>
                                            <label className="block text-sm font-medium text-gray-300 mb-2">Action</label>
                                            <select value={alertRuleForm.action} onChange={(e) => setAlertRuleForm({ ...alertRuleForm, action: e.target.value })}
                                                className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 outline-none">
                                                <option value="email">Email</option>
                                                <option value="webhook">Webhook</option>
                                                <option value="both">Both</option>
                                                <option value="notify">Notify Only</option>
                                                <option value="silence">Silence</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">Min Confidence</label>
                                        <input type="number" min="0" max="1" step="0.1" value={alertRuleForm.min_confidence}
                                            onChange={(e) => setAlertRuleForm({ ...alertRuleForm, min_confidence: parseFloat(e.target.value) })}
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 outline-none" />
                                        <p className="text-xs text-gray-500 mt-1">Only alert if confidence &gt;= this value</p>
                                    </div>
                                    <div>
                                        <div className="flex items-center gap-3 p-3 bg-gray-900/30 rounded-lg">
                                            <Switch
                                                checked={alertRuleForm.is_active}
                                                onCheckedChange={(next) => setAlertRuleForm({ ...alertRuleForm, is_active: next })}
                                                label="Activate alert rule"
                                            />
                                            <span className="text-sm font-medium text-gray-300">Active</span>
                                        </div>
                                    </div>
                                    <div className="flex gap-2 pt-4">
                                        <button onClick={createAlertRule} className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
                                            Create Rule
                                        </button>
                                        <button onClick={() => setShowAlertRuleForm(false)} className="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">
                                            Cancel
                                        </button>
                                    </div>
                                </div>
                            )}

                            <div>
                                <h3 className="font-semibold mb-4 text-gray-200">Alert Rules ({alertRules.length})</h3>
                                {alertRules.length === 0 ? (
                                    <div className="glass-card p-12 text-center">
                                        <Bell size={40} className="text-gray-600 mx-auto mb-3" />
                                        <p className="text-gray-400">No alert rules created yet.</p>
                                        <p className="text-sm text-gray-500 mt-1">Create a rule to start receiving alerts.</p>
                                    </div>
                                ) : (
                                    <div className="space-y-3">
                                        {alertRules.map(rule => (
                                            <div key={rule.id} className="glass-card p-4">
                                                <div className="flex items-start justify-between mb-2">
                                                    <div className="flex-1">
                                                        <div className="flex items-center gap-2">
                                                            <p className="font-medium text-gray-200">{rule.name}</p>
                                                            <span className={`text-xs px-2 py-1 rounded ${rule.is_active
                                                                ? 'bg-green-500/10 text-green-400'
                                                                : 'bg-gray-700/50 text-gray-400'}`}>
                                                                {rule.is_active ? 'Active' : 'Inactive'}
                                                            </span>
                                                            <span className="text-xs bg-brand-600/10 text-brand-400 px-2 py-1 rounded">
                                                                {rule.trigger_type}
                                                            </span>
                                                        </div>
                                                        {rule.description && (
                                                            <p className="text-xs text-gray-500 mt-1">{rule.description}</p>
                                                        )}
                                                        <div className="flex gap-3 mt-2 text-xs text-gray-400">
                                                            <span>Min Confidence: {(rule.min_confidence * 100).toFixed(0)}%</span>
                                                            <span>Action: {rule.action}</span>
                                                        </div>
                                                    </div>
                                                    <button onClick={() => deleteAlertRule(rule.id)}
                                                        className="p-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg transition-colors"
                                                        title="Delete rule">
                                                        <Trash2 size={14} />
                                                    </button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Webhooks Section */}
                    {activeSection === 'webhooks' && (
                        <div className="space-y-6">
                            <div className="flex items-center justify-between">
                                <h2 className="text-xl font-bold flex items-center gap-2"><Webhook size={20} className="text-brand-500" /> Webhooks</h2>
                                <button onClick={() => setShowWebhookForm(!showWebhookForm)}
                                    className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
                                    <Plus size={16} /> Add Webhook
                                </button>
                            </div>

                            {showWebhookForm && (
                                <div className="glass-card p-6 space-y-4">
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">Webhook URL</label>
                                        <input type="url" value={webhookForm.url} onChange={(e) => setWebhookForm({ ...webhookForm, url: e.target.value })}
                                            placeholder="https://your-server.com/webhook"
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">Events (comma-separated)</label>
                                        <input type="text" value={webhookForm.events} onChange={(e) => setWebhookForm({ ...webhookForm, events: e.target.value })}
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors" />
                                        <p className="text-xs text-gray-500 mt-1">Available: visitor.identified, visitor.unidentified, alert.created, processing.complete</p>
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">Secret (optional)</label>
                                        <input type="password" value={webhookForm.secret} onChange={(e) => setWebhookForm({ ...webhookForm, secret: e.target.value })}
                                            placeholder="Optional signing secret"
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors" />
                                    </div>
                                    <div className="flex gap-2">
                                        <button onClick={createWebhook} className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Create</button>
                                        <button onClick={() => setShowWebhookForm(false)} className="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Cancel</button>
                                    </div>
                                </div>
                            )}

                            {webhooks.length === 0 ? (
                                <div className="glass-card p-12 text-center">
                                    <Webhook size={40} className="text-gray-600 mx-auto mb-3" />
                                    <p className="text-gray-400">No webhooks configured yet.</p>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {webhooks.map(wh => (
                                        <div key={wh.id} className="glass-card p-4 flex items-center justify-between">
                                            <div className="flex-1 min-w-0">
                                                <p className="font-medium truncate">{wh.url}</p>
                                                <div className="flex items-center gap-2 mt-1">
                                                    <span className={`text-xs px-2 py-0.5 rounded ${wh.is_active ? 'bg-green-400/10 text-green-400' : 'bg-red-400/10 text-red-400'}`}>
                                                        {wh.is_active ? 'Active' : 'Inactive'}
                                                    </span>
                                                    {wh.events.map(ev => (
                                                        <span key={ev} className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded">{ev}</span>
                                                    ))}
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-2 ml-4">
                                                <button onClick={() => testWebhook(wh.id)} className="p-2 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 rounded-lg transition-colors" title="Test">
                                                    <RefreshCw size={14} />
                                                </button>
                                                <button onClick={() => deleteWebhook(wh.id)} className="p-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg transition-colors" title="Delete">
                                                    <Trash2 size={14} />
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* API Keys Section */}
                    {activeSection === 'api-keys' && (
                        <div className="space-y-6">
                            <div className="flex items-center justify-between">
                                <h2 className="text-xl font-bold flex items-center gap-2"><Key size={20} className="text-brand-500" /> API Keys</h2>
                                <button onClick={() => setShowApiKeyForm(!showApiKeyForm)}
                                    className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
                                    <Plus size={16} /> Create API Key
                                </button>
                            </div>

                            {showApiKeyForm && (
                                <div className="glass-card p-6 space-y-4">
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">Key Name</label>
                                        <input type="text" value={apiKeyForm.name} onChange={(e) => setApiKeyForm({ ...apiKeyForm, name: e.target.value })}
                                            placeholder="e.g. Production Integration"
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors" />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">Permissions (comma-separated)</label>
                                        <input type="text" value={apiKeyForm.permissions} onChange={(e) => setApiKeyForm({ ...apiKeyForm, permissions: e.target.value })}
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors" />
                                        <p className="text-xs text-gray-500 mt-1">Available: read, write, admin</p>
                                    </div>
                                    <div className="flex gap-2">
                                        <button onClick={createApiKey} className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Create</button>
                                        <button onClick={() => setShowApiKeyForm(false)} className="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Cancel</button>
                                    </div>
                                </div>
                            )}

                            {apiKeys.length === 0 ? (
                                <div className="glass-card p-12 text-center">
                                    <Key size={40} className="text-gray-600 mx-auto mb-3" />
                                    <p className="text-gray-400">No API keys created yet.</p>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {apiKeys.map(key => (
                                        <div key={key.id} className="glass-card p-4 flex items-center justify-between">
                                            <div className="flex-1 min-w-0">
                                                <p className="font-medium">{key.name}</p>
                                                <div className="flex items-center gap-2 mt-1">
                                                    <code className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded font-mono">{key.key_prefix}...</code>
                                                    {key.permissions.map(p => (
                                                        <span key={p} className="text-xs bg-brand-600/10 text-brand-400 px-2 py-0.5 rounded">{p}</span>
                                                    ))}
                                                    {key.last_used_at && (
                                                        <span className="text-xs text-gray-500">Last used: {new Date(key.last_used_at).toLocaleDateString()}</span>
                                                    )}
                                                </div>
                                            </div>
                                            <button onClick={() => deleteApiKey(key.id)} className="p-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg transition-colors ml-4" title="Delete">
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Retention Policies Section */}
                    {activeSection === 'retention' && (
                        <div className="space-y-6">
                            <div className="flex items-center justify-between">
                                <h2 className="text-xl font-bold flex items-center gap-2"><Clock size={20} className="text-brand-500" /> Data Retention Policies</h2>
                                <div className="flex gap-2">
                                    <button onClick={runCleanup} disabled={cleanupRunning}
                                        className="bg-yellow-500/10 hover:bg-yellow-500/20 text-yellow-400 px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 disabled:opacity-50">
                                        <RefreshCw size={16} className={cleanupRunning ? 'animate-spin' : ''} />
                                        {cleanupRunning ? 'Running...' : 'Run Cleanup'}
                                    </button>
                                    <button onClick={() => setShowRetentionForm(!showRetentionForm)}
                                        className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
                                        <Plus size={16} /> Add Policy
                                    </button>
                                </div>
                            </div>

                            {showRetentionForm && (
                                <div className="glass-card p-6 space-y-4">
                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        <div>
                                            <label className="block text-sm font-medium text-gray-300 mb-2">Entity Type</label>
                                            <select value={retentionForm.entity_type} onChange={(e) => setRetentionForm({ ...retentionForm, entity_type: e.target.value })}
                                                className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 outline-none">
                                                <option value="visitor_logs">Visitor Logs</option>
                                                <option value="face_data">Face Data</option>
                                                <option value="audit_logs">Audit Logs</option>
                                            </select>
                                        </div>
                                        <div>
                                            <label className="block text-sm font-medium text-gray-300 mb-2">Retention (Days)</label>
                                            <input type="number" min="1" max="3650" value={retentionForm.retention_days}
                                                onChange={(e) => setRetentionForm({ ...retentionForm, retention_days: parseInt(e.target.value) || 90 })}
                                                className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 outline-none" />
                                        </div>
                                        <div>
                                            <label className="block text-sm font-medium text-gray-300 mb-2">Cleanup Mode</label>
                                            <div className="flex items-center justify-between rounded-lg border border-gray-700 bg-gray-900/30 px-4 py-3">
                                                <div>
                                                    <p className="text-sm font-medium text-gray-200">Automatic deletion</p>
                                                    <p className="text-xs text-gray-500">When enabled, cleanup jobs will delete expired records automatically.</p>
                                                </div>
                                                <Switch
                                                    checked={retentionForm.auto_delete}
                                                    onCheckedChange={(next) => setRetentionForm({ ...retentionForm, auto_delete: next })}
                                                    label="Automatic deletion"
                                                />
                                            </div>
                                        </div>
                                    </div>
                                    <div className="flex gap-2">
                                        <button onClick={createRetentionPolicy} className="bg-brand-600 hover:bg-brand-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Create</button>
                                        <button onClick={() => setShowRetentionForm(false)} className="bg-gray-800 hover:bg-gray-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors">Cancel</button>
                                    </div>
                                </div>
                            )}

                            {retentionPolicies.length === 0 ? (
                                <div className="glass-card p-12 text-center">
                                    <Clock size={40} className="text-gray-600 mx-auto mb-3" />
                                    <p className="text-gray-400">No retention policies configured yet.</p>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {retentionPolicies.map(policy => (
                                        <div key={policy.id} className="glass-card p-4 flex items-center justify-between">
                                            <div>
                                                <p className="font-medium">{policy.entity_type.replace(/_/g, ' ')}</p>
                                                <div className="flex items-center gap-2 mt-1">
                                                    <span className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded">{policy.retention_days} days</span>
                                                    <span className={`text-xs px-2 py-0.5 rounded ${policy.auto_delete ? 'bg-green-400/10 text-green-400' : 'bg-yellow-500/10 text-yellow-300'}`}>
                                                        {policy.auto_delete ? 'Auto delete' : 'Manual review'}
                                                    </span>
                                                    {policy.last_cleanup_at && (
                                                        <span className="text-xs text-gray-500">Last cleanup: {new Date(policy.last_cleanup_at).toLocaleDateString()}</span>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* GDPR Section */}
                    {activeSection === 'gdpr' && (
                        <div className="space-y-6">
                            <div className="glass-card p-6">
                                <div className="flex items-center gap-3 mb-6">
                                    <div className="p-2 bg-brand-500/10 rounded-lg"><Shield className="text-brand-500" size={24} /></div>
                                    <div>
                                        <h2 className="text-xl font-bold">GDPR Compliance Tools</h2>
                                        <p className="text-sm text-gray-400">Right to access and right to erasure</p>
                                    </div>
                                </div>

                                <div className="space-y-4">
                                    <div>
                                        <label className="block text-sm font-medium text-gray-300 mb-2">Visitor ID</label>
                                        <input type="text" value={gdprVisitorId} onChange={(e) => setGdprVisitorId(e.target.value)}
                                            placeholder="Enter visitor UUID"
                                            className="w-full bg-gray-900/50 border border-gray-700 rounded-lg px-4 py-3 text-white focus:border-brand-500 focus:ring-1 focus:ring-brand-500 outline-none transition-colors" />
                                    </div>

                                    <div className="flex gap-3">
                                        <button onClick={handleGdprExport} disabled={gdprLoading || !gdprVisitorId.trim()}
                                            className="bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 px-4 py-3 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 disabled:opacity-50">
                                            <Download size={16} /> Export Data (Right to Access)
                                        </button>
                                        <button onClick={handleGdprDelete} disabled={gdprLoading || !gdprVisitorId.trim()}
                                            className="bg-red-500/10 hover:bg-red-500/20 text-red-400 px-4 py-3 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 disabled:opacity-50">
                                            <UserX size={16} /> Delete All Data (Right to Erasure)
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <div className="glass-card p-6">
                                <h3 className="font-bold mb-4 text-gray-300">Encryption Verification</h3>
                                <p className="text-sm text-gray-400 mb-4">Verify that all face embeddings are properly encrypted at rest.</p>
                                <button onClick={async () => {
                                    try {
                                        const res = await complianceService.verifyEncryption()
                                        setMessage({ type: 'success', text: `Encryption check: ${res.data.encrypted_count || 0} encrypted, ${res.data.unencrypted_count || 0} unencrypted` })
                                    } catch {
                                        setMessage({ type: 'error', text: 'Encryption verification failed' })
                                    }
                                }} className="bg-green-500/10 hover:bg-green-500/20 text-green-400 px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2">
                                    <Shield size={16} /> Verify Encryption
                                </button>
                            </div>
                        </div>
                    )}
                </motion.div>
            </main>

            {/* Sticky save footer — appears only when General settings have unsaved changes */}
            {canManage && isDirty && activeSection === 'general' && (
                <div className="fixed bottom-0 inset-x-0 z-40 border-t border-white/10 bg-[#0a0a0f]/90 backdrop-blur-xl px-6 py-4">
                    <div className="container mx-auto flex items-center justify-between gap-4">
                        <p className="text-sm text-gray-400">You have unsaved changes.</p>
                        <div className="flex items-center gap-3">
                            <button
                                type="button"
                                onClick={handleDiscard}
                                disabled={saving}
                                className="px-4 py-2 rounded-lg text-sm font-medium text-gray-300 hover:text-white hover:bg-white/10 transition-colors disabled:opacity-50"
                            >
                                Discard
                            </button>
                            <button
                                type="submit"
                                form="general-settings-form"
                                disabled={saving}
                                className="inline-flex items-center gap-2 rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 disabled:cursor-not-allowed px-5 py-2 text-sm font-semibold text-white transition-colors"
                            >
                                <Save size={15} />
                                {saving ? 'Saving…' : 'Save changes'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

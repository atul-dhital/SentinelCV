'use client'

import React, { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
    AlertTriangle,
    BellRing,
    Plus,
    RefreshCw,
    ShieldCheck,
    Trash2,
    Pencil,
    Power,
    PowerOff,
    Activity,
} from 'lucide-react'
import Navbar from '@/components/Navbar'
import {
    alertService,
    authService,
    type AlertConfig,
    type AlertRule,
    type UserInfo,
} from '@/services/api'
import { useConfirm } from '@/components/ui/ConfirmDialog'
import { Switch } from '@/components/ui/Switch'

const TRIGGER_TYPES = [
    { value: 'known', label: 'Known visitor detected' },
    { value: 'unknown', label: 'Unknown visitor detected' },
    { value: 'liveness_fail', label: 'Liveness check failed' },
    { value: 'anomaly', label: 'Anomaly detected' },
]

const PRIORITIES = ['low', 'medium', 'high', 'critical']
const ACTIONS = ['email', 'webhook', 'both', 'notify', 'silence']

type RuleDraft = {
    id?: string
    name: string
    description: string
    is_active: boolean
    priority: string
    trigger_type: string
    min_confidence: string
    action: string
    max_alerts_per_hour: string
}

const emptyDraft: RuleDraft = {
    name: '',
    description: '',
    is_active: true,
    priority: 'medium',
    trigger_type: 'unknown',
    min_confidence: '0.5',
    action: 'email',
    max_alerts_per_hour: '',
}

interface AlertStats {
    organization_id: string
    alerts_enabled: boolean
    total_rules: number
    active_rules: number
    by_trigger_type: Record<string, number>
}

interface AlertTrigger {
    id: string
    session_id: string | null
    visitor_id: string | null
    alert_type: string
    message: string
    created_at: string | null
}

export default function AlertsPage() {
    const confirm = useConfirm()
    const [user, setUser] = useState<UserInfo | null>(null)
    const [loading, setLoading] = useState(true)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

    const [config, setConfig] = useState<AlertConfig | null>(null)
    const [rules, setRules] = useState<AlertRule[]>([])
    const [stats, setStats] = useState<AlertStats | null>(null)
    const [triggers, setTriggers] = useState<AlertTrigger[]>([])

    const [draft, setDraft] = useState<RuleDraft>(emptyDraft)
    const [editingRuleId, setEditingRuleId] = useState<string | null>(null)

    const canManage = user?.role === 'admin'

    const showMessage = (type: 'success' | 'error', text: string) => {
        setMessage({ type, text })
        setTimeout(() => setMessage(null), 4000)
    }

    const refresh = async () => {
        const [configRes, rulesRes, statsRes, triggersRes] = await Promise.allSettled([
            alertService.getConfig(),
            alertService.getRules(),
            alertService.getStats({ days: 7 }),
            alertService.getTriggers({ days: 7 }),
        ])
        if (configRes.status === 'fulfilled') setConfig(configRes.value.data)
        if (rulesRes.status === 'fulfilled') setRules(rulesRes.value.data || [])
        if (statsRes.status === 'fulfilled') setStats(statsRes.value.data as AlertStats)
        if (triggersRes.status === 'fulfilled') setTriggers((triggersRes.value.data as AlertTrigger[]) || [])
        const anyFailed = [configRes, rulesRes, statsRes, triggersRes].some((r) => r.status === 'rejected')
        if (anyFailed) {
            showMessage('error', 'Some alerts data failed to load')
        }
    }

    useEffect(() => {
        authService.me().then((res) => setUser(res.data)).catch(() => setUser(null))
        refresh().finally(() => setLoading(false))
    }, [])

    const updateConfigField = async <K extends keyof AlertConfig>(field: K, value: AlertConfig[K]) => {
        if (!config) return
        const previous = config
        setConfig({ ...config, [field]: value })
        try {
            const res = await alertService.updateConfig({ [field]: value } as Partial<AlertConfig>)
            setConfig(res.data)
            showMessage('success', `Updated ${String(field)}`)
        } catch (err: any) {
            setConfig(previous)
            showMessage('error', err?.response?.data?.detail || `Failed to update ${String(field)}`)
        }
    }

    const submitRule = async (event: React.FormEvent) => {
        event.preventDefault()
        if (!draft.name.trim()) {
            showMessage('error', 'Rule name is required')
            return
        }
        const payload: Record<string, any> = {
            name: draft.name.trim(),
            description: draft.description.trim() || undefined,
            is_active: draft.is_active,
            priority: draft.priority,
            trigger_type: draft.trigger_type,
            action: draft.action,
        }
        const minConf = parseFloat(draft.min_confidence)
        if (!Number.isNaN(minConf)) payload.min_confidence = minConf
        const maxPerHour = parseInt(draft.max_alerts_per_hour, 10)
        if (!Number.isNaN(maxPerHour)) payload.max_alerts_per_hour = maxPerHour

        try {
            if (editingRuleId) {
                await alertService.updateRule(editingRuleId, payload as Partial<AlertRule>)
                showMessage('success', 'Rule updated')
            } else {
                await alertService.createRule(payload as any)
                showMessage('success', 'Rule created')
            }
            setDraft(emptyDraft)
            setEditingRuleId(null)
            await refresh()
        } catch (err: any) {
            showMessage('error', err?.response?.data?.detail || 'Failed to save rule')
        }
    }

    const startEdit = (rule: AlertRule) => {
        setEditingRuleId(rule.id)
        setDraft({
            id: rule.id,
            name: rule.name,
            description: rule.description || '',
            is_active: rule.is_active,
            priority: (rule as any).priority || 'medium',
            trigger_type: rule.trigger_type,
            min_confidence: rule.min_confidence != null ? String(rule.min_confidence) : '',
            action: rule.action || 'email',
            max_alerts_per_hour: (rule as any).max_alerts_per_hour != null
                ? String((rule as any).max_alerts_per_hour) : '',
        })
        window.scrollTo({ top: 0, behavior: 'smooth' })
    }

    const cancelEdit = () => {
        setEditingRuleId(null)
        setDraft(emptyDraft)
    }

    const toggleRule = async (rule: AlertRule) => {
        try {
            if (rule.is_active) {
                await alertService.deactivateRule(rule.id)
            } else {
                await alertService.activateRule(rule.id)
            }
            await refresh()
        } catch (err: any) {
            showMessage('error', err?.response?.data?.detail || 'Failed to toggle rule')
        }
    }

    const deleteRule = async (rule: AlertRule) => {
        const ok = await confirm({
            kind: 'danger',
            title: `Delete rule "${rule.name}"?`,
            description: 'Notifications for this rule will stop immediately. Existing alert history will be preserved.',
            confirmLabel: 'Delete rule',
        })
        if (!ok) return
        try {
            await alertService.deleteRule(rule.id)
            showMessage('success', 'Rule deleted')
            await refresh()
        } catch (err: any) {
            showMessage('error', err?.response?.data?.detail || 'Failed to delete rule')
        }
    }

    if (loading) {
        return (
            <div className="min-h-screen bg-[#050505] text-white">
                <Navbar />
                <main className="pt-28 px-6 max-w-7xl mx-auto">
                    <div className="animate-pulse space-y-6">
                        <div className="h-10 w-72 bg-white/10 rounded-xl" />
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                            {Array.from({ length: 4 }).map((_, i) => (
                                <div key={i} className="h-32 bg-white/10 rounded-3xl" />
                            ))}
                        </div>
                        <div className="h-80 bg-white/10 rounded-3xl" />
                    </div>
                </main>
            </div>
        )
    }

    return (
        <div className="min-h-screen bg-[#050505] text-white">
            <Navbar />
            <main className="pt-28 pb-16 px-6 max-w-7xl mx-auto">
                <div className="flex items-center justify-between gap-4 mb-8">
                    <div>
                        <h1 className="text-4xl font-extrabold bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent flex items-center gap-3">
                            <BellRing className="text-brand-400" /> Alerts
                        </h1>
                        <p className="text-gray-400 mt-2">
                            Configure trigger rules, notification channels, and inspect recent alert activity.
                        </p>
                    </div>
                    <div className="flex items-center gap-3">
                        <button
                            onClick={refresh}
                            className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-gray-200 hover:bg-white/10"
                        >
                            <RefreshCw size={14} /> Refresh
                        </button>
                        {canManage && (
                            <div className="flex items-center gap-2 text-sm text-gray-400">
                                <ShieldCheck size={16} /> Admin access
                            </div>
                        )}
                    </div>
                </div>

                {message && (
                    <div
                        className={`mb-6 px-4 py-3 rounded-xl border ${message.type === 'success'
                            ? 'bg-green-500/10 border-green-500/20 text-green-300'
                            : 'bg-red-500/10 border-red-500/20 text-red-300'
                            }`}
                    >
                        {message.text}
                    </div>
                )}

                {/* Stats */}
                {stats && (
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
                        <StatCard
                            label="Alerts"
                            value={stats.alerts_enabled ? 'ENABLED' : 'DISABLED'}
                            accent={stats.alerts_enabled ? 'text-green-400' : 'text-red-400'}
                            icon={<BellRing size={18} />}
                        />
                        <StatCard
                            label="Total rules"
                            value={String(stats.total_rules)}
                            accent="text-brand-400"
                            icon={<AlertTriangle size={18} />}
                        />
                        <StatCard
                            label="Active rules"
                            value={String(stats.active_rules)}
                            accent="text-blue-400"
                            icon={<Power size={18} />}
                        />
                        <StatCard
                            label="Triggers (7d)"
                            value={String(triggers.length)}
                            accent="text-amber-400"
                            icon={<Activity size={18} />}
                        />
                    </div>
                )}

                {/* Config + Create form */}
                <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-8">
                    {/* Global config */}
                    <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
                        <h2 className="text-xl font-bold mb-1">Global Configuration</h2>
                        <p className="text-sm text-gray-400 mb-5">
                            Organization-wide defaults applied to every rule.
                        </p>
                        {config && (
                            <div className="space-y-4">
                                <ToggleRow
                                    label="Alerts enabled"
                                    description="Master switch for all alert delivery"
                                    checked={config.alerts_enabled}
                                    disabled={!canManage}
                                    onChange={(v) => updateConfigField('alerts_enabled', v)}
                                />
                                <ToggleRow
                                    label="Email delivery"
                                    description="Send alerts to configured email recipients"
                                    checked={config.email_alerts_enabled}
                                    disabled={!canManage}
                                    onChange={(v) => updateConfigField('email_alerts_enabled', v)}
                                />
                                <ToggleRow
                                    label="Webhook delivery"
                                    description="Forward alerts to registered webhooks"
                                    checked={config.webhook_alerts_enabled}
                                    disabled={!canManage}
                                    onChange={(v) => updateConfigField('webhook_alerts_enabled', v)}
                                />

                                <div>
                                    <label className="block text-sm text-gray-300 mb-2">
                                        Minimum confidence threshold ({config.min_confidence_threshold.toFixed(2)})
                                    </label>
                                    <input
                                        type="range"
                                        min={0}
                                        max={1}
                                        step={0.05}
                                        disabled={!canManage}
                                        value={config.min_confidence_threshold}
                                        onChange={(e) => updateConfigField('min_confidence_threshold', parseFloat(e.target.value))}
                                        className="w-full accent-brand-500"
                                    />
                                </div>

                                <div>
                                    <label className="block text-sm text-gray-300 mb-2">
                                        Duplicate suppression window (seconds)
                                    </label>
                                    <input
                                        type="number"
                                        min={0}
                                        max={3600}
                                        disabled={!canManage}
                                        value={config.alert_duplicate_window_seconds}
                                        onChange={(e) =>
                                            updateConfigField(
                                                'alert_duplicate_window_seconds',
                                                Math.max(0, parseInt(e.target.value || '0', 10)),
                                            )
                                        }
                                        className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-2.5 text-sm outline-none focus:border-brand-500"
                                    />
                                </div>
                            </div>
                        )}
                    </section>

                    {/* Create / edit rule */}
                    <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
                        <h2 className="text-xl font-bold mb-1">
                            {editingRuleId ? 'Edit Rule' : 'Create Rule'}
                        </h2>
                        <p className="text-sm text-gray-400 mb-4">
                            Define trigger conditions, priority, and the notification action.
                        </p>

                        {/* Natural-language rule preview */}
                        <div className="mb-5 p-4 rounded-xl bg-brand-500/5 border border-brand-500/20">
                            <p className="text-xs font-bold uppercase tracking-widest text-brand-400 mb-1">Rule Preview</p>
                            <p className="text-sm text-gray-300 leading-relaxed">
                                When a{' '}
                                <span className="text-white font-semibold">
                                    {TRIGGER_TYPES.find(t => t.value === draft.trigger_type)?.label?.toLowerCase() || draft.trigger_type}
                                </span>
                                {' '}is detected by{' '}
                                <span className="text-white font-semibold">any camera</span>
                                {draft.min_confidence && parseFloat(draft.min_confidence) > 0 ? (
                                    <> with confidence above{' '}
                                    <span className="text-white font-semibold">{Math.round(parseFloat(draft.min_confidence) * 100)}%</span></>
                                ) : null}
                                , send a{' '}
                                <span className="text-white font-semibold">{draft.action}</span>
                                {' '}with{' '}
                                <span className="text-white font-semibold">{draft.priority}</span>
                                {' '}priority.
                                {draft.max_alerts_per_hour ? (
                                    <> Maximum <span className="text-white font-semibold">{draft.max_alerts_per_hour} alerts/hour</span>.</>
                                ) : null}
                            </p>
                        </div>

                        <form onSubmit={submitRule} className="space-y-3">
                            <input
                                value={draft.name}
                                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                                placeholder="Rule name"
                                disabled={!canManage}
                                className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                            />
                            <textarea
                                value={draft.description}
                                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                                placeholder="Description (optional)"
                                rows={2}
                                disabled={!canManage}
                                className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                            />
                            <div className="grid grid-cols-2 gap-3">
                                <select
                                    value={draft.trigger_type}
                                    onChange={(e) => setDraft({ ...draft, trigger_type: e.target.value })}
                                    disabled={!canManage}
                                    className="rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                                >
                                    {TRIGGER_TYPES.map((t) => (
                                        <option key={t.value} value={t.value}>{t.label}</option>
                                    ))}
                                </select>
                                <select
                                    value={draft.priority}
                                    onChange={(e) => setDraft({ ...draft, priority: e.target.value })}
                                    disabled={!canManage}
                                    className="rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                                >
                                    {PRIORITIES.map((p) => (
                                        <option key={p} value={p}>{p}</option>
                                    ))}
                                </select>
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div>
                                    <input
                                        type="number"
                                        step={0.05}
                                        min={0}
                                        max={1}
                                        value={draft.min_confidence}
                                        onChange={(e) => {
                                            let val = e.target.value
                                            const num = parseFloat(val)
                                            if (!Number.isNaN(num)) {
                                                if (num > 1) val = '1'
                                                if (num < 0) val = '0'
                                            }
                                            setDraft({ ...draft, min_confidence: val })
                                        }}
                                        placeholder="Min confidence (0–1)"
                                        disabled={!canManage}
                                        className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                                    />
                                    {draft.min_confidence && !Number.isNaN(parseFloat(draft.min_confidence)) && (
                                        <span className="text-[10px] text-gray-500 mt-1 block">
                                            = {Math.round(parseFloat(draft.min_confidence) * 100)}% confidence
                                        </span>
                                    )}
                                </div>
                                <select
                                    value={draft.action}
                                    onChange={(e) => setDraft({ ...draft, action: e.target.value })}
                                    disabled={!canManage}
                                    className="rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                                >
                                    {ACTIONS.map((a) => (
                                        <option key={a} value={a}>{a}</option>
                                    ))}
                                </select>
                            </div>
                            <input
                                type="number"
                                min={0}
                                value={draft.max_alerts_per_hour}
                                onChange={(e) => setDraft({ ...draft, max_alerts_per_hour: e.target.value })}
                                placeholder="Max alerts per hour (optional)"
                                disabled={!canManage}
                                className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm outline-none focus:border-brand-500"
                            />
                            <div className="flex items-center gap-3 text-sm text-gray-300">
                                <Switch
                                    checked={draft.is_active}
                                    onCheckedChange={(next) => setDraft({ ...draft, is_active: next })}
                                    disabled={!canManage}
                                    label="Activate rule immediately after creating"
                                />
                                <span>Activate immediately</span>
                            </div>
                            <div className="flex items-center gap-2 pt-1">
                                <button
                                    type="submit"
                                    disabled={!canManage}
                                    className="inline-flex items-center gap-2 rounded-xl border border-brand-500/30 bg-brand-500/20 px-4 py-3 text-brand-100 hover:bg-brand-500/30 disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                    <Plus size={16} /> {editingRuleId ? 'Save changes' : 'Create rule'}
                                </button>
                                {editingRuleId && (
                                    <button
                                        type="button"
                                        onClick={cancelEdit}
                                        className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-gray-300"
                                    >
                                        Cancel
                                    </button>
                                )}
                            </div>
                        </form>
                    </section>
                </div>

                {/* Rules table */}
                <section className="rounded-3xl border border-white/10 bg-white/5 p-6 mb-8">
                    <div className="flex items-center justify-between mb-5">
                        <div>
                            <h2 className="text-xl font-bold">Alert Rules</h2>
                            <p className="text-sm text-gray-400">
                                Rules are evaluated in order; higher priority triggers first.
                            </p>
                        </div>
                    </div>

                    {rules.length === 0 ? (
                        <p className="text-sm text-gray-500">No alert rules yet. Create your first rule above.</p>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead className="text-left text-gray-400 border-b border-white/10">
                                    <tr>
                                        <th className="py-3 pr-3">Name</th>
                                        <th className="py-3 pr-3">Trigger</th>
                                        <th className="py-3 pr-3">Priority</th>
                                        <th className="py-3 pr-3">Min conf.</th>
                                        <th className="py-3 pr-3">Action</th>
                                        <th className="py-3 pr-3">Status</th>
                                        <th className="py-3 pr-3 text-right">Controls</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rules.map((rule, idx) => (
                                        <motion.tr
                                            key={rule.id}
                                            initial={{ opacity: 0, y: 4 }}
                                            animate={{ opacity: 1, y: 0 }}
                                            transition={{ delay: idx * 0.02 }}
                                            className="border-b border-white/5 hover:bg-white/5"
                                        >
                                            <td className="py-3 pr-3">
                                                <div className="font-semibold text-white">{rule.name}</div>
                                                {rule.description && (
                                                    <div className="text-xs text-gray-500 mt-0.5">{rule.description}</div>
                                                )}
                                            </td>
                                            <td className="py-3 pr-3 text-gray-300">{rule.trigger_type}</td>
                                            <td className="py-3 pr-3">
                                                <PriorityBadge priority={(rule as any).priority || 'medium'} />
                                            </td>
                                            <td className="py-3 pr-3 text-gray-300">
                                                {rule.min_confidence != null ? rule.min_confidence.toFixed(2) : '–'}
                                            </td>
                                            <td className="py-3 pr-3 text-gray-300">{rule.action}</td>
                                            <td className="py-3 pr-3">
                                                <span
                                                    className={`px-2 py-0.5 rounded-full text-xs font-semibold ${rule.is_active
                                                        ? 'bg-green-500/10 text-green-300 border border-green-500/20'
                                                        : 'bg-gray-500/10 text-gray-400 border border-white/10'
                                                        }`}
                                                >
                                                    {rule.is_active ? 'active' : 'paused'}
                                                </span>
                                            </td>
                                            <td className="py-3 pl-3 text-right">
                                                <div className="inline-flex items-center gap-1.5">
                                                    <button
                                                        onClick={() => toggleRule(rule)}
                                                        disabled={!canManage}
                                                        aria-label={rule.is_active ? `Pause rule ${rule.name}` : `Activate rule ${rule.name}`}
                                                        title={rule.is_active ? 'Pause' : 'Activate'}
                                                        className="rounded-lg border border-white/10 bg-white/5 p-2 text-gray-300 hover:bg-white/10 disabled:opacity-40"
                                                    >
                                                        {rule.is_active ? <PowerOff size={14} /> : <Power size={14} />}
                                                    </button>
                                                    <button
                                                        onClick={() => startEdit(rule)}
                                                        disabled={!canManage}
                                                        aria-label={`Edit rule ${rule.name}`}
                                                        title="Edit"
                                                        className="rounded-lg border border-white/10 bg-white/5 p-2 text-gray-300 hover:bg-white/10 disabled:opacity-40"
                                                    >
                                                        <Pencil size={14} />
                                                    </button>
                                                    <button
                                                        onClick={() => deleteRule(rule)}
                                                        disabled={!canManage}
                                                        aria-label={`Delete rule ${rule.name}`}
                                                        title="Delete"
                                                        className="rounded-lg border border-red-500/20 bg-red-500/10 p-2 text-red-300 hover:bg-red-500/20 disabled:opacity-40"
                                                    >
                                                        <Trash2 size={14} />
                                                    </button>
                                                </div>
                                            </td>
                                        </motion.tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </section>

                {/* Recent triggers */}
                <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
                    <div className="flex items-center justify-between mb-5">
                        <div>
                            <h2 className="text-xl font-bold">Recent Triggers (7 days)</h2>
                            <p className="text-sm text-gray-400">Most recent alert events across all rules.</p>
                        </div>
                    </div>

                    {triggers.length === 0 ? (
                        <p className="text-sm text-gray-500">No alerts have fired in the last 7 days.</p>
                    ) : (
                        <div className="space-y-3">
                            {triggers.slice(0, 25).map((trigger) => (
                                <div
                                    key={trigger.id}
                                    className="rounded-2xl border border-white/10 bg-black/30 p-4"
                                >
                                    <div className="flex items-start justify-between gap-3">
                                        <div className="min-w-0">
                                            <div className="flex items-center gap-2 mb-1">
                                                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-brand-500/10 text-brand-300 border border-brand-500/20">
                                                    {trigger.alert_type}
                                                </span>
                                                {trigger.created_at && (
                                                    <span className="text-xs text-gray-500">
                                                        {new Date(trigger.created_at).toLocaleString()}
                                                    </span>
                                                )}
                                            </div>
                                            <p className="text-sm text-gray-300 truncate">{trigger.message}</p>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </section>
            </main>
        </div>
    )
}

// ─────────────────────────────────────────────────────────────────────────────

function StatCard({
    label,
    value,
    accent,
    icon,
}: {
    label: string
    value: string
    accent: string
    icon: React.ReactNode
}) {
    return (
        <div className="rounded-3xl border border-white/10 bg-white/5 p-5">
            <div className="flex items-center gap-3 mb-2">
                <div className={`p-2 rounded-xl bg-white/5 ${accent}`}>{icon}</div>
                <span className="text-xs uppercase tracking-wider text-gray-500">{label}</span>
            </div>
            <div className={`text-2xl font-extrabold ${accent}`}>{value}</div>
        </div>
    )
}

function ToggleRow({
    label,
    description,
    checked,
    disabled,
    onChange,
}: {
    label: string
    description: string
    checked: boolean
    disabled?: boolean
    onChange: (value: boolean) => void
}) {
    return (
        <div className="flex items-center justify-between gap-4">
            <div>
                <div className="font-semibold text-sm text-white">{label}</div>
                <div className="text-xs text-gray-500 mt-0.5">{description}</div>
            </div>
            <button
                type="button"
                onClick={() => !disabled && onChange(!checked)}
                disabled={disabled}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${checked ? 'bg-brand-500' : 'bg-white/10'
                    } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
                <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'
                        }`}
                />
            </button>
        </div>
    )
}

function PriorityBadge({ priority }: { priority: string }) {
    const map: Record<string, string> = {
        low: 'bg-gray-500/10 text-gray-300 border-white/10',
        medium: 'bg-blue-500/10 text-blue-300 border-blue-500/20',
        high: 'bg-orange-500/10 text-orange-300 border-orange-500/20',
        critical: 'bg-red-500/10 text-red-300 border-red-500/20',
    }
    return (
        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${map[priority] || map.medium}`}>
            {priority}
        </span>
    )
}

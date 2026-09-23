'use client'

import React, { useState, useEffect, useRef, useCallback } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
    Shield, LayoutDashboard, Users, Video, FileText, LogOut, Menu, X,
    Settings as SettingsIcon, BarChart3, Upload, ClipboardList, Lightbulb,
    ShieldCheck, FileBarChart, Sun, Moon, Rocket, Activity, Keyboard, Cpu,
    Webhook, Layers, Box, Network, Smile, GitBranch, Waves,
    FlaskConical, Lock, BellRing, ChevronDown, FlaskRound, AlertTriangle,
} from 'lucide-react'
import { authService, analyticsService, alertService, orgService } from '@/services/api'
import type { UserInfo, Organization } from '@/services/api'
import NotificationCenter from './NotificationCenter'
import { useTheme } from './ThemeProvider'

// ── Nav structure ──────────────────────────────────────────────────────────────

type NavItem = {
    href: string
    label: string
    icon: React.ElementType
    experimental?: boolean
}

type NavGroup = {
    label: string
    icon: React.ElementType
    experimental?: boolean
    items: NavItem[]
}

const NAV_GROUPS: NavGroup[] = [
    {
        label: 'Operations',
        icon: Activity,
        items: [
            { href: '/', label: 'Overview Dashboard', icon: LayoutDashboard },
            { href: '/live-activities', label: 'Real-time Feed', icon: Activity },
            { href: '/liveness', label: 'Active Liveness', icon: ShieldCheck },
            { href: '/logs', label: 'Security Logs', icon: FileText },
        ],
    },
    {
        label: 'Directory',
        icon: Users,
        items: [
            { href: '/visitors', label: 'Subject Database', icon: Users },
            { href: '/upload', label: 'Batch Processing', icon: Upload },
            { href: '/missing-persons/disaster-events', label: 'Disaster Response', icon: AlertTriangle },
        ],
    },
    {
        label: 'Intelligence',
        icon: BarChart3,
        items: [
            { href: '/analytics', label: 'Behavior Analytics', icon: BarChart3 },
            { href: '/data-quality', label: 'Media Integrity', icon: ShieldCheck },
            { href: '/reports', label: 'Audit Reports', icon: FileBarChart },
        ],
    },
]

// AI Lab group is experimental — visible to admin only.
// Every item here calls a route gated behind ENABLE_PHASE3_FEATURES or
// ENABLE_EXPERIMENTAL_FEATURES, which default OFF in production — do not
// move an item out of this group unless its backend route is core-mounted.
const AI_LAB_GROUP: NavGroup = {
    label: 'AI Lab',
    icon: FlaskRound,
    experimental: true,
    items: [
        { href: '/emotion', label: 'Sentiment Analysis', icon: Smile, experimental: true },
        { href: '/multimodal', label: 'Multimodal', icon: Layers },
        { href: '/3d-face', label: '3D Face', icon: Box },
        { href: '/reid', label: 'Re-ID', icon: GitBranch },
        { href: '/vit', label: 'Vision Transformer', icon: Cpu },
        { href: '/multispectral', label: 'Spectral', icon: Waves },
        { href: '/ab-testing', label: 'A/B Testing', icon: FlaskConical },
        { href: '/federated', label: 'Federated Learning', icon: Network },
        { href: '/enhancements', label: 'Enhancements', icon: Rocket },
        { href: '/future-enhancements', label: 'Roadmap', icon: Rocket },
    ],
}

const ADMIN_ITEMS: NavItem[] = [
    { href: '/users', label: 'Users', icon: Users },
    { href: '/alerts', label: 'Alerts', icon: BellRing },
    { href: '/audit-logs', label: 'Audit Logs', icon: ClipboardList },
    { href: '/settings/consent', label: 'Consent Portal', icon: ShieldCheck },
    { href: '/edge-devices', label: 'Edge Devices', icon: Cpu },
    { href: '/integrations', label: 'Integrations', icon: Webhook },
    { href: '/security', label: 'Security', icon: Lock },
    { href: '/settings', label: 'Settings', icon: SettingsIcon },
]

// Mobile bottom nav — 5 most-used features
const MOBILE_BOTTOM_NAV = [
    { href: '/', label: 'Home', icon: LayoutDashboard },
    { href: '/logs', label: 'Logs', icon: FileText },
    { href: '/visitors', label: 'People', icon: Users },
    { href: '/live-activities', label: 'Live', icon: Activity },
    { href: '/alerts', label: 'Alerts', icon: BellRing },
]

// ── System Health Dot ──────────────────────────────────────────────────────────

type HealthStatus = 'healthy' | 'degraded' | 'critical' | 'unknown'

function SystemHealthDot() {
    const [status, setStatus] = useState<HealthStatus>('unknown')
    const [open, setOpen] = useState(false)
    const [detail, setDetail] = useState<{ ai: string; errorRate: number; recognitionBackend: string | null; recognitionDegraded: boolean | null } | null>(null)
    const ref = useRef<HTMLDivElement>(null)

    const check = useCallback(async () => {
        try {
            const res = await analyticsService.getSystemHealth()
            const h = res.data
            if (!h) { setStatus('unknown'); return }
            const aiOk = h.ai_service_status === 'online' || h.ai_service_status === 'healthy'
            const highError = (h.error_rate ?? 0) > 0.1
            const recognitionDegraded = h.recognition_degraded ?? null
            if (!aiOk) setStatus('critical')
            else if (highError || recognitionDegraded) setStatus('degraded')
            else setStatus('healthy')
            setDetail({
                ai: h.ai_service_status,
                errorRate: h.error_rate ?? 0,
                recognitionBackend: h.recognition_backend ?? null,
                recognitionDegraded,
            })
        } catch {
            setStatus('unknown')
        }
    }, [])

    useEffect(() => {
        check()
        const iv = setInterval(check, 30000)
        return () => clearInterval(iv)
    }, [check])

    // Close on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
        }
        document.addEventListener('mousedown', handler)
        return () => document.removeEventListener('mousedown', handler)
    }, [])

    const dot = {
        healthy: 'bg-green-400',
        degraded: 'bg-yellow-400',
        critical: 'bg-red-500',
        unknown: 'bg-gray-500',
    }[status]

    const label = {
        healthy: 'All systems operational',
        degraded: 'Degraded — check services',
        critical: 'Critical — AI service down',
        unknown: 'Status unknown',
    }[status]

    return (
        <div ref={ref} className="relative">
            <button
                onClick={() => setOpen(v => !v)}
                title="System health"
                aria-label={`System health: ${label}`}
                aria-expanded={open}
                aria-haspopup="dialog"
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl hover:bg-white/5 transition-colors"
            >
                <span className={`w-2 h-2 rounded-full ${dot} ${status === 'healthy' ? 'animate-pulse' : ''}`} aria-hidden="true" />
                <span className="text-xs text-gray-500 hidden xl:block">
                    {status === 'unknown' ? '...' : status === 'healthy' ? 'Live' : status}
                </span>
            </button>

            <AnimatePresence>
                {open && (
                    <motion.div
                        initial={{ opacity: 0, y: 6, scale: 0.96 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 6, scale: 0.96 }}
                        transition={{ duration: 0.15 }}
                        className="absolute right-0 top-full mt-2 w-56 bg-gray-950 border border-white/10 rounded-2xl p-4 shadow-2xl z-50 text-xs"
                    >
                        <p className="font-bold text-white mb-3 flex items-center gap-2">
                            <span className={`w-2 h-2 rounded-full ${dot}`} />
                            System Status
                        </p>
                        <div className="space-y-2 text-gray-400">
                            <div className="flex justify-between">
                                <span>AI Service</span>
                                <span className={detail?.ai === 'online' ? 'text-green-400 font-semibold' : 'text-red-400 font-semibold'}>
                                    {detail?.ai ?? '—'}
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span>Recognition</span>
                                <span className={detail?.recognitionDegraded ? 'text-red-400 font-semibold' : detail?.recognitionBackend ? 'text-green-400 font-semibold' : 'text-gray-500'}>
                                    {detail?.recognitionBackend ?? '—'}{detail?.recognitionDegraded ? ' (fallback)' : ''}
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span>Error Rate</span>
                                <span className={(detail?.errorRate ?? 0) > 0.05 ? 'text-yellow-400' : 'text-green-400'}>
                                    {detail ? `${(detail.errorRate * 100).toFixed(1)}%` : '—'}
                                </span>
                            </div>
                        </div>
                        <p className="mt-3 text-gray-500 border-t border-white/5 pt-2">{label}</p>
                        {detail?.recognitionDegraded && (
                            <p className="mt-1.5 text-red-400/90 text-[11px] leading-snug">Weak fallback embeddings in use — no real ArcFace/AdaFace backend loaded.</p>
                        )}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}

// ── Nav Group Dropdown ─────────────────────────────────────────────────────────

function NavGroupDropdown({ group, pathname, isAdmin }: { group: NavGroup & { items: NavItem[] }; pathname: string; isAdmin?: boolean }) {
    const [open, setOpen] = useState(false)
    const ref = useRef<HTMLDivElement>(null)
    const isActive = group.items.some(item => item.href === pathname)

    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
        }
        document.addEventListener('mousedown', handler)
        return () => document.removeEventListener('mousedown', handler)
    }, [])

    return (
        <div ref={ref} className="relative">
            <button
                onClick={() => setOpen(v => !v)}
                aria-haspopup="menu"
                aria-expanded={open}
                aria-label={`${group.label} menu`}
                className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200 relative group ${
                    isActive ? 'text-brand-400' : 'text-gray-400 hover:text-white'
                }`}
            >
                <group.icon size={15} />
                {group.label}
                {group.experimental && (
                    <span className="text-[9px] font-black uppercase tracking-widest text-amber-400 bg-amber-400/10 px-1 py-0.5 rounded leading-none">
                        LAB
                    </span>
                )}
                <ChevronDown size={12} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
                {isActive && (
                    <motion.div
                        layoutId="nav-group-active"
                        className="absolute inset-0 bg-brand-500/10 rounded-xl -z-10 border border-brand-500/20"
                        transition={{ type: 'spring', bounce: 0.2, duration: 0.5 }}
                    />
                )}
                {isActive && !open && (
                    <span className="absolute -bottom-1 left-1/2 -translate-x-1/2 w-4 h-0.5 bg-brand-500 rounded-full" />
                )}
            </button>

            <AnimatePresence>
                {open && (
                    <motion.div
                        initial={{ opacity: 0, y: 8, scale: 0.96 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 8, scale: 0.96 }}
                        transition={{ duration: 0.15 }}
                        role="menu"
                        aria-label={`${group.label} submenu`}
                        className="absolute left-0 top-full mt-2 min-w-[200px] bg-gray-950/95 backdrop-blur-xl border border-white/10 rounded-2xl p-2 shadow-2xl z-50"
                    >
                        {group.experimental && (
                            <div className="flex items-center gap-2 px-3 py-2 mb-1 text-[11px] text-amber-400/80 border-b border-white/5">
                                <FlaskRound size={12} className="shrink-0" />
                                <span>These features are in active development and may be incomplete.</span>
                            </div>
                        )}
                        {group.items.map((item) => (
                            <Link
                                key={item.href}
                                href={item.href}
                                onClick={() => setOpen(false)}
                                role="menuitem"
                                className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all ${
                                    pathname === item.href
                                        ? 'bg-brand-500/10 text-brand-400 border border-brand-500/20'
                                        : 'text-gray-400 hover:text-white hover:bg-white/5'
                                }`}
                            >
                                <item.icon size={15} />
                                {item.label}
                                {item.experimental && (
                                    <span className="ml-auto text-[9px] font-black uppercase tracking-widest text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded leading-none border border-amber-400/20">
                                        EXP
                                    </span>
                                )}
                            </Link>
                        ))}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}

// ── Main Navbar ────────────────────────────────────────────────────────────────

export default function Navbar() {
    const pathname = usePathname()
    const [mobileOpen, setMobileOpen] = useState(false)
    const [user, setUser] = useState<UserInfo | null>(null)
    const { theme, toggleTheme } = useTheme()
    const [mobileGroup, setMobileGroup] = useState<string | null>(null)
    const [alertCount, setAlertCount] = useState(0)

    useEffect(() => {
        Promise.all([authService.me(), orgService.getMyOrg()])
            .then(([userRes, orgRes]) => {
                const u = userRes.data
                const org = orgRes.data
                setUser(u)
                if (typeof pendo !== 'undefined') {
                    pendo.identify({
                        visitor: {
                            id: u.id,
                            email: u.email,
                            full_name: u.full_name,
                            role: u.role,
                            is_active: u.is_active,
                            organization_id: u.organization_id,
                            created_at: u.created_at,
                        },
                        account: {
                            id: org.id,
                            name: org.name,
                            face_confidence_threshold: org.face_confidence_threshold,
                            log_retention_days: org.log_retention_days,
                            notification_email: org.notification_email,
                            notification_unidentified: org.notification_unidentified,
                            notification_email_address: org.notification_email_address,
                            created_at: org.created_at,
                        },
                    })
                }
            })
            .catch(() => setUser(null))
    }, [])

    // Poll alert count for mobile badge
    useEffect(() => {
        const fetchAlertCount = () => {
            alertService.getStats({ days: 1 })
                .then(res => { setAlertCount(res.data?.active_rules ?? 0) })
                .catch(() => {})
        }
        fetchAlertCount()
        const iv = setInterval(fetchAlertCount, 30000)
        return () => clearInterval(iv)
    }, [])

    useEffect(() => {
        setMobileOpen(false)
    }, [pathname])

    useEffect(() => {
        document.body.style.overflow = mobileOpen ? 'hidden' : ''
        return () => { document.body.style.overflow = '' }
    }, [mobileOpen])

    const handleLogout = async () => {
        try {
            await authService.logout()
        } catch (err) {
            console.warn('Logout API failed, clearing in-memory session', err)
        }
        if (typeof pendo !== 'undefined') {
            pendo.clearSession()
        }
        authService.clearSession()
        window.location.href = '/login'
    }

    const openShortcutHelp = () => {
        window.dispatchEvent(new CustomEvent('sentinelcv:open-shortcuts'))
    }

    const isAdmin = user?.role === 'admin'

    // Admin sees all groups including AI Lab and the Admin panel.
    // Staff sees only operational groups — no experimental AI Lab or Admin controls.
    const allGroups = isAdmin
        ? [...NAV_GROUPS, AI_LAB_GROUP, { label: 'Admin', icon: SettingsIcon, items: ADMIN_ITEMS }]
        : NAV_GROUPS

    return (
        <>
            {/* ── Desktop / tablet top navbar ──────────────────────────────── */}
            <nav className="fixed top-0 w-full z-50 bg-black/60 backdrop-blur-xl border-b border-white/5 supports-[backdrop-filter]:bg-black/40">
                <div className="container mx-auto px-4 flex justify-between items-center h-16">
                    {/* Logo */}
                    <Link href="/" className="flex items-center gap-2 group transition-transform hover:scale-105 shrink-0 mr-4">
                        <div className="w-9 h-9 bg-gradient-to-br from-brand-500 to-brand-700 rounded-xl flex items-center justify-center shadow-lg shadow-brand-500/20 group-hover:shadow-brand-500/40 transition-all">
                            <Shield size={20} className="text-white" />
                        </div>
                        <div className="flex flex-col">
                            <span className="text-lg font-bold tracking-tight text-white leading-none">
                                Sentinel<span className="text-brand-400">CV</span>
                            </span>
                            <span className="text-[9px] text-gray-500 font-medium tracking-[0.2em] uppercase hidden sm:block">
                                Security Suite
                            </span>
                        </div>
                    </Link>

                    {/* Desktop grouped nav */}
                    <div className="hidden md:flex items-center gap-1 flex-1">
                        {allGroups.map((group) => (
                            <NavGroupDropdown
                                key={group.label}
                                group={group as NavGroup & { items: NavItem[] }}
                                pathname={pathname}
                                isAdmin={isAdmin}
                            />
                        ))}
                    </div>

                    {/* Right controls */}
                    {user && (
                        <div className="hidden md:flex items-center gap-2 ml-2 pl-3 border-l border-white/10 shrink-0">
                            <SystemHealthDot />
                            <NotificationCenter />
                            <button
                                onClick={openShortcutHelp}
                                className="p-2 rounded-xl text-gray-400 hover:text-white hover:bg-white/5 transition-all"
                                aria-label="Show keyboard shortcuts"
                                title="Keyboard shortcuts"
                            >
                                <Keyboard size={16} />
                            </button>
                            <button
                                onClick={toggleTheme}
                                className="p-2 rounded-xl text-gray-400 hover:text-white hover:bg-white/5 transition-all hover:rotate-12"
                                aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                                title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
                            >
                                {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
                            </button>
                            <div className="flex flex-col items-end mx-1">
                                <span className="text-xs font-semibold text-white leading-none mb-0.5">{user.full_name}</span>
                                <span className="text-[9px] bg-brand-500/10 text-brand-400 px-1.5 py-0.5 rounded-full border border-brand-500/20 font-bold uppercase tracking-wider">
                                    {user.role}
                                </span>
                            </div>
                            <button
                                onClick={handleLogout}
                                className="p-2 rounded-xl text-gray-400 hover:text-red-400 hover:bg-red-400/10 transition-all group"
                                aria-label="Sign out"
                                title="Logout"
                            >
                                <LogOut size={18} className="group-hover:translate-x-0.5 transition-transform" />
                            </button>
                        </div>
                    )}

                    {/* Mobile hamburger */}
                    <button
                        className="md:hidden p-2 rounded-xl text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
                        onClick={() => setMobileOpen(!mobileOpen)}
                        aria-label={mobileOpen ? 'Close navigation menu' : 'Open navigation menu'}
                        aria-expanded={mobileOpen}
                    >
                        {mobileOpen ? <X size={22} /> : <Menu size={22} />}
                    </button>
                </div>

                {/* Mobile full-screen menu */}
                <AnimatePresence>
                    {mobileOpen && (
                        <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: 'auto' }}
                            exit={{ opacity: 0, height: 0 }}
                            className="md:hidden bg-black/98 backdrop-blur-2xl border-t border-white/5 overflow-hidden max-h-[calc(100vh-4rem)] overflow-y-auto pb-24"
                        >
                            <div className="px-4 py-4 space-y-1">
                                {allGroups.map((group) => (
                                    <div key={group.label}>
                                        {/* Group header */}
                                        <button
                                            onClick={() => setMobileGroup(mobileGroup === group.label ? null : group.label)}
                                            className="w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm font-bold text-gray-300 hover:bg-white/5 transition-colors"
                                        >
                                            <div className="flex items-center gap-3">
                                                <group.icon size={18} />
                                                {group.label}
                                                {'experimental' in group && group.experimental && (
                                                    <span className="text-[9px] font-black uppercase tracking-widest text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded">
                                                        LAB
                                                    </span>
                                                )}
                                            </div>
                                            <ChevronDown
                                                size={14}
                                                className={`transition-transform text-gray-500 ${mobileGroup === group.label ? 'rotate-180' : ''}`}
                                            />
                                        </button>

                                        {/* Group items */}
                                        <AnimatePresence>
                                            {mobileGroup === group.label && (
                                                <motion.div
                                                    initial={{ opacity: 0, height: 0 }}
                                                    animate={{ opacity: 1, height: 'auto' }}
                                                    exit={{ opacity: 0, height: 0 }}
                                                    className="ml-4 mt-1 space-y-1 overflow-hidden"
                                                >
                                                    {(group.items as NavItem[]).map((item) => (
                                                        <Link
                                                            key={item.href}
                                                            href={item.href}
                                                            onClick={() => setMobileOpen(false)}
                                                            className={`flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all ${
                                                                pathname === item.href
                                                                    ? 'bg-brand-500/10 text-brand-400 border border-brand-500/20'
                                                                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                                                            }`}
                                                        >
                                                            <item.icon size={16} />
                                                            {item.label}
                                                            {item.experimental && (
                                                                <span className="ml-auto text-[9px] font-black uppercase tracking-widest text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded border border-amber-400/20">
                                                                    EXP
                                                                </span>
                                                            )}
                                                        </Link>
                                                    ))}
                                                </motion.div>
                                            )}
                                        </AnimatePresence>
                                    </div>
                                ))}

                                {/* Mobile utilities */}
                                {user && (
                                    <div className="pt-3 mt-3 border-t border-white/10 space-y-1">
                                        <button
                                            onClick={openShortcutHelp}
                                            className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-gray-400 hover:text-white hover:bg-white/5 transition-all"
                                        >
                                            <Keyboard size={18} />
                                            Keyboard Shortcuts
                                        </button>
                                        <button
                                            onClick={toggleTheme}
                                            className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-gray-400 hover:text-white hover:bg-white/5 transition-all"
                                        >
                                            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
                                            {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
                                        </button>
                                        <button
                                            onClick={handleLogout}
                                            className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-gray-400 hover:text-red-400 hover:bg-red-400/5 transition-all"
                                        >
                                            <LogOut size={18} />
                                            Logout
                                        </button>
                                    </div>
                                )}
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </nav>

            {/* ── Mobile bottom navigation bar ─────────────────────────────── */}
            <nav className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-black/90 backdrop-blur-xl border-t border-white/5 pb-safe">
                <div className="flex items-center justify-around px-2 py-2">
                    {MOBILE_BOTTOM_NAV.map((item) => {
                        const isActive = pathname === item.href
                        const showBadge = item.href === '/alerts' && alertCount > 0
                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={`flex flex-col items-center gap-0.5 px-3 py-2 rounded-xl transition-all relative ${
                                    isActive
                                        ? 'text-brand-400'
                                        : 'text-gray-500 hover:text-gray-300'
                                }`}
                            >
                                <div className="relative">
                                    <item.icon size={20} />
                                    {showBadge && (
                                        <span className="absolute -top-1.5 -right-2.5 min-w-[16px] h-4 flex items-center justify-center rounded-full bg-red-500 text-white text-[9px] font-bold px-1 leading-none">
                                            {alertCount <= 9 ? alertCount : '9+'}
                                        </span>
                                    )}
                                </div>
                                <span className="text-[10px] font-medium">{item.label}</span>
                                {isActive && (
                                    <motion.div
                                        layoutId="mobile-bottom-active"
                                        className="absolute bottom-1 w-1 h-1 bg-brand-400 rounded-full"
                                        transition={{ type: 'spring', bounce: 0.3, duration: 0.4 }}
                                    />
                                )}
                            </Link>
                        )
                    })}
                </div>
            </nav>
        </>
    )
}

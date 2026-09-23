'use client'

import React, { useState, useMemo, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { Shield, LogIn, Building, Mail, User, ArrowLeft, Key, CheckCircle2, XCircle, Eye, Activity, Lock, Users } from 'lucide-react'
import { authService } from '@/services/api'

// ── Live password rules checker ───────────────────────────────────────────────
function PasswordRules({ password }: { password: string }) {
    const rules = useMemo(() => [
        { label: 'At least 8 characters', ok: password.length >= 8 },
        { label: 'One uppercase letter', ok: /[A-Z]/.test(password) },
        { label: 'One number', ok: /\d/.test(password) },
    ], [password])

    return (
        <ul className="mt-2 space-y-1" aria-label="Password requirements">
            {rules.map(rule => (
                <li key={rule.label} className="flex items-center gap-2 text-xs">
                    {rule.ok
                        ? <CheckCircle2 size={12} className="text-green-400 shrink-0" aria-hidden="true" />
                        : <XCircle size={12} className="text-gray-600 shrink-0" aria-hidden="true" />
                    }
                    <span className={rule.ok ? 'text-green-400' : 'text-gray-500'}>
                        {rule.label}
                        <span className="sr-only">{rule.ok ? ' — met' : ' — not met'}</span>
                    </span>
                </li>
            ))}
        </ul>
    )
}

// ── Feature list for left panel ───────────────────────────────────────────────
const FEATURES = [
    {
        icon: Eye,
        title: 'Real-time Detection',
        desc: 'Identify visitors instantly across multiple camera feeds.',
    },
    {
        icon: Users,
        title: 'Visitor Intelligence',
        desc: 'Build recognition profiles with adaptive AI thresholds.',
    },
    {
        icon: Activity,
        title: 'Live Analytics',
        desc: 'Monitor visitor flows, emotions, and behavioral patterns.',
    },
    {
        icon: Lock,
        title: 'Compliance-Ready',
        desc: 'Built-in GDPR controls, audit logs, and liveness checks.',
    },
]

// ── Main Login Page ───────────────────────────────────────────────────────────
export default function LoginPage() {
    const [mode, setMode] = useState<'login' | 'register' | 'forgot' | 'reset'>('login')
    const [email, setEmail] = useState('')
    const [password, setPassword] = useState('')
    const [fullName, setFullName] = useState('')
    const [orgName, setOrgName] = useState('')
    const [error, setError] = useState('')
    const [success, setSuccess] = useState('')
    const [loading, setLoading] = useState(false)

    // Password reset
    const [resetToken, setResetToken] = useState('')
    const [newPassword, setNewPassword] = useState('')
    const [registered, setRegistered] = useState(false)
    const [redirectIntent, setRedirectIntent] = useState<'login' | 'register' | null>(null)
    const [resetEmailSent, setResetEmailSent] = useState('')
    const [resendCooldown, setResendCooldown] = useState(0)
    const cooldownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

    // Deep-link reset: if URL contains ?token=... or #reset-token=..., auto-enter reset mode
    useEffect(() => {
        if (typeof window === 'undefined') return
        const params = new URLSearchParams(window.location.search)
        const tokenFromQuery = params.get('reset_token') || params.get('token')
        if (tokenFromQuery) {
            setResetToken(tokenFromQuery)
            setMode('reset')
            // Clean the URL so the token doesn't linger in browser history/referrers
            const clean = `${window.location.pathname}${window.location.hash}`
            window.history.replaceState(null, '', clean)
        }
    }, [])

    useEffect(() => {
        return () => {
            if (cooldownTimerRef.current) clearInterval(cooldownTimerRef.current)
        }
    }, [])

    useEffect(() => {
        if (!redirectIntent || typeof window === 'undefined') {
            return
        }

        const timeoutId = window.setTimeout(() => {
            window.location.assign('/')
        }, redirectIntent === 'register' ? 1500 : 0)

        return () => {
            window.clearTimeout(timeoutId)
        }
    }, [redirectIntent])

    const handleLogin = async (e: React.FormEvent) => {
        e.preventDefault()
        setError('')
        setRedirectIntent(null)
        setLoading(true)
        try {
            await authService.login(email, password)
            setRedirectIntent('login')
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Login failed. Check your email and password.')
        } finally {
            setLoading(false)
        }
    }

    const handleRegister = async (e: React.FormEvent) => {
        e.preventDefault()
        setError('')
        setRedirectIntent(null)
        setLoading(true)
        try {
            await authService.register({
                email,
                full_name: fullName,
                password,
                organization_name: orgName,
            })
            setRegistered(true)
            setRedirectIntent('register')
        } catch (err: any) {
            const detail = err.response?.data?.detail
            if (Array.isArray(detail)) {
                setError(detail.map((d: any) => d.msg).join('. '))
            } else {
                setError(detail || 'Registration failed')
            }
        } finally {
            setLoading(false)
        }
    }

    const handleForgotPassword = async (e: React.FormEvent) => {
        e.preventDefault()
        setError('')
        setSuccess('')
        setLoading(true)
        try {
            const res = await authService.forgotPassword(email)
            const token = res.data.reset_token
            const maskedEmail = email.replace(/^(.)(.*)(@.*)$/, (_, a, b, c) => a + b.replace(/./g, '*') + c)
            setResetEmailSent(maskedEmail)
            if (token) {
                setResetToken(token)
                setSuccess(`A reset token was sent to ${maskedEmail}. Check your inbox — it expires in 15 minutes.`)
            } else {
                setResetToken('')
                setSuccess(`A reset token was sent to ${maskedEmail}. Check your inbox — it expires in 15 minutes.`)
            }
            setResendCooldown(60)
            if (cooldownTimerRef.current) clearInterval(cooldownTimerRef.current)
            cooldownTimerRef.current = setInterval(() => {
                setResendCooldown(prev => {
                    if (prev <= 1) {
                        if (cooldownTimerRef.current) clearInterval(cooldownTimerRef.current)
                        return 0
                    }
                    return prev - 1
                })
            }, 1000)
            setMode('reset')
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Failed to request password reset')
        } finally {
            setLoading(false)
        }
    }

    const handleResetPassword = async (e: React.FormEvent) => {
        e.preventDefault()
        setError('')
        setSuccess('')
        setLoading(true)
        try {
            await authService.resetPassword(resetToken, newPassword)
            setSuccess('Password reset successfully! You can now sign in with your new password.')
            setMode('login')
            setResetToken('')
            setNewPassword('')
        } catch (err: any) {
            const detail = err.response?.data?.detail
            if (Array.isArray(detail)) {
                setError(detail.map((d: any) => d.msg).join('. '))
            } else {
                setError(detail || 'Failed to reset password')
            }
        } finally {
            setLoading(false)
        }
    }

    const switchMode = (next: typeof mode) => {
        setMode(next)
        setError('')
        setSuccess('')
        setRedirectIntent(null)
    }

    return (
        <div className="min-h-screen flex">
            {/* ── Left value-proposition panel (hidden on mobile) ─────────── */}
            <div className="hidden lg:flex lg:w-[55%] relative bg-gradient-to-br from-gray-950 via-brand-950 to-gray-950 flex-col justify-between p-12 overflow-hidden">
                {/* Background glow */}
                <div className="absolute inset-0 pointer-events-none">
                    <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-brand-500/10 blur-[120px] rounded-full" />
                    <div className="absolute bottom-1/4 right-1/4 w-64 h-64 bg-brand-700/10 blur-[100px] rounded-full" />
                </div>

                {/* Logo */}
                <div className="flex items-center gap-3 relative z-10">
                    <div className="w-10 h-10 bg-gradient-to-br from-brand-500 to-brand-700 rounded-xl flex items-center justify-center shadow-lg shadow-brand-500/30">
                        <Shield size={22} className="text-white" />
                    </div>
                    <div>
                        <span className="text-xl font-bold tracking-tight text-white">
                            Sentinel<span className="text-brand-400">CV</span>
                        </span>
                        <p className="text-[10px] text-gray-500 font-medium tracking-[0.2em] uppercase">Security Suite</p>
                    </div>
                </div>

                {/* Hero headline */}
                <div className="relative z-10">
                    <h1 className="text-4xl xl:text-5xl font-black text-white leading-tight mb-4 tracking-tight">
                        AI-Powered<br />
                        <span className="bg-gradient-to-r from-brand-400 to-brand-300 bg-clip-text text-transparent">
                            Visitor Intelligence
                        </span>
                    </h1>
                    <p className="text-gray-400 text-lg max-w-md leading-relaxed mb-10">
                        Real-time face recognition, behavioral analytics, and compliance tooling for high-security environments.
                    </p>

                    {/* Feature list */}
                    <div className="grid grid-cols-1 gap-4">
                        {FEATURES.map((f, i) => (
                            <motion.div
                                key={f.title}
                                initial={{ opacity: 0, x: -20 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ delay: 0.1 + i * 0.08 }}
                                className="flex items-start gap-4"
                            >
                                <div className="w-9 h-9 bg-brand-500/10 rounded-xl flex items-center justify-center shrink-0 border border-brand-500/20">
                                    <f.icon size={16} className="text-brand-400" />
                                </div>
                                <div>
                                    <p className="font-semibold text-white text-sm">{f.title}</p>
                                    <p className="text-gray-500 text-xs leading-relaxed">{f.desc}</p>
                                </div>
                            </motion.div>
                        ))}
                    </div>
                </div>

                {/* Bottom tagline */}
                <p className="text-xs text-gray-600 relative z-10">
                    Enterprise security infrastructure · Trusted for critical deployments
                </p>
            </div>

            {/* ── Right auth panel ──────────────────────────────────────────── */}
            <div className="flex-1 flex items-center justify-center px-6 py-12 lg:py-8">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="w-full max-w-md"
                >
                    {/* Mobile-only logo */}
                    <div className="flex items-center justify-center gap-3 mb-8 lg:hidden">
                        <div className="w-12 h-12 bg-brand-600 rounded-xl flex items-center justify-center">
                            <Shield size={26} />
                        </div>
                        <span className="text-3xl font-bold tracking-tight">
                            Sentinel<span className="text-brand-400">CV</span>
                        </span>
                    </div>

                    <div className="glass-card p-8">
                        {/* Tab toggle — login / register */}
                        {(mode === 'login' || mode === 'register') && (
                            <div className="flex mb-6 bg-white/5 rounded-lg p-1">
                                <button
                                    onClick={() => switchMode('login')}
                                    className={`flex-1 py-2 rounded-md text-sm font-medium transition-colors ${
                                        mode === 'login' ? 'bg-brand-600 text-white' : 'text-gray-400 hover:text-white'
                                    }`}
                                >
                                    Sign In
                                </button>
                                <button
                                    onClick={() => switchMode('register')}
                                    className={`flex-1 py-2 rounded-md text-sm font-medium transition-colors ${
                                        mode === 'register' ? 'bg-brand-600 text-white' : 'text-gray-400 hover:text-white'
                                    }`}
                                >
                                    Register
                                </button>
                            </div>
                        )}

                        {/* Back button for forgot/reset */}
                        {(mode === 'forgot' || mode === 'reset') && (
                            <button
                                onClick={() => switchMode('login')}
                                className="flex items-center gap-2 text-gray-400 hover:text-white text-sm mb-4 transition-colors"
                            >
                                <ArrowLeft size={16} /> Back to Sign In
                            </button>
                        )}

                        {mode === 'forgot' && (
                            <div className="mb-4">
                                <h2 className="text-lg font-bold mb-1">Forgot Password</h2>
                                <p className="text-sm text-gray-400">Enter your email to receive a password reset token.</p>
                            </div>
                        )}
                        {mode === 'reset' && (
                            <div className="mb-4">
                                <h2 className="text-lg font-bold mb-1">Reset Password</h2>
                                <p className="text-sm text-gray-400">
                                    {resetToken
                                        ? 'Reset token loaded. Choose a new password below.'
                                        : 'Enter the reset token from your email and choose a new password.'}
                                </p>
                            </div>
                        )}

                        {/* Error / success banners — errors are persistent (not auto-dismiss) */}
                        {error && (
                            <div className="bg-red-500/10 border border-red-500/30 text-red-400 text-sm px-4 py-3 rounded-lg mb-4 flex items-start gap-2">
                                <XCircle size={16} className="shrink-0 mt-0.5" />
                                <span>{error}</span>
                            </div>
                        )}
                        {success && (
                            <div className="bg-green-500/10 border border-green-500/20 text-green-400 text-sm px-4 py-3 rounded-lg mb-4 flex items-center gap-2">
                                <CheckCircle2 size={16} className="shrink-0" />
                                {success}
                            </div>
                        )}

                        {/* ── Login Form ──────────────────────────────────── */}
                        {mode === 'login' && (
                            <form onSubmit={handleLogin} className="space-y-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1.5">Email</label>
                                    <div className="relative">
                                        <Mail size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                                        <input
                                            type="email"
                                            name="email"
                                            autoComplete="email"
                                            value={email}
                                            onChange={(e) => setEmail(e.target.value)}
                                            className="w-full bg-white/5 border border-white/10 rounded-lg px-10 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition-colors"
                                            placeholder="admin@example.com"
                                            required
                                        />
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1.5">Password</label>
                                    <input
                                        type="password"
                                        name="password"
                                        autoComplete="current-password"
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition-colors"
                                        placeholder="••••••••"
                                        required
                                    />
                                </div>
                                <button
                                    type="submit"
                                    disabled={loading}
                                    className="w-full bg-brand-600 hover:bg-brand-700 text-white py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                >
                                    {loading ? (
                                        <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                    ) : (
                                        <><LogIn size={18} /> Sign In</>
                                    )}
                                </button>
                                <div className="text-center">
                                    <button
                                        type="button"
                                        onClick={() => switchMode('forgot')}
                                        className="text-sm text-brand-400 hover:text-brand-300 transition-colors"
                                    >
                                        Forgot Password?
                                    </button>
                                </div>
                            </form>
                        )}

                        {/* ── Register Form ───────────────────────────────── */}
                        {mode === 'register' && (
                            <form onSubmit={handleRegister} className="space-y-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1.5">Organization Name</label>
                                    <div className="relative">
                                        <Building size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                                        <input
                                            type="text"
                                            name="organizationName"
                                            autoComplete="organization"
                                            value={orgName}
                                            onChange={(e) => setOrgName(e.target.value)}
                                            className="w-full bg-white/5 border border-white/10 rounded-lg px-10 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition-colors"
                                            placeholder="e.g. Acme Security Operations"
                                            required
                                        />
                                    </div>
                                    <p className="text-xs text-gray-500 mt-1">
                                        Appears on reports and shared with your team members.
                                    </p>
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1.5">Full Name</label>
                                    <div className="relative">
                                        <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                                        <input
                                            type="text"
                                            name="fullName"
                                            autoComplete="name"
                                            value={fullName}
                                            onChange={(e) => setFullName(e.target.value)}
                                            className="w-full bg-white/5 border border-white/10 rounded-lg px-10 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition-colors"
                                            placeholder="John Doe"
                                            required
                                        />
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1.5">Email</label>
                                    <div className="relative">
                                        <Mail size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                                        <input
                                            type="email"
                                            name="email"
                                            autoComplete="email"
                                            value={email}
                                            onChange={(e) => setEmail(e.target.value)}
                                            className="w-full bg-white/5 border border-white/10 rounded-lg px-10 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition-colors"
                                            placeholder="admin@example.com"
                                            required
                                        />
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1.5">Password</label>
                                    <input
                                        type="password"
                                        name="password"
                                        autoComplete="new-password"
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition-colors"
                                        placeholder="••••••••"
                                        required
                                        aria-describedby="register-password-rules"
                                    />
                                    {/* Password requirements — always inline so rules don't vanish on blur */}
                                    <div id="register-password-rules"><PasswordRules password={password} /></div>
                                </div>
                                <button
                                    type="submit"
                                    disabled={loading || registered}
                                    className="w-full bg-brand-600 hover:bg-brand-700 text-white py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                >
                                    {loading ? (
                                        <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                    ) : (
                                        <><LogIn size={18} /> Create Organization</>
                                    )}
                                </button>
                                {registered && (
                                    <motion.div
                                        initial={{ opacity: 0, y: -4 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        className="mt-3 p-4 rounded-lg bg-green-500/10 border border-green-500/20 text-center"
                                    >
                                        <CheckCircle2 size={24} className="text-green-400 mx-auto mb-2" />
                                        <p className="text-green-400 text-sm font-medium">Organization created! Taking you to your dashboard&hellip;</p>
                                    </motion.div>
                                )}
                            </form>
                        )}

                        {/* ── Forgot Password Form ─────────────────────────── */}
                        {mode === 'forgot' && (
                            <form onSubmit={handleForgotPassword} className="space-y-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1.5">Email</label>
                                    <div className="relative">
                                        <Mail size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                                        <input
                                            type="email"
                                            name="email"
                                            autoComplete="email"
                                            value={email}
                                            onChange={(e) => setEmail(e.target.value)}
                                            className="w-full bg-white/5 border border-white/10 rounded-lg px-10 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition-colors"
                                            placeholder="admin@example.com"
                                            required
                                        />
                                    </div>
                                </div>
                                <button
                                    type="submit"
                                    disabled={loading}
                                    className="w-full bg-brand-600 hover:bg-brand-700 text-white py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                >
                                    {loading ? (
                                        <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                    ) : (
                                        <><Key size={18} /> Get Reset Token</>
                                    )}
                                </button>
                            </form>
                        )}

                        {/* ── Reset Password Form ──────────────────────────── */}
                        {mode === 'reset' && (
                            <form onSubmit={handleResetPassword} className="space-y-4">
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1.5">Reset Token</label>
                                    <input
                                        type="text"
                                        name="resetToken"
                                        autoComplete="one-time-code"
                                        value={resetToken}
                                        onChange={(e) => setResetToken(e.target.value)}
                                        className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition-colors font-mono text-sm"
                                        placeholder="Paste reset token here"
                                        required
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm text-gray-400 mb-1.5">New Password</label>
                                    <input
                                        type="password"
                                        name="newPassword"
                                        autoComplete="new-password"
                                        value={newPassword}
                                        onChange={(e) => setNewPassword(e.target.value)}
                                        className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-brand-500 transition-colors"
                                        placeholder="••••••••"
                                        required
                                        aria-describedby="reset-password-rules"
                                    />
                                    <div id="reset-password-rules"><PasswordRules password={newPassword} /></div>
                                </div>
                                <button
                                    type="submit"
                                    disabled={loading}
                                    className="w-full bg-brand-600 hover:bg-brand-700 text-white py-3 rounded-lg font-medium transition-colors flex items-center justify-center gap-2 disabled:opacity-50"
                                >
                                    {loading ? (
                                        <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                    ) : (
                                        <><Key size={18} /> Reset Password</>
                                    )}
                                </button>
                                {resetEmailSent && (
                                    <div className="text-center mt-2">
                                        {resendCooldown > 0 ? (
                                            <p className="text-xs text-gray-500">Resend token in {resendCooldown}s</p>
                                        ) : (
                                            <button
                                                type="button"
                                                onClick={() => { setMode('forgot'); handleForgotPassword(new Event('submit') as any) }}
                                                className="text-sm text-brand-400 hover:text-brand-300 transition-colors"
                                            >
                                                Resend token to {resetEmailSent}
                                            </button>
                                        )}
                                    </div>
                                )}
                            </form>
                        )}
                    </div>
                </motion.div>
            </div>
        </div>
    )
}

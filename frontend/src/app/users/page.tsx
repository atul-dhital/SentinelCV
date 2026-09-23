'use client'

import React, { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Users, Plus, Trash2, Shield, UserCheck, UserX, AlertCircle, CheckCircle, X, Crown, Mail, RefreshCw } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { userService, authService, UserInfo } from '@/services/api'
import { useConfirm } from '@/components/ui/ConfirmDialog'
import { useToast } from '@/components/ui/Toast'

export default function UsersPage() {
    const confirm = useConfirm()
    const toast = useToast()
    const [users, setUsers] = useState<UserInfo[]>([])
    const [currentUser, setCurrentUser] = useState<UserInfo | null>(null)
    const [loading, setLoading] = useState(true)
    const [showModal, setShowModal] = useState(false)
    const [saving, setSaving] = useState(false)
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
    const [isAdmin, setIsAdmin] = useState(false)
    const [fetchError, setFetchError] = useState<string | null>(null)

    const [formData, setFormData] = useState({
        email: '',
        full_name: '',
        password: '',
        role: 'staff',
    })

    useEffect(() => {
        fetchData()
    }, [])

    const fetchData = async () => {
        setFetchError(null)
        try {
            const [usersRes, meRes] = await Promise.all([
                userService.getUsers().catch(() => ({ data: [] })),
                authService.me().catch(() => ({ data: null })),
            ])
            setUsers(usersRes.data)
            setCurrentUser(meRes.data)
            setIsAdmin(meRes.data?.role === 'admin')
        } catch (err: any) {
            if (err.response?.status === 401) {
                window.location.href = '/login'
                return
            }
            if (err.response?.status === 403) {
                // Genuinely forbidden — not an admin
                setIsAdmin(false)
            } else {
                setFetchError(err.response?.data?.detail || err.message || 'Failed to load user data. Please try again.')
            }
            console.error('Failed to fetch users:', err)
        } finally {
            setLoading(false)
        }
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setSaving(true)
        setMessage(null)

        try {
            await userService.createUser({
                email: formData.email,
                full_name: formData.full_name,
                password: formData.password,
                role: formData.role,
            })

            setMessage({ type: 'success', text: 'User created successfully!' })
            setShowModal(false)
            setFormData({ email: '', full_name: '', password: '', role: 'staff' })
            fetchData()
        } catch (err: any) {
            setMessage({ type: 'error', text: err.response?.data?.detail || 'Failed to create user' })
        } finally {
            setSaving(false)
        }
    }

    const handleToggleRole = async (user: UserInfo) => {
        if (!isAdmin) return
        if (user.id === currentUser?.id) {
            setMessage({ type: 'error', text: 'Cannot change your own role' })
            return
        }

        const newRole = user.role === 'admin' ? 'staff' : 'admin'

        try {
            await userService.updateUser(user.id, { role: newRole })
            fetchData()
        } catch {
            setMessage({ type: 'error', text: 'Failed to update user role' })
        }
    }

    const handleToggleActive = async (user: UserInfo) => {
        if (!isAdmin) return
        if (user.id === currentUser?.id) {
            setMessage({ type: 'error', text: 'Cannot deactivate yourself' })
            return
        }

        try {
            await userService.updateUser(user.id, { is_active: !user.is_active })
            fetchData()
        } catch {
            setMessage({ type: 'error', text: 'Failed to update user status' })
        }
    }

    const handleDelete = async (userId: string) => {
        if (!isAdmin) return
        if (userId === currentUser?.id) {
            toast.error('Cannot delete yourself')
            return
        }

        const target = users.find(u => u.id === userId)
        const ok = await confirm({
            kind: 'danger',
            title: target ? `Delete ${target.full_name || target.email}?` : 'Delete user?',
            description: 'This permanently removes the user and revokes any active sessions. This action cannot be undone.',
            confirmLabel: 'Delete user',
            cancelLabel: 'Cancel',
        })
        if (!ok) return

        try {
            await userService.deleteUser(userId)
            toast.success('User deleted')
            fetchData()
        } catch {
            toast.error('Failed to delete user')
        }
    }

    const getRoleIcon = (role: string) => {
        if (role === 'admin') return <Crown size={14} className="text-yellow-400" />
        return <UserCheck size={14} className="text-gray-400" />
    }

    const getRoleBadge = (role: string) => {
        if (role === 'admin') {
            return <span className="text-xs bg-yellow-400/10 text-yellow-400 px-2 py-1 rounded">Admin</span>
        }
        return <span className="text-xs bg-gray-500/10 text-gray-400 px-2 py-1 rounded">Staff</span>
    }

    if (loading) {
        return (
            <div className="min-h-screen">
                <Navbar />
                <main className="pt-24 pb-20 px-6 container mx-auto">
                    <div className="space-y-4">
                        {[1, 2, 3].map((i) => (
                            <div key={i} className="glass-card p-6 animate-pulse h-20" />
                        ))}
                    </div>
                </main>
            </div>
        )
    }

    if (!isAdmin) {
        // If there was a fetch error, show a retry-able error instead of "Access Denied"
        if (fetchError) {
            return (
                <div className="min-h-screen">
                    <Navbar />
                    <main className="pt-24 pb-20 px-6 container mx-auto">
                        <div className="glass-card p-12 text-center">
                            <AlertCircle size={48} className="text-amber-400 mx-auto mb-4" />
                            <h2 className="text-2xl font-bold mb-2">Failed to Load</h2>
                            <p className="text-gray-400 mb-6">{fetchError}</p>
                            <button
                                onClick={() => { setLoading(true); fetchData(); }}
                                className="bg-brand-600 hover:bg-brand-700 text-white px-6 py-3 rounded-lg font-medium transition-colors inline-flex items-center gap-2"
                            >
                                <RefreshCw size={16} /> Retry
                            </button>
                        </div>
                    </main>
                </div>
            )
        }

        return (
            <div className="min-h-screen">
                <Navbar />
                <main className="pt-24 pb-20 px-6 container mx-auto">
                    <div className="glass-card p-12 text-center">
                        <Shield size={48} className="text-red-400 mx-auto mb-4" />
                        <h2 className="text-2xl font-bold mb-2">Access Denied</h2>
                        <p className="text-gray-400">You need admin privileges to access this page.</p>
                    </div>
                </main>
            </div>
        )
    }

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-20 px-6 container mx-auto">
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                >
                    <div className="flex justify-between items-end mb-10 gap-6">
                        <div>
                            <motion.h1
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="text-4xl font-extrabold mb-3 bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent"
                            >
                                User Management
                            </motion.h1>
                            <p className="text-gray-400 text-lg">Manage team members and their permissions.</p>
                        </div>
                        <button
                            onClick={() => setShowModal(true)}
                            className="bg-brand-600 hover:bg-brand-700 text-white px-6 py-3 rounded-lg font-medium transition-colors flex items-center gap-2"
                        >
                            <Plus size={18} /> Add User
                        </button>
                    </div>

                    {message && (
                        <div className={`mb-6 p-4 rounded-lg flex items-center gap-3 ${message.type === 'success'
                                ? 'bg-green-500/10 text-green-400 border border-green-500/20'
                                : 'bg-red-500/10 text-red-400 border border-red-500/20'
                            }`}>
                            {message.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
                            {message.text}
                        </div>
                    )}

                    <div className="glass-card overflow-hidden">
                        <table className="w-full">
                            <thead className="bg-gray-900/50">
                                <tr>
                                    <th className="text-left px-6 py-4 text-sm font-medium text-gray-400">User</th>
                                    <th className="text-left px-6 py-4 text-sm font-medium text-gray-400">Role</th>
                                    <th className="text-left px-6 py-4 text-sm font-medium text-gray-400">Status</th>
                                    <th className="text-left px-6 py-4 text-sm font-medium text-gray-400">Created</th>
                                    <th className="text-right px-6 py-4 text-sm font-medium text-gray-400">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-800">
                                {users.map((user) => (
                                    <motion.tr
                                        key={user.id}
                                        initial={{ opacity: 0 }}
                                        animate={{ opacity: 1 }}
                                        className="hover:bg-white/5 transition-colors"
                                    >
                                        <td className="px-6 py-4">
                                            <div className="flex items-center gap-3">
                                                <div className="w-10 h-10 bg-gray-800 rounded-full flex items-center justify-center">
                                                    <Users size={18} className="text-gray-400" />
                                                </div>
                                                <div>
                                                    <div className="font-medium">
                                                        {user.full_name}
                                                        {user.id === currentUser?.id && (
                                                            <span className="text-gray-500 text-sm ml-2">(You)</span>
                                                        )}
                                                    </div>
                                                    <div className="text-sm text-gray-500 flex items-center gap-1">
                                                        <Mail size={12} />
                                                        {user.email}
                                                    </div>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <div className="flex items-center gap-2">
                                                {getRoleIcon(user.role)}
                                                {getRoleBadge(user.role)}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4">
                                            {user.is_active ? (
                                                <span className="text-xs text-green-400 bg-green-400/10 px-2 py-1 rounded flex w-fit items-center gap-1">
                                                    <CheckCircle size={12} /> Active
                                                </span>
                                            ) : (
                                                <span className="text-xs text-red-400 bg-red-400/10 px-2 py-1 rounded flex w-fit items-center gap-1">
                                                    <X size={12} /> Inactive
                                                </span>
                                            )}
                                        </td>
                                        <td className="px-6 py-4 text-sm text-gray-400">
                                            {new Date(user.created_at).toLocaleDateString()}
                                        </td>
                                        <td className="px-6 py-4">
                                            <div className="flex justify-end gap-2">
                                                <button
                                                    onClick={() => handleToggleRole(user)}
                                                    disabled={user.id === currentUser?.id}
                                                    className="p-2 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
                                                    aria-label={`Toggle role for ${user.full_name || user.email}`}
                                                    title="Toggle role"
                                                >
                                                    <Shield size={16} className={user.role === 'admin' ? 'text-yellow-400' : 'text-gray-400'} />
                                                </button>
                                                <button
                                                    onClick={() => handleToggleActive(user)}
                                                    disabled={user.id === currentUser?.id}
                                                    className={`p-2 rounded-lg transition-colors ${user.is_active
                                                            ? 'bg-red-500/10 hover:bg-red-500/20 text-red-400'
                                                            : 'bg-green-500/10 hover:bg-green-500/20 text-green-400'
                                                        } disabled:opacity-50 disabled:cursor-not-allowed`}
                                                    aria-label={`${user.is_active ? 'Deactivate' : 'Activate'} user ${user.full_name || user.email}`}
                                                    title={user.is_active ? 'Deactivate' : 'Activate'}
                                                >
                                                    {user.is_active ? <UserX size={16} /> : <UserCheck size={16} />}
                                                </button>
                                                <button
                                                    onClick={() => handleDelete(user.id)}
                                                    disabled={user.id === currentUser?.id}
                                                    className="p-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                                    aria-label={`Delete user ${user.full_name || user.email}`}
                                                    title="Delete user"
                                                >
                                                    <Trash2 size={16} />
                                                </button>
                                            </div>
                                        </td>
                                    </motion.tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </motion.div>
            </main>

            {/* Create User Modal */}
            <AnimatePresence>
                {showModal && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"
                        onClick={() => setShowModal(false)}
                    >
                        <motion.div
                            initial={{ scale: 0.95, opacity: 0 }}
                            animate={{ scale: 1, opacity: 1 }}
                            exit={{ scale: 0.95, opacity: 0 }}
                            className="glass-card p-6 w-full max-w-lg"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <div className="flex justify-between items-center mb-6">
                                <h2 className="text-xl font-bold">Add New User</h2>
                                <button
                                    onClick={() => setShowModal(false)}
                                    className="text-gray-400 hover:text-white transition-colors"
                                >
                                    <X size={20} />
                                </button>
                            </div>

                            <form onSubmit={handleSubmit} className="space-y-6">
                                <div className="space-y-4">
                                    <div>
                                        <label className="block text-xs font-black text-gray-500 uppercase tracking-widest mb-2 px-1">
                                            Full Name
                                        </label>
                                        <div className="relative group">
                                            <input
                                                type="text"
                                                value={formData.full_name}
                                                onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                                                className="w-full bg-white/5 border border-white/10 rounded-2xl px-5 py-4 text-white focus:border-brand-500/50 focus:ring-4 focus:ring-brand-500/10 outline-none transition-all placeholder:text-gray-700"
                                                placeholder="e.g., Alexander Pierce"
                                                required
                                            />
                                            <Users className="absolute right-5 top-1/2 -translate-y-1/2 text-gray-700 group-focus-within:text-brand-500 transition-colors" size={20} />
                                        </div>
                                    </div>

                                    <div>
                                        <label className="block text-xs font-black text-gray-500 uppercase tracking-widest mb-2 px-1">
                                            Email Address
                                        </label>
                                        <div className="relative group">
                                            <input
                                                type="email"
                                                value={formData.email}
                                                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                                                className="w-full bg-white/5 border border-white/10 rounded-2xl px-5 py-4 text-white focus:border-brand-500/50 focus:ring-4 focus:ring-brand-500/10 outline-none transition-all placeholder:text-gray-700"
                                                placeholder="e.g., a.pierce@sentinel.cv"
                                                required
                                            />
                                            <Mail className="absolute right-5 top-1/2 -translate-y-1/2 text-gray-700 group-focus-within:text-brand-500 transition-colors" size={20} />
                                        </div>
                                    </div>

                                    <div>
                                        <label className="block text-xs font-black text-gray-500 uppercase tracking-widest mb-2 px-1">
                                            Access Credentials
                                        </label>
                                        <div className="relative group">
                                            <input
                                                type="password"
                                                value={formData.password}
                                                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                                                className="w-full bg-white/5 border border-white/10 rounded-2xl px-5 py-4 text-white focus:border-brand-500/50 focus:ring-4 focus:ring-brand-500/10 outline-none transition-all placeholder:text-gray-700"
                                                placeholder="••••••••"
                                                minLength={8}
                                                required
                                            />
                                            <Shield className="absolute right-5 top-1/2 -translate-y-1/2 text-gray-700 group-focus-within:text-brand-500 transition-colors" size={20} />
                                        </div>
                                        <div className="mt-3 flex items-center gap-2 px-1">
                                            <div className="flex-1 h-1 bg-white/5 rounded-full overflow-hidden">
                                                <div className={`h-full transition-all duration-500 ${formData.password.length >= 8 ? 'w-full bg-green-500/50' : 'w-1/3 bg-red-500/50'}`} />
                                            </div>
                                            <span className="text-[10px] font-bold text-gray-600 uppercase tracking-wider">Complexity</span>
                                        </div>
                                    </div>

                                    <div>
                                        <label className="block text-xs font-black text-gray-500 uppercase tracking-widest mb-2 px-1">
                                            Authorization Level
                                        </label>
                                        <select
                                            value={formData.role}
                                            onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                                            className="w-full bg-white/5 border border-white/10 rounded-2xl px-5 py-4 text-white focus:border-brand-500/50 focus:ring-4 focus:ring-brand-500/10 outline-none transition-all appearance-none cursor-pointer"
                                        >
                                            <option value="staff">Staff - Read Only Intelligence</option>
                                            <option value="admin">Administrator - Full System Access</option>
                                        </select>
                                    </div>
                                </div>

                                <div className="flex gap-4 pt-4">
                                    <button
                                        type="button"
                                        onClick={() => setShowModal(false)}
                                        className="flex-1 bg-white/5 hover:bg-white/10 text-white px-6 py-4 rounded-2xl font-bold transition-all border border-white/5"
                                    >
                                        Discard
                                    </button>
                                    <button
                                        type="submit"
                                        disabled={saving}
                                        className="flex-[2] bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white px-6 py-4 rounded-2xl font-bold transition-all shadow-xl shadow-brand-600/20"
                                    >
                                        {saving ? (
                                            <span className="flex items-center justify-center gap-2">
                                                <RefreshCw size={18} className="animate-spin" />
                                                Provisioning...
                                            </span>
                                        ) : 'Authorize User'}
                                    </button>
                                </div>
                            </form>

                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    )
}

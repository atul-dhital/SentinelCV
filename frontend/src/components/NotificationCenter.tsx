'use client'

import React, { useState, useEffect, useRef } from 'react'
import { Bell, Check, CheckCheck, Trash2, X } from 'lucide-react'
import { notificationService, Notification } from '@/services/api'

export default function NotificationCenter() {
    const [open, setOpen] = useState(false)
    const [notifications, setNotifications] = useState<Notification[]>([])
    const [unreadCount, setUnreadCount] = useState(0)
    const ref = useRef<HTMLDivElement>(null)

    useEffect(() => {
        fetchUnreadCount()
        const interval = setInterval(fetchUnreadCount, 30000) // poll every 30s as fallback
        return () => clearInterval(interval)
    }, [])

    // Subscribe to the global realtime event bus dispatched by the dashboard
    // WebSocket handler in page.tsx.  This avoids opening a second WebSocket
    // connection — all pages share the single connection on the dashboard.
    useEffect(() => {
        const handler = (e: Event) => {
            const msg = (e as CustomEvent).detail
            if (msg?.type === 'notification.created') {
                setUnreadCount(prev => prev + 1)
            }
        }
        window.addEventListener('sentinelcv:realtime', handler)
        return () => window.removeEventListener('sentinelcv:realtime', handler)
    }, [])

    useEffect(() => {
        if (open) fetchNotifications()
    }, [open])

    // Close on click outside
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
        }
        document.addEventListener('mousedown', handler)
        return () => document.removeEventListener('mousedown', handler)
    }, [])

    const fetchUnreadCount = async () => {
        try {
            const res = await notificationService.getUnreadCount()
            setUnreadCount(res.data.count)
        } catch { /* ignore */ }
    }

    const fetchNotifications = async () => {
        try {
            const res = await notificationService.list()
            setNotifications(res.data.items || res.data || [])
        } catch { /* ignore */ }
    }

    const markRead = async (id: string) => {
        try {
            await notificationService.markRead(id)
            setNotifications(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n))
            setUnreadCount(prev => Math.max(0, prev - 1))
        } catch { /* ignore */ }
    }

    const markAllRead = async () => {
        try {
            await notificationService.markAllRead()
            setNotifications(prev => prev.map(n => ({ ...n, is_read: true })))
            setUnreadCount(0)
        } catch { /* ignore */ }
    }

    const deleteNotification = async (id: string) => {
        try {
            await notificationService.delete(id)
            const removed = notifications.find(n => n.id === id)
            setNotifications(prev => prev.filter(n => n.id !== id))
            if (removed && !removed.is_read) setUnreadCount(prev => Math.max(0, prev - 1))
        } catch { /* ignore */ }
    }

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen(!open)}
                className="relative p-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
                title="Notifications"
            >
                <Bell size={18} />
                {unreadCount > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center">
                        {unreadCount > 9 ? '9+' : unreadCount}
                    </span>
                )}
            </button>

            {open && (
                <div className="absolute right-0 top-full mt-2 w-80 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl z-50 overflow-hidden">
                    <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
                        <span className="text-sm font-bold">Notifications</span>
                        <div className="flex items-center gap-2">
                            {unreadCount > 0 && (
                                <button
                                    onClick={markAllRead}
                                    className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1"
                                    title="Mark all as read"
                                >
                                    <CheckCheck size={14} /> Mark all read
                                </button>
                            )}
                            <button onClick={() => setOpen(false)} className="text-gray-500 hover:text-white">
                                <X size={16} />
                            </button>
                        </div>
                    </div>

                    <div className="max-h-80 overflow-y-auto">
                        {notifications.length === 0 ? (
                            <div className="px-4 py-8 text-center text-gray-500 text-sm">
                                No notifications yet
                            </div>
                        ) : (
                            notifications.map(n => (
                                <div
                                    key={n.id}
                                    className={`px-4 py-3 border-b border-gray-800 hover:bg-gray-800/50 transition-colors ${!n.is_read ? 'bg-brand-600/5' : ''}`}
                                >
                                    <div className="flex items-start justify-between gap-2">
                                        <div className="flex-1 min-w-0">
                                            <p className={`text-sm font-medium ${!n.is_read ? 'text-white' : 'text-gray-400'}`}>
                                                {n.title}
                                            </p>
                                            <p className="text-xs text-gray-500 mt-0.5 truncate">{n.message}</p>
                                            <p className="text-xs text-gray-600 mt-1">
                                                {new Date(n.created_at).toLocaleString()}
                                            </p>
                                        </div>
                                        <div className="flex items-center gap-1 shrink-0">
                                            {!n.is_read && (
                                                <button
                                                    onClick={() => markRead(n.id)}
                                                    className="p-1 text-gray-500 hover:text-green-400 transition-colors"
                                                    title="Mark as read"
                                                >
                                                    <Check size={14} />
                                                </button>
                                            )}
                                            <button
                                                onClick={() => deleteNotification(n.id)}
                                                className="p-1 text-gray-500 hover:text-red-400 transition-colors"
                                                title="Delete"
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}

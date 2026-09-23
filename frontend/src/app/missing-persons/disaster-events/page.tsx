'use client'

import { FormEvent, useEffect, useState } from 'react'
import { AlertTriangle, CalendarDays, MapPin, Plus, RefreshCw, ShieldCheck } from 'lucide-react'
import Navbar from '@/components/Navbar'
import { authService, missingPersonService, type DisasterEvent, type UserInfo } from '@/services/api'

const initialForm = { name: '', event_type: 'flood', affected_areas: '', starts_at: new Date().toISOString().slice(0, 16), notes: '' }
const eventTone: Record<DisasterEvent['status'], string> = {
    planned: 'bg-slate-400/10 text-slate-300 border-slate-400/30',
    active: 'bg-brand-500/10 text-brand-300 border-brand-500/30',
    closed: 'bg-emerald-400/10 text-emerald-300 border-emerald-400/30',
}

export default function DisasterEventsPage() {
    const [events, setEvents] = useState<DisasterEvent[]>([])
    const [form, setForm] = useState(initialForm)
    const [loading, setLoading] = useState(true)
    const [saving, setSaving] = useState(false)
    const [showForm, setShowForm] = useState(false)
    const [importFile, setImportFile] = useState<File | null>(null)
    const [importing, setImporting] = useState(false)
    const [message, setMessage] = useState<string | null>(null)
    const [user, setUser] = useState<UserInfo | null>(null)

    const load = async () => {
        setLoading(true)
        try {
            const [eventsResponse, userResponse] = await Promise.all([missingPersonService.listDisasterEvents(), authService.me()])
            setEvents(eventsResponse.data)
            setUser(userResponse.data)
        } catch (error: any) {
            if (error.response?.status === 401) window.location.assign('/login')
            else setMessage(error.response?.data?.detail || 'Could not load disaster events.')
        } finally { setLoading(false) }
    }

    useEffect(() => { load() }, [])

    const submit = async (event: FormEvent) => {
        event.preventDefault()
        setSaving(true)
        setMessage(null)
        try {
            await missingPersonService.createDisasterEvent({
                name: form.name.trim(),
                event_type: form.event_type,
                affected_areas: form.affected_areas.split(',').map(area => area.trim()).filter(Boolean),
                starts_at: new Date(form.starts_at).toISOString(),
                ends_at: null,
                notes: form.notes.trim() || null,
            })
            setForm(initialForm)
            setShowForm(false)
            setMessage('Disaster event created. You can now attach missing-person cases to it.')
            await load()
        } catch (error: any) {
            setMessage(error.response?.data?.detail || 'Could not create disaster event.')
        } finally { setSaving(false) }
    }

    const importCases = async () => {
        if (!importFile) return
        setImporting(true)
        setMessage(null)
        try {
            const result = await missingPersonService.importCases(importFile, events.find(event => event.status === 'active')?.id)
            setMessage('Import complete: ' + result.data.imported + ' cases added, ' + result.data.failed + ' rows skipped.')
            setImportFile(null)
        } catch (error: any) {
            setMessage(error.response?.data?.detail || 'Could not import CSV file.')
        } finally { setImporting(false) }
    }

    const canManage = user?.role === 'admin' || user?.role === 'staff'
    return (
        <div className="min-h-screen bg-gray-950 text-white">
            <Navbar />
            <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
                <section className="glass-card overflow-hidden p-6 sm:p-9">
                    <div className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
                        <div className="max-w-2xl">
                            <p className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.18em] text-brand-400"><ShieldCheck size={15} /> Disaster response workspace</p>
                            <h1 className="text-3xl font-black tracking-tight sm:text-4xl">Disaster events</h1>
                            <p className="mt-3 text-sm leading-6 text-gray-400">Create separate response operations. Missing reports, located-person records, and human-reviewed AI matches stay scoped to each event.</p>
                        </div>
                        <button onClick={() => setShowForm(value => !value)} className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white transition hover:bg-brand-500"><Plus size={17} /> New disaster event</button>
                    </div>
                </section>
                {message && <div className="mt-5 rounded-xl border border-brand-400/25 bg-brand-500/10 px-4 py-3 text-sm text-brand-200">{message}</div>}
                {showForm && <form onSubmit={submit} className="glass-card mt-6 p-5 sm:p-6">
                    <h2 className="text-lg font-bold">Create response event</h2>
                    <div className="mt-5 grid gap-4 md:grid-cols-2">
                        <label className="text-sm text-gray-300">Event name<input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="2026 Nepal Flood Response" className="mt-1.5 w-full rounded-xl border border-gray-700 bg-gray-950 px-3 py-2.5 text-white outline-none transition focus:border-brand-400" /></label>
                        <label className="text-sm text-gray-300">Disaster type<select value={form.event_type} onChange={e => setForm({ ...form, event_type: e.target.value })} className="mt-1.5 w-full rounded-xl border border-gray-700 bg-gray-950 px-3 py-2.5 text-white outline-none transition focus:border-brand-400"><option value="flood">Flood</option><option value="landslide">Landslide</option><option value="earthquake">Earthquake</option><option value="fire">Fire</option><option value="other">Other</option></select></label>
                        <label className="text-sm text-gray-300">Affected areas<input value={form.affected_areas} onChange={e => setForm({ ...form, affected_areas: e.target.value })} placeholder="Kathmandu, Kavrepalanchok, Sindhuli" className="mt-1.5 w-full rounded-xl border border-gray-700 bg-gray-950 px-3 py-2.5 text-white outline-none transition focus:border-brand-400" /></label>
                        <label className="text-sm text-gray-300">Response starts<input required type="datetime-local" value={form.starts_at} onChange={e => setForm({ ...form, starts_at: e.target.value })} className="mt-1.5 w-full rounded-xl border border-gray-700 bg-gray-950 px-3 py-2.5 text-white outline-none transition focus:border-brand-400" /></label>
                    </div>
                    <label className="mt-4 block text-sm text-gray-300">Operational notes<textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} placeholder="Shelters, hospitals, contact procedures, or response boundaries." className="mt-1.5 min-h-24 w-full rounded-xl border border-gray-700 bg-gray-950 px-3 py-2.5 text-white outline-none transition focus:border-brand-400" /></label>
                    <div className="mt-5 flex gap-3"><button disabled={saving} className="rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-brand-500 disabled:opacity-50">{saving ? 'Creating...' : 'Create event'}</button><button type="button" onClick={() => setShowForm(false)} className="rounded-xl border border-white/10 px-4 py-2.5 text-sm text-gray-300 transition hover:bg-white/5 hover:text-white">Cancel</button></div>
                </form>}
                <section className="glass-card mt-6 p-5 sm:p-6">
                    <h2 className="text-lg font-bold">Import many missing-person records</h2>
                    <p className="mt-1 text-sm text-gray-400">Upload CSV from a municipality, shelter, hospital, or field team. Required column: <code>full_name</code>.</p>
                    <p className="mt-1 text-xs text-gray-500">Optional: age, gender, last_seen_location, last_seen_at, clothing_description, distinguishing_marks, priority, status, reporter_name, reporter_email, reporter_phone.</p>
                    <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
                        <input type="file" accept=".csv,text/csv" onChange={e => setImportFile(e.target.files?.[0] || null)} className="block w-full text-sm text-gray-300 file:mr-4 file:rounded-lg file:border-0 file:bg-brand-500/15 file:px-3 file:py-2 file:font-semibold file:text-brand-300 hover:file:bg-brand-500/25" />
                        <button type="button" disabled={!importFile || importing || !canManage} onClick={importCases} className="shrink-0 rounded-xl border border-brand-400/40 px-4 py-2.5 text-sm font-bold text-brand-300 transition hover:bg-brand-500/10 disabled:cursor-not-allowed disabled:opacity-40">{importing ? 'Importing...' : 'Import CSV'}</button>
                    </div>
                    {!canManage && <p className="mt-3 text-xs text-amber-300">Sign in with a staff or admin account to create events or import cases.</p>}
                </section>
                <section className="mt-8">
                    <div className="mb-4 flex items-center justify-between"><h2 className="text-xl font-bold">Response operations</h2><button onClick={load} className="rounded-lg p-2 text-gray-400 transition hover:bg-white/5 hover:text-white" aria-label="Refresh events"><RefreshCw size={17} /></button></div>
                    {loading ? <p className="text-gray-400">Loading events...</p> : events.length === 0 ? <div className="rounded-2xl border border-dashed border-white/15 bg-white/[0.02] p-8 text-center"><AlertTriangle className="mx-auto text-brand-400" size={28} /><p className="mt-3 font-semibold">No disaster event yet</p><p className="mt-1 text-sm text-gray-400">Create an event before registering disaster cases.</p></div> :
                        <div className="grid gap-4 md:grid-cols-2">{events.map(event => <article key={event.id} className="glass-card glass-card-hover p-5"><div className="flex items-start justify-between gap-4"><div><p className="text-lg font-bold">{event.name}</p><p className="mt-1 capitalize text-sm text-brand-300">{event.event_type}</p></div><span className={'rounded-full border px-2.5 py-1 text-xs font-bold capitalize ' + eventTone[event.status]}>{event.status}</span></div><div className="mt-5 space-y-2 text-sm text-gray-300"><p className="flex gap-2"><CalendarDays size={16} className="shrink-0 text-gray-500" />{new Date(event.starts_at).toLocaleString()}</p><p className="flex gap-2"><MapPin size={16} className="shrink-0 text-gray-500" />{event.affected_areas?.join(', ') || 'Affected area not recorded'}</p></div></article>)}</div>}
                </section>
            </main>
        </div>
    )
}

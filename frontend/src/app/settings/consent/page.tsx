'use client';

import React, { Suspense, useState, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import { Search, ShieldCheck, ShieldX, RefreshCw, AlertCircle, CheckCircle2 } from 'lucide-react';
import Navbar from '@/components/Navbar';
import { visitorService, type Visitor } from '@/services/api';
import api from '@/services/api';

const CONSENT_TYPES = [
  { id: 'face_recognition', label: 'Face Recognition', description: 'Allow facial recognition for identification' },
  { id: 'tracking', label: 'Movement Tracking', description: 'Allow tracking across multiple cameras' },
  { id: 'analytics', label: 'Analytics', description: 'Allow usage in aggregate analytics reports' },
];

interface ConsentRecord {
  consent_type: string;
  consent_given: boolean;
  consent_date?: string;
  consent_withdrawn_date?: string;
}

// useSearchParams must live inside a component wrapped in <Suspense> to
// avoid "missing Suspense boundary" hydration errors in Next.js 13+ App Router.
function ConsentPortalInner() {
  const searchParams = useSearchParams();
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [visitors, setVisitors] = useState<Visitor[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedVisitor, setSelectedVisitor] = useState<Visitor | null>(null);
  const [consents, setConsents] = useState<Record<string, ConsentRecord>>({});
  const [loadingConsents, setLoadingConsents] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // If visitor_id is in the URL (deep-linked from visitor detail page), auto-load it.
  useEffect(() => {
    const visitorId = searchParams.get('visitor_id');
    if (!visitorId) return;
    visitorService.getVisitor(visitorId)
      .then(res => loadConsents(res.data))
      .catch(() => {/* visitor not found or no permission */});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Fetch visitors matching search
  useEffect(() => {
    if (!debouncedSearch.trim()) { setVisitors([]); return; }
    setLoading(true);
    visitorService.getVisitors({ search: debouncedSearch, limit: 10 })
      .then(res => setVisitors(res.data.items))
      .catch(() => setVisitors([]))
      .finally(() => setLoading(false));
  }, [debouncedSearch]);

  // Fetch consent records for selected visitor
  const loadConsents = async (visitor: Visitor) => {
    setSelectedVisitor(visitor);
    setLoadingConsents(true);
    setConsents({});
    const map: Record<string, ConsentRecord> = {};
    await Promise.all(
      CONSENT_TYPES.map(async (ct) => {
        try {
          const res = await api.get<ConsentRecord>(
            `/gdpr/consent/${ct.id}?visitor_id=${visitor.id}`
          );
          map[ct.id] = res.data;
        } catch (e: any) {
          if (e?.response?.status === 404) {
            map[ct.id] = { consent_type: ct.id, consent_given: false };
          }
        }
      })
    );
    setConsents(map);
    setLoadingConsents(false);
  };

  const handleGrant = async (consentType: string) => {
    if (!selectedVisitor) return;
    setSaving(consentType);
    try {
      await api.post(`/gdpr/consent?visitor_id=${selectedVisitor.id}`, {
        consent_type: consentType,
        consent_given: true,
      });
      await loadConsents(selectedVisitor);
      setMessage({ type: 'success', text: `Consent granted for ${consentType.replace(/_/g, ' ')}.` });
    } catch {
      setMessage({ type: 'error', text: 'Failed to grant consent.' });
    } finally {
      setSaving(null);
    }
  };

  const handleWithdraw = async (consentType: string) => {
    if (!selectedVisitor) return;
    setSaving(consentType);
    try {
      await api.post(`/gdpr/consent/${consentType}/withdraw?visitor_id=${selectedVisitor.id}`);
      await loadConsents(selectedVisitor);
      setMessage({ type: 'success', text: `Consent withdrawn for ${consentType.replace(/_/g, ' ')}.` });
    } catch {
      setMessage({ type: 'error', text: 'Failed to withdraw consent.' });
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className="min-h-screen">
      <Navbar />
      <main className="pt-24 pb-20 px-6 container mx-auto max-w-4xl">
        <div className="mb-8">
          <h1 className="text-2xl font-bold">Visitor Consent Management</h1>
          <p className="text-sm text-gray-400 mt-1">
            Manage visitor data-processing consent records in accordance with GDPR Article 7.
          </p>
        </div>

        {message && (
          <div className={`mb-6 flex items-center gap-3 p-4 rounded-lg border text-sm ${
            message.type === 'success'
              ? 'bg-green-900/20 border-green-700 text-green-300'
              : 'bg-red-900/20 border-red-700 text-red-300'
          }`}>
            {message.type === 'success' ? <CheckCircle2 size={16} /> : <AlertCircle size={16} />}
            {message.text}
            <button onClick={() => setMessage(null)} className="ml-auto text-gray-400 hover:text-white">✕</button>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Left: Visitor search */}
          <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">Find Visitor</h2>
            <div className="relative mb-3">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by name, email, or phone…"
                className="w-full pl-9 pr-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500/40"
              />
            </div>

            {loading && (
              <div className="flex items-center gap-2 text-sm text-gray-400 py-2">
                <RefreshCw size={14} className="animate-spin" /> Searching…
              </div>
            )}

            <div className="space-y-1 max-h-64 overflow-y-auto">
              {visitors.map((v) => (
                <button
                  key={v.id}
                  onClick={() => loadConsents(v)}
                  className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors ${
                    selectedVisitor?.id === v.id
                      ? 'bg-brand-500/20 border border-brand-500/30 text-brand-300'
                      : 'hover:bg-gray-800 text-gray-300'
                  }`}
                >
                  <div className="font-medium">{v.name || '(unnamed)'}</div>
                  {v.email && <div className="text-xs text-gray-500">{v.email}</div>}
                </button>
              ))}
              {!loading && debouncedSearch && visitors.length === 0 && (
                <p className="text-sm text-gray-500 py-2 text-center">No visitors found</p>
              )}
              {!debouncedSearch && (
                <p className="text-xs text-gray-600 text-center py-3">Type to search visitors</p>
              )}
            </div>
          </div>

          {/* Right: Consent records */}
          <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
            <h2 className="text-sm font-semibold text-gray-300 mb-3">
              {selectedVisitor ? `Consents for ${selectedVisitor.name || 'visitor'}` : 'Select a visitor'}
            </h2>

            {!selectedVisitor && (
              <p className="text-xs text-gray-600 text-center py-8">
                Select a visitor on the left to manage their consent records
              </p>
            )}

            {loadingConsents && (
              <div className="flex items-center gap-2 text-sm text-gray-400 py-4">
                <RefreshCw size={14} className="animate-spin" /> Loading consents…
              </div>
            )}

            {selectedVisitor && !loadingConsents && (
              <div className="space-y-3">
                {CONSENT_TYPES.map((ct) => {
                  const record = consents[ct.id];
                  const granted = record?.consent_given ?? false;
                  const isSaving = saving === ct.id;
                  return (
                    <div key={ct.id} className="flex items-center justify-between p-3 rounded-lg bg-gray-800 border border-gray-700">
                      <div>
                        <div className="text-sm font-medium text-gray-200">{ct.label}</div>
                        <div className="text-xs text-gray-500">{ct.description}</div>
                        {granted && record?.consent_date && (
                          <div className="text-xs text-green-500 mt-0.5">
                            Granted {new Date(record.consent_date).toLocaleDateString()}
                          </div>
                        )}
                        {!granted && record?.consent_withdrawn_date && (
                          <div className="text-xs text-red-400 mt-0.5">
                            Withdrawn {new Date(record.consent_withdrawn_date).toLocaleDateString()}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2 ml-3 shrink-0">
                        <span className={`flex items-center gap-1 text-xs font-semibold ${granted ? 'text-green-400' : 'text-gray-500'}`}>
                          {granted ? <ShieldCheck size={13} /> : <ShieldX size={13} />}
                          {granted ? 'Granted' : 'Not set'}
                        </span>
                        {granted ? (
                          <button
                            disabled={isSaving}
                            onClick={() => handleWithdraw(ct.id)}
                            className="px-2.5 py-1 rounded bg-red-900/40 hover:bg-red-900/70 text-red-300 text-xs disabled:opacity-50 transition-colors"
                          >
                            {isSaving ? '…' : 'Withdraw'}
                          </button>
                        ) : (
                          <button
                            disabled={isSaving}
                            onClick={() => handleGrant(ct.id)}
                            className="px-2.5 py-1 rounded bg-green-900/40 hover:bg-green-900/70 text-green-300 text-xs disabled:opacity-50 transition-colors"
                          >
                            {isSaving ? '…' : 'Grant'}
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

export default function ConsentPortalPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    }>
      <ConsentPortalInner />
    </Suspense>
  );
}

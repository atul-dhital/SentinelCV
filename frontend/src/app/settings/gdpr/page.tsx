"use client";

import React, { useState, useEffect } from "react";
import { AlertCircle, Download, Trash2, RefreshCw, Clock, CheckCircle2, Layers } from "lucide-react";
import {
  authService,
  gdprService,
  type GdprRequest,
  type GdprRetentionPolicy,
} from "@/services/api";

type PolicyFormState = {
  data_type: GdprRetentionPolicy["data_type"];
  retention_days: number;
  auto_delete_enabled: boolean;
};

export default function GDPRSettingsPage() {
  const [policies, setPolicies] = useState<GdprRetentionPolicy[]>([]);
  const [requests, setRequests] = useState<GdprRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [showPolicyForm, setShowPolicyForm] = useState(false);
  const [organizationId, setOrganizationId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [confirmDeleteText, setConfirmDeleteText] = useState('');
  const [bulkProcessing, setBulkProcessing] = useState(false);

  const [policyForm, setPolicyForm] = useState<PolicyFormState>({
    data_type: "face_images",
    retention_days: 90,
    auto_delete_enabled: true,
  });

  const fetchPolicies = async (orgId: string) => {
    try {
      const response = await gdprService.listPolicies(orgId);
      setPolicies(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    }
  };

  const fetchRequests = async () => {
    try {
      const response = await gdprService.listPendingRequests();
      setRequests(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    }
  };

  useEffect(() => {
    let isMounted = true;
    Promise.all([authService.me(), fetchRequests()])
      .then(([meResponse]) => {
        if (!isMounted) return;
        const { organization_id: orgId, role } = meResponse.data;
        setOrganizationId(orgId);
        setIsAdmin(role === "admin");
        return fetchPolicies(orgId);
      })
      .catch((err) => {
        if (!isMounted) return;
        setError(err instanceof Error ? err.message : "An error occurred");
      })
      .finally(() => {
        if (isMounted) {
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const handleCreatePolicy = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!organizationId) {
      setError("Organization context unavailable");
      return;
    }
    // Duplicate detection
    const existing = policies.find(p => p.data_type === policyForm.data_type);
    if (existing) {
      setError(`A policy for "${policyForm.data_type}" already exists. Edit or delete the existing policy instead.`);
      return;
    }
    try {
      await gdprService.updatePolicies(organizationId, [policyForm]);

      setShowPolicyForm(false);
      setPolicyForm({
        data_type: "face_images",
        retention_days: 90,
        auto_delete_enabled: true,
      });
      fetchPolicies(organizationId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "pending":
        return <span className="px-2 py-1 rounded bg-yellow-100 text-yellow-800 text-xs">Pending</span>;
      case "processing":
        return <span className="px-2 py-1 rounded bg-blue-100 text-blue-800 text-xs">Processing</span>;
      case "completed":
        return <span className="px-2 py-1 rounded bg-green-100 text-green-800 text-xs">Completed</span>;
      default:
        return null;
    }
  };

  // Compliance summary derived from current state
  const hasRetentionPolicy = policies.length > 0
  const autoDeleteEnabled = policies.some(p => p.auto_delete_enabled)
  const pendingCount = requests.filter(r => r.status === 'pending').length
  const complianceScore = [hasRetentionPolicy, autoDeleteEnabled, pendingCount === 0].filter(Boolean).length

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">GDPR Compliance</h1>
        <p className="mt-2 text-gray-600">
          Manage data retention policies, consent records, and data requests
        </p>
      </div>

      {/* Compliance Status Panel */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-lg font-bold text-gray-900 flex items-center gap-2">
              <span className={`w-3 h-3 rounded-full inline-block ${complianceScore === 3 ? 'bg-green-500' : complianceScore >= 1 ? 'bg-yellow-500' : 'bg-red-500'}`} />
              Compliance Status
            </h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {complianceScore === 3 ? 'GDPR-Ready Configuration — all controls active' : `${complianceScore} of 3 controls configured`}
            </p>
          </div>
          <button
            onClick={() => {
              const csvContent = [
                'Control,Status',
                `Retention Policy,${hasRetentionPolicy ? 'Configured' : 'Missing'}`,
                `Auto-Delete,${autoDeleteEnabled ? 'Enabled' : 'Disabled'}`,
                `Pending Requests,${pendingCount === 0 ? 'None' : `${pendingCount} pending`}`,
                `Report Date,${new Date().toISOString().slice(0, 10)}`,
              ].join('\n')
              const blob = new Blob([csvContent], { type: 'text/csv' })
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              a.download = `gdpr-compliance-report-${new Date().toISOString().slice(0, 10)}.csv`
              a.click()
              URL.revokeObjectURL(url)
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-200 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
          >
            <Download className="w-4 h-4" />
            Download Report
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className={`rounded-xl p-4 border ${hasRetentionPolicy ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'}`}>
            <p className="text-xs font-bold uppercase tracking-widest mb-1 ${hasRetentionPolicy ? 'text-green-600' : 'text-red-600'}">
              {hasRetentionPolicy ? '✓' : '✗'} Retention Policy
            </p>
            <p className="text-sm font-semibold text-gray-900">
              {hasRetentionPolicy ? `${policies.length} polic${policies.length === 1 ? 'y' : 'ies'} configured` : 'Not configured'}
            </p>
            <p className="text-xs text-gray-500 mt-1">
              {hasRetentionPolicy ? 'Data retention rules are active' : 'Add a retention policy below'}
            </p>
          </div>

          <div className={`rounded-xl p-4 border ${autoDeleteEnabled ? 'border-green-200 bg-green-50' : 'border-yellow-200 bg-yellow-50'}`}>
            <p className="text-xs font-bold uppercase tracking-widest mb-1">
              {autoDeleteEnabled ? '✓' : '⚠'} Auto-Delete
            </p>
            <p className="text-sm font-semibold text-gray-900">
              {autoDeleteEnabled ? 'Enabled on at least one policy' : 'Not enabled'}
            </p>
            <p className="text-xs text-gray-500 mt-1">Automatic deletion when retention period expires</p>
          </div>

          <div className={`rounded-xl p-4 border ${pendingCount === 0 ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'}`}>
            <p className="text-xs font-bold uppercase tracking-widest mb-1">
              {pendingCount === 0 ? '✓' : '!'} Deletion Queue
            </p>
            <p className="text-sm font-semibold text-gray-900">
              {pendingCount === 0 ? 'No pending requests' : `${pendingCount} request${pendingCount === 1 ? '' : 's'} pending`}
            </p>
            <p className="text-xs text-gray-500 mt-1">GDPR erasure and export requests</p>
          </div>
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 p-4 flex items-start">
          <AlertCircle className="w-5 h-5 text-red-600 mt-0.5 mr-3" />
          <div>
            <h3 className="font-semibold text-red-900">Error</h3>
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        </div>
      )}

      {/* Retention Policies Section */}
      <div className="space-y-4">
        <div className="flex justify-between items-center">
          <h2 className="text-2xl font-bold text-gray-900">Data Retention Policies</h2>
          {isAdmin && (
            <button
              onClick={() => setShowPolicyForm(true)}
              className="px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700"
            >
              Add Policy
            </button>
          )}
        </div>

        <p className="text-gray-600">
          Define how long different types of data are retained before automatic deletion
        </p>

        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          {loading ? (
            <div className="p-8 text-center">
              <RefreshCw className="w-6 h-6 animate-spin mx-auto text-gray-400" />
            </div>
          ) : policies.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              <p>No retention policies configured</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Data Type
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Retention Period
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Auto-Delete
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {policies.map((policy) => (
                  <tr key={policy.id}>
                    <td className="px-6 py-4 text-sm font-medium text-gray-900">
                      {policy.data_type.replace(/_/g, " ")}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {policy.retention_days} days
                    </td>
                    <td className="px-6 py-4 text-sm">
                      <span
                        className={`inline-block px-2 py-1 rounded text-xs font-semibold ${
                          policy.auto_delete_enabled
                            ? "bg-green-100 text-green-800"
                            : "bg-gray-100 text-gray-800"
                        }`}
                      >
                        {policy.auto_delete_enabled ? "Enabled" : "Disabled"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Pending Requests Section */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Pending GDPR Requests</h2>
            <p className="text-gray-600 mt-1">
              Data export, deletion, and consent withdrawal requests awaiting processing
            </p>
          </div>
          {isAdmin && requests.filter(r => r.request_type === 'data_deletion' && r.status === 'pending').length > 1 && (
            <button
              disabled={bulkProcessing}
              onClick={async () => {
                const pendingDeletions = requests.filter(
                  r => r.request_type === 'data_deletion' && r.status === 'pending'
                );
                if (!pendingDeletions.length) return;
                setBulkProcessing(true);
                try {
                  const ids = pendingDeletions.map(r => r.id);
                  const res = await gdprService.bulkProcess(ids, 'approve');
                  fetchRequests();
                  setError(null);
                } catch { setError('Bulk processing failed.'); }
                finally { setBulkProcessing(false); }
              }}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-medium disabled:opacity-50 transition-colors"
            >
              <Layers className="w-4 h-4" />
              {bulkProcessing ? 'Processing…' : `Approve All Deletions (${requests.filter(r => r.request_type === 'data_deletion' && r.status === 'pending').length})`}
            </button>
          )}
        </div>

        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          {loading ? (
            <div className="p-8 text-center">
              <RefreshCw className="w-6 h-6 animate-spin mx-auto text-gray-400" />
            </div>
          ) : requests.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              <p>No pending requests</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Visitor ID
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Request Type
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Requested
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {requests.map((request) => (
                  <tr key={request.id}>
                    <td className="px-6 py-4 text-sm font-mono text-gray-600">
                      {request.visitor_id.substring(0, 8)}...
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900 capitalize">
                      {request.request_type.replace(/_/g, " ")}
                    </td>
                    <td className="px-6 py-4 text-sm">
                      {getStatusBadge(request.status)}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {new Date(request.request_date).toLocaleDateString()}
                    </td>
                    <td className="px-6 py-4 text-sm flex gap-2">
                      {request.request_type === "data_export" &&
                        request.response_file_url && (
                          <button className="text-blue-600 hover:text-blue-700 flex items-center">
                            <Download className="w-4 h-4 mr-1" />
                            Download
                          </button>
                        )}
                      <button className="text-blue-600 hover:text-blue-700">
                        View Details
                      </button>
                      {isAdmin && request.request_type === 'data_deletion' && request.status === 'pending' && (
                        confirmDeleteId === request.id ? (
                          <div className="flex items-center gap-2">
                            <input
                              type="text"
                              value={confirmDeleteText}
                              onChange={(e) => setConfirmDeleteText(e.target.value)}
                              placeholder="Type DELETE to confirm"
                              className="border border-red-300 rounded px-2 py-1 text-xs w-36"
                            />
                            <button
                              disabled={confirmDeleteText !== 'DELETE'}
                              onClick={async () => {
                                try {
                                  await gdprService.processRequest(request.id, { action: 'approve' });
                                  setConfirmDeleteId(null);
                                  setConfirmDeleteText('');
                                  fetchRequests();
                                } catch { setError('Failed to process deletion request'); }
                              }}
                              className="text-red-600 hover:text-red-700 text-xs font-bold disabled:opacity-30"
                            >
                              Confirm
                            </button>
                            <button onClick={() => { setConfirmDeleteId(null); setConfirmDeleteText('') }} className="text-gray-400 text-xs">Cancel</button>
                          </div>
                        ) : (
                          <button onClick={() => setConfirmDeleteId(request.id)} className="text-red-600 hover:text-red-700 flex items-center">
                            <Trash2 className="w-4 h-4 mr-1" />
                            Process Delete
                          </button>
                        )
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Add Policy Modal */}
      {showPolicyForm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg max-w-md w-full mx-4 p-6">
            <h2 className="text-2xl font-bold text-gray-900 mb-6">
              Add Retention Policy
            </h2>

            <form onSubmit={handleCreatePolicy} className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Data Type
                </label>
                <select
                  value={policyForm.data_type}
                  onChange={(e) =>
                    setPolicyForm({
                      ...policyForm,
                      data_type: e.target.value as PolicyFormState["data_type"],
                    })
                  }
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                >
                  <option value="face_images">Face Images</option>
                  <option value="face_embeddings">Face Embeddings</option>
                  <option value="logs">Detection Logs</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Retention Period (days)
                </label>
                <input
                  type="number"
                  min="1"
                  value={policyForm.retention_days}
                  onChange={(e) =>
                    setPolicyForm({
                      ...policyForm,
                      retention_days: parseInt(e.target.value),
                    })
                  }
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  required
                />
                <p className="text-xs text-gray-500 mt-1">
                  Data will be automatically deleted after this period
                </p>
              </div>

              <div className="flex items-center">
                <input
                  type="checkbox"
                  checked={policyForm.auto_delete_enabled}
                  onChange={(e) =>
                    setPolicyForm({
                      ...policyForm,
                      auto_delete_enabled: e.target.checked,
                    })
                  }
                  className="w-4 h-4 text-blue-600 rounded"
                />
                <label className="ml-2 text-sm text-gray-700">
                  Enable automatic deletion
                </label>
              </div>

              <div className="flex gap-4 justify-end">
                <button
                  type="button"
                  onClick={() => setShowPolicyForm(false)}
                  className="px-6 py-2 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-6 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700"
                >
                  Create Policy
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

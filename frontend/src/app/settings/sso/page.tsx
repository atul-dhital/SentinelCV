"use client";

import React, { useState, useEffect } from "react";
import {
  AlertCircle,
  Plus,
  Edit2,
  Trash2,
  RefreshCw,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import {
  authService,
  ssoService,
  type SsoProvider,
  type SsoProviderPayload,
} from "@/services/api";
import { useConfirm } from "@/components/ui/ConfirmDialog";

type SSOFormState = SsoProviderPayload & {
  provider_name: string;
  entity_id: string;
  sso_url: string;
  certificate: string;
};

export default function SSOSettingsPage() {
  const confirm = useConfirm();
  const [providers, setProviders] = useState<SsoProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [showFormModal, setShowFormModal] = useState(false);
  const [editFormModal, setEditingModal] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<SsoProvider | null>(
    null
  );

  const [formData, setFormData] = useState<SSOFormState>({
    provider_type: "saml",
    provider_name: "",
    entity_id: "",
    sso_url: "",
    certificate: "",
  });

  const fetchProviders = async () => {
    try {
      setLoading(true);
      const response = await ssoService.listProviders();
      setProviders(response.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    authService.me()
      .then((res) => { setIsAdmin(res.data.role === "admin"); })
      .catch(() => {});
    fetchProviders();
  }, []);

  const handleCreateProvider = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await ssoService.createProvider(formData);

      setShowFormModal(false);
      setFormData({
        provider_type: "saml",
        provider_name: "",
        entity_id: "",
        sso_url: "",
        certificate: "",
      });
      fetchProviders();
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    }
  };

  const handleDeleteProvider = async (providerId: string) => {
    const target = providers.find(p => p.id === providerId);
    const ok = await confirm({
      kind: "danger",
      title: target ? `Delete provider "${target.provider_name}"?` : "Delete provider?",
      description: "Users who authenticate via this provider will no longer be able to sign in.",
      confirmLabel: "Delete provider",
    });
    if (!ok) return;

    try {
      await ssoService.deleteProvider(providerId);
      fetchProviders();
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    }
  };

  const toggleActive = async (provider: SsoProvider) => {
    try {
      await ssoService.updateProvider(provider.id, { active: !provider.active });
      fetchProviders();
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    }
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">SSO Configuration</h1>
          <p className="mt-2 text-gray-600">
            Configure SAML, OAuth2, or OpenID Connect providers for enterprise authentication
          </p>
        </div>
        {isAdmin && (
          <button
            onClick={() => setShowFormModal(true)}
            className="inline-flex items-center px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700"
          >
            <Plus className="w-5 h-5 mr-2" />
            Add Provider
          </button>
        )}
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

      {/* Providers List */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center">
            <RefreshCw className="w-6 h-6 animate-spin mx-auto text-gray-400" />
          </div>
        ) : providers.length === 0 ? (
          <div className="p-8 text-center text-gray-500">
            <p>No SSO providers configured yet</p>
            <p className="text-sm mt-2">Click "Add Provider" to create one</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Provider Name
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Type
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Entity ID
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-sm font-semibold text-gray-700">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {providers.map((provider) => (
                  <tr key={provider.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 text-sm font-medium text-gray-900">
                      {provider.provider_name}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      <span className="inline-block px-2 py-1 rounded bg-blue-100 text-blue-800 text-xs font-semibold">
                        {provider.provider_type.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      {provider.entity_id || "—"}
                    </td>
                    <td className="px-6 py-4 text-sm">
                      {provider.active ? (
                        <div className="flex items-center text-green-700">
                          <CheckCircle2 className="w-4 h-4 mr-2" />
                          <span>Active</span>
                        </div>
                      ) : (
                        <div className="flex items-center text-gray-500">
                          <XCircle className="w-4 h-4 mr-2" />
                          <span>Inactive</span>
                        </div>
                      )}
                    </td>
                    <td className="px-6 py-4 text-sm flex gap-2">
                      {isAdmin ? (
                        <>
                          <button
                            onClick={() => toggleActive(provider)}
                            className="text-blue-600 hover:text-blue-700"
                          >
                            {provider.active ? "Deactivate" : "Activate"}
                          </button>
                          <button
                            onClick={() => {
                              setSelectedProvider(provider);
                              setEditingModal(true);
                            }}
                            className="text-blue-600 hover:text-blue-700"
                          >
                            <Edit2 className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDeleteProvider(provider.id)}
                            className="text-red-600 hover:text-red-700"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </>
                      ) : (
                        <span className="text-gray-400 text-xs">View only</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add Provider Modal */}
      {showFormModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg max-w-2xl w-full mx-4 p-6">
            <h2 className="text-2xl font-bold text-gray-900 mb-6">
              Add SSO Provider
            </h2>

            <form onSubmit={handleCreateProvider} className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Provider Type
                </label>
                <select
                  value={formData.provider_type}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      provider_type: e.target.value as SSOFormState["provider_type"],
                    })
                  }
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="saml">SAML 2.0</option>
                  <option value="oauth2">OAuth 2.0</option>
                  <option value="openid">OpenID Connect</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Provider Name
                </label>
                <input
                  type="text"
                  value={formData.provider_name}
                  onChange={(e) =>
                    setFormData({...formData, provider_name: e.target.value})
                  }
                  placeholder="e.g., Okta, Azure AD"
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Entity ID / Issuer
                </label>
                <input
                  type="text"
                  value={formData.entity_id}
                  onChange={(e) =>
                    setFormData({...formData, entity_id: e.target.value})
                  }
                  placeholder="e.g., https://example.okta.com"
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  SSO URL
                </label>
                <input
                  type="url"
                  value={formData.sso_url}
                  onChange={(e) =>
                    setFormData({...formData, sso_url: e.target.value})
                  }
                  placeholder="https://example.okta.com/app/amazon_aws/..."
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  X.509 Certificate (SAML)
                </label>
                <textarea
                  value={formData.certificate}
                  onChange={(e) =>
                    setFormData({...formData, certificate: e.target.value})
                  }
                  placeholder="Paste certificate content here"
                  rows={6}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 font-mono text-sm"
                />
              </div>

              <div className="flex gap-4 justify-end">
                <button
                  type="button"
                  onClick={() => setShowFormModal(false)}
                  className="px-6 py-2 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-6 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700"
                >
                  Create Provider
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

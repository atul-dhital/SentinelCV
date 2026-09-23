"use client";

import React, { useEffect, useState, type JSX } from "react";
import {
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  Save,
  Server,
  Shield,
  Users,
} from "lucide-react";

import {
  ldapService,
  LdapConfig,
  LdapConfigPayload,
  LdapSyncLog,
} from "@/services/api";

type MessageState = { type: "success" | "error" | "info"; text: string };

type LdapFormState = {
  ldap_server: string;
  ldap_port: number;
  use_ssl: boolean;
  bind_dn: string;
  user_search_base: string;
  group_search_base: string;
  user_attribute: string;
  group_attribute: string;
  active: boolean;
};

const defaultFormState: LdapFormState = {
  ldap_server: "",
  ldap_port: 389,
  use_ssl: false,
  bind_dn: "",
  user_search_base: "",
  group_search_base: "",
  user_attribute: "uid",
  group_attribute: "cn",
  active: false,
};

const formatTimestamp = (value?: string | null) => {
  if (!value) return "Never";
  return new Date(value).toLocaleString();
};

export default function LdapSettingsPage(): JSX.Element {
  const [config, setConfig] = useState<LdapConfig | null>(null);
  const [logs, setLogs] = useState<LdapSyncLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<MessageState | null>(null);
  const [formData, setFormData] = useState<LdapFormState>(defaultFormState);
  const [bindPassword, setBindPassword] = useState("");

  const loadData = async () => {
    setLoading(true);
    try {
      const [configResponse, logResponse] = await Promise.all([
        ldapService.getConfig().catch(() => ({ data: null })),
        ldapService.listSyncLogs(25).catch(() => ({ data: [] })),
      ]);
      const loadedConfig = configResponse.data;
      setConfig(loadedConfig);
      setFormData(
        loadedConfig
          ? {
              ldap_server: loadedConfig.ldap_server,
              ldap_port: loadedConfig.ldap_port,
              use_ssl: loadedConfig.use_ssl,
              bind_dn: loadedConfig.bind_dn ?? "",
              user_search_base: loadedConfig.user_search_base,
              group_search_base: loadedConfig.group_search_base ?? "",
              user_attribute: loadedConfig.user_attribute,
              group_attribute: loadedConfig.group_attribute,
              active: loadedConfig.active,
            }
          : defaultFormState
      );
      const logData = logResponse.data as any;
      setLogs(logData?.items || []);
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to load LDAP settings",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const buildPayload = (): LdapConfigPayload => {
    return {
      ldap_server: formData.ldap_server.trim(),
      ldap_port: formData.ldap_port,
      use_ssl: formData.use_ssl,
      bind_dn: formData.bind_dn.trim() || null,
      user_search_base: formData.user_search_base.trim(),
      group_search_base: formData.group_search_base.trim() || null,
      user_attribute: formData.user_attribute.trim() || "uid",
      group_attribute: formData.group_attribute.trim() || "cn",
      active: formData.active,
    };
  };

  const handleSave = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage(null);

    if (!formData.ldap_server.trim() || !formData.user_search_base.trim()) {
      setMessage({ type: "error", text: "LDAP server and user base DN are required." });
      return;
    }
    if (formData.ldap_port < 1 || formData.ldap_port > 65535) {
      setMessage({ type: "error", text: "LDAP port must be between 1 and 65535." });
      return;
    }

    setSaving(true);
    try {
      const basePayload = buildPayload();
      const payload: LdapConfigPayload = bindPassword.trim()
        ? { ...basePayload, bind_password: bindPassword.trim() }
        : basePayload;

      const response = config
        ? await ldapService.updateConfig(config.id, payload)
        : await ldapService.createConfig(payload);

      setConfig(response.data);
      setFormData({
        ldap_server: response.data.ldap_server,
        ldap_port: response.data.ldap_port,
        use_ssl: response.data.use_ssl,
        bind_dn: response.data.bind_dn ?? "",
        user_search_base: response.data.user_search_base,
        group_search_base: response.data.group_search_base ?? "",
        user_attribute: response.data.user_attribute,
        group_attribute: response.data.group_attribute,
        active: response.data.active,
      });
      setBindPassword("");
      setMessage({ type: "success", text: "LDAP configuration saved." });
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to save LDAP configuration",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!config) {
      setMessage({ type: "error", text: "Save a configuration before testing." });
      return;
    }

    setTesting(true);
    setMessage(null);
    try {
      const response = await ldapService.testConfig(config.id);
      setMessage({
        type: response.data.status === "ok" ? "success" : "error",
        text: response.data.message,
      });
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "LDAP connection test failed",
      });
    } finally {
      setTesting(false);
    }
  };

  const handleSync = async () => {
    if (!config) {
      setMessage({ type: "error", text: "Save a configuration before syncing." });
      return;
    }

    setSyncing(true);
    setMessage(null);
    try {
      const response = await ldapService.sync(config.id);
      setMessage({
        type: response.data.status === "success" ? "success" : "error",
        text: response.data.message,
      });
      await loadData();
    } catch (err) {
      setMessage({
        type: "error",
        text: err instanceof Error ? err.message : "LDAP sync failed",
      });
    } finally {
      setSyncing(false);
    }
  };

  const statusBadge = (status: string) => {
    const normalized = status.toLowerCase();
    if (normalized === "success" || normalized === "ok") {
      return "bg-green-100 text-green-800";
    }
    if (normalized === "failed" || normalized === "error") {
      return "bg-red-100 text-red-800";
    }
    if (normalized === "pending") {
      return "bg-yellow-100 text-yellow-800";
    }
    return "bg-gray-100 text-gray-800";
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">LDAP Directory Sync</h1>
        <p className="mt-2 text-gray-600">
          Connect your directory to automate user provisioning and access controls.
        </p>
      </div>

      {message && (
        <div
          className={`rounded-lg border p-4 flex items-start gap-3 ${
            message.type === "error"
              ? "bg-red-50 border-red-200"
              : message.type === "success"
              ? "bg-green-50 border-green-200"
              : "bg-blue-50 border-blue-200"
          }`}
        >
          {message.type === "success" ? (
            <CheckCircle2 className="w-5 h-5 text-green-600 mt-0.5" />
          ) : (
            <AlertCircle className="w-5 h-5 text-red-600 mt-0.5" />
          )}
          <div>
            <p
              className={`text-sm font-semibold ${
                message.type === "error" ? "text-red-900" : "text-gray-900"
              }`}
            >
              {message.text}
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[2fr,1fr]">
        <form
          onSubmit={handleSave}
          className="bg-white rounded-lg border border-gray-200 p-6 space-y-6"
        >
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-bold text-gray-900">Directory Settings</h2>
              <p className="text-sm text-gray-500">
                Configure LDAP connection details and search bases.
              </p>
            </div>
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {saving ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              {saving ? "Saving" : "Save"}
            </button>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">LDAP Server</label>
              <input
                value={formData.ldap_server}
                onChange={(event) =>
                  setFormData({ ...formData, ldap_server: event.target.value })
                }
                placeholder="ldap.example.com"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">Port</label>
              <input
                type="number"
                min={1}
                max={65535}
                value={formData.ldap_port}
                onChange={(event) =>
                  setFormData({
                    ...formData,
                    ldap_port: Number(event.target.value || 0),
                  })
                }
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">Bind DN</label>
              <input
                value={formData.bind_dn}
                onChange={(event) =>
                  setFormData({ ...formData, bind_dn: event.target.value })
                }
                placeholder="cn=readonly,dc=example,dc=com"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">Bind Password</label>
              <input
                type="password"
                value={bindPassword}
                onChange={(event) => setBindPassword(event.target.value)}
                placeholder={config?.has_bind_password ? "Stored (leave blank to keep)" : "Enter password"}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">User Search Base</label>
              <input
                value={formData.user_search_base}
                onChange={(event) =>
                  setFormData({ ...formData, user_search_base: event.target.value })
                }
                placeholder="ou=users,dc=example,dc=com"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">Group Search Base</label>
              <input
                value={formData.group_search_base}
                onChange={(event) =>
                  setFormData({ ...formData, group_search_base: event.target.value })
                }
                placeholder="ou=groups,dc=example,dc=com"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">User Attribute</label>
              <input
                value={formData.user_attribute}
                onChange={(event) =>
                  setFormData({ ...formData, user_attribute: event.target.value })
                }
                placeholder="uid"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700">Group Attribute</label>
              <input
                value={formData.group_attribute}
                onChange={(event) =>
                  setFormData({ ...formData, group_attribute: event.target.value })
                }
                placeholder="cn"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              />
            </div>
          </div>

          <div className="flex flex-wrap gap-6">
            <label className="inline-flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={formData.use_ssl}
                onChange={(event) =>
                  setFormData({ ...formData, use_ssl: event.target.checked })
                }
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              Use SSL/TLS
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-gray-700">
              <input
                type="checkbox"
                checked={formData.active}
                onChange={(event) =>
                  setFormData({ ...formData, active: event.target.checked })
                }
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              Enable sync
            </label>
          </div>
        </form>

        <div className="space-y-6">
          <div className="bg-white rounded-lg border border-gray-200 p-6 space-y-4">
            <h2 className="text-lg font-bold text-gray-900">Connection Status</h2>
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <RefreshCw className="w-4 h-4 animate-spin" />
                Loading LDAP configuration...
              </div>
            ) : config ? (
              <div className="space-y-3 text-sm text-gray-600">
                <div className="flex items-center gap-2">
                  <Server className="w-4 h-4 text-blue-600" />
                  <span>{config.ldap_server}:{config.ldap_port}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-emerald-600" />
                  <span>{config.use_ssl ? "TLS enabled" : "Plain LDAP"}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Users className="w-4 h-4 text-indigo-600" />
                  <span>User base: {config.user_search_base}</span>
                </div>
                <div className="flex items-center gap-2">
                  <RefreshCw className="w-4 h-4 text-gray-500" />
                  <span>Last sync: {formatTimestamp(config.last_sync_at)}</span>
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-500">
                No LDAP configuration stored yet.
              </p>
            )}

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={handleTest}
                disabled={!config || testing}
                className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
              >
                {testing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Server className="w-4 h-4" />}
                {testing ? "Testing" : "Test Connection"}
              </button>
              <button
                type="button"
                onClick={handleSync}
                disabled={!config || syncing}
                className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm text-white hover:bg-emerald-700 disabled:opacity-60"
              >
                {syncing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                {syncing ? "Syncing" : "Run Sync"}
              </button>
            </div>
          </div>

          <div className="bg-white rounded-lg border border-gray-200 p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-gray-900">Recent Syncs</h2>
              <button
                type="button"
                onClick={loadData}
                className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"
              >
                <RefreshCw className="w-4 h-4" />
                Refresh
              </button>
            </div>

            {loading ? (
              <div className="flex items-center gap-2 text-sm text-gray-500">
                <RefreshCw className="w-4 h-4 animate-spin" />
                Loading sync history...
              </div>
            ) : logs.length === 0 ? (
              <p className="text-sm text-gray-500">No sync activity recorded yet.</p>
            ) : (
              <div className="space-y-3">
                {logs.slice(0, 5).map((log) => (
                  <div
                    key={log.id}
                    className="rounded-lg border border-gray-200 p-3 text-sm text-gray-600"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900">
                        {formatTimestamp(log.created_at)}
                      </span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-semibold ${statusBadge(log.status)}`}
                      >
                        {log.status}
                      </span>
                    </div>
                    <div className="mt-2 grid gap-2 md:grid-cols-3">
                      <span>Users synced: {log.users_synced}</span>
                      <span>Groups synced: {log.groups_synced}</span>
                      <span>Users disabled: {log.users_disabled}</span>
                    </div>
                    {log.error_message && (
                      <p className="mt-2 text-xs text-red-600">{log.error_message}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

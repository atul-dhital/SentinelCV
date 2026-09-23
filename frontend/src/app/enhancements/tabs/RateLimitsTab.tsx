'use client';

import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Button } from '@/components/ui/Button';
import { motion } from 'framer-motion';
import { Lock, Plus, ShieldCheck, Globe, Clock, Trash2 } from 'lucide-react';
import { RateLimitRule } from '@/services/api';

interface RateLimitsTabProps {
  rules: RateLimitRule[];
  saving?: boolean;
  onCreate: (data: { endpoint_pattern: string; max_requests: number; window_seconds: number; is_active: boolean }) => void;
  onUpdate: (ruleId: string, data: { endpoint_pattern: string; max_requests: number; window_seconds: number; is_active: boolean }) => void;
  onDelete: (ruleId: string) => void;
}

const iconForIndex = (i: number) => {
  if (i % 3 === 0) return Globe;
  if (i % 3 === 1) return ShieldCheck;
  return Clock;
};

const RateLimitsTab: React.FC<RateLimitsTabProps> = ({ rules, saving = false, onCreate, onUpdate, onDelete }) => {
  const [draftRules, setDraftRules] = useState<RateLimitRule[]>(rules);
  const [newRule, setNewRule] = useState({
    endpoint_pattern: '/api/v1/example',
    max_requests: 100,
    window_seconds: 3600,
    is_active: true,
  });

  useEffect(() => {
    setDraftRules(rules);
  }, [rules]);

  const updateDraft = (
    id: string,
    field: 'endpoint_pattern' | 'max_requests' | 'window_seconds' | 'is_active',
    value: string | number | boolean
  ) => {
    setDraftRules((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="p-3 rounded-2xl bg-brand-500/10 border border-brand-500/20">
              <Lock size={24} className="text-brand-500" />
            </div>
            <div>
              <CardTitle>Security Gates</CardTitle>
              <p className="text-sm text-gray-400">Manage API rate limiting and traffic control policies</p>
            </div>
          </div>
          <Button
            variant="secondary"
            className="hidden sm:flex gap-2"
            disabled={saving}
            onClick={() => onCreate(newRule)}
          >
            <Plus size={16} /> Add Rule
          </Button>
        </CardHeader>

        <CardContent className="space-y-6">
          <div className="grid md:grid-cols-4 gap-3 p-4 rounded-2xl bg-black/20 border border-white/5">
            <Input
              value={newRule.endpoint_pattern}
              onChange={(e) => setNewRule((prev) => ({ ...prev, endpoint_pattern: e.target.value }))}
              placeholder="/api/v1/endpoint"
              className="h-10 bg-black/20"
            />
            <Input
              type="number"
              value={newRule.max_requests}
              onChange={(e) => setNewRule((prev) => ({ ...prev, max_requests: Number(e.target.value || 0) }))}
              className="h-10 bg-black/20"
            />
            <Input
              type="number"
              value={newRule.window_seconds}
              onChange={(e) => setNewRule((prev) => ({ ...prev, window_seconds: Number(e.target.value || 0) }))}
              className="h-10 bg-black/20"
            />
            <Button disabled={saving} onClick={() => onCreate(newRule)} className="h-10 text-xs">Create</Button>
          </div>

          <div className="grid gap-4">
            {draftRules.map((limit, i) => {
              const Icon = iconForIndex(i);
              return (
                <div key={limit.id} className="group p-6 bg-white/5 border border-white/10 rounded-2xl hover:border-brand-500/30 transition-all duration-300">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <div className="flex items-center gap-4">
                      <div className="p-2 rounded-lg bg-black/40">
                        <Icon size={20} className="text-gray-400" />
                      </div>
                      <div className="min-w-0">
                        <h3 className="text-sm font-mono font-bold text-brand-400 truncate">{limit.endpoint_pattern}</h3>
                        <p className="text-xs text-gray-500 mt-0.5">Rule ID: {limit.id}</p>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4 md:w-96">
                      <div className="space-y-1.5">
                        <label className="text-[10px] font-black uppercase text-gray-600 tracking-widest">Threshold</label>
                        <Input
                          type="number"
                          value={limit.max_requests}
                          onChange={(e) => updateDraft(limit.id, 'max_requests', Number(e.target.value || 0))}
                          className="h-10 bg-black/20"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <label className="text-[10px] font-black uppercase text-gray-600 tracking-widest">Window (s)</label>
                        <Input
                          type="number"
                          value={limit.window_seconds}
                          onChange={(e) => updateDraft(limit.id, 'window_seconds', Number(e.target.value || 0))}
                          className="h-10 bg-black/20"
                        />
                      </div>
                      <div className="space-y-1.5 col-span-2">
                        <label className="text-[10px] font-black uppercase text-gray-600 tracking-widest">Endpoint Pattern</label>
                        <Input
                          value={limit.endpoint_pattern}
                          onChange={(e) => updateDraft(limit.id, 'endpoint_pattern', e.target.value)}
                          className="h-10 bg-black/20"
                        />
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="secondary"
                        className="h-10"
                        disabled={saving}
                        onClick={() =>
                          onUpdate(limit.id, {
                            endpoint_pattern: limit.endpoint_pattern,
                            max_requests: limit.max_requests,
                            window_seconds: limit.window_seconds,
                            is_active: limit.is_active,
                          })
                        }
                      >
                        Save
                      </Button>
                      <Button variant="danger" className="h-10" disabled={saving} onClick={() => onDelete(limit.id)}>
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="pt-4 p-6 bg-brand-500/5 rounded-2xl border border-brand-500/10">
            <div className="text-sm text-gray-400">
              Changes will be applied to the <span className="text-brand-400 font-bold">API Gateway</span> immediately.
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default RateLimitsTab;

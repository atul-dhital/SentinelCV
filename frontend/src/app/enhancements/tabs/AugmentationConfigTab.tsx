'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { motion } from 'framer-motion';
import { Ban, ChevronRight, Info, Maximize, RefreshCw, Video, Wand2, Zap } from 'lucide-react';
import {
  AugmentationConfigResponse,
  SyntheticGenerationJob,
  SyntheticQualityMetrics,
  TemporalAugmentationJob,
  TemporalExpressionMetrics,
} from '@/services/api';

interface AugmentationTabProps {
  data: AugmentationConfigResponse | null;
  syntheticJob: SyntheticGenerationJob | null;
  temporalJob: TemporalAugmentationJob | null;
  syntheticMetrics: SyntheticQualityMetrics[];
  temporalMetrics: TemporalExpressionMetrics[];
  startingSyntheticJob?: boolean;
  startingTemporalJob?: boolean;
  refreshingMetrics?: boolean;
  onChange?: (next: AugmentationConfigResponse | null) => void;
  onSave?: (next: AugmentationConfigResponse) => void;
  onStartSyntheticJob: (totalSamples: number) => void | Promise<void>;
  onCancelSyntheticJob: (jobId: string) => void | Promise<void>;
  onStartTemporalJob: (inputVideoPath: string) => void | Promise<void>;
  onCancelTemporalJob: (jobId: string) => void | Promise<void>;
  onRefreshMetrics: () => void | Promise<void>;
  saving?: boolean;
}

const AugmentationConfigTab: React.FC<AugmentationTabProps> = ({
  data,
  syntheticJob,
  temporalJob,
  syntheticMetrics,
  temporalMetrics,
  startingSyntheticJob = false,
  startingTemporalJob = false,
  refreshingMetrics = false,
  onChange,
  onSave,
  onStartSyntheticJob,
  onCancelSyntheticJob,
  onStartTemporalJob,
  onCancelTemporalJob,
  onRefreshMetrics,
  saving = false,
}) => {
  const [syntheticSampleTarget, setSyntheticSampleTarget] = useState(64);
  const [temporalVideoPath, setTemporalVideoPath] = useState('data/uploads/sample.mp4');

  useEffect(() => {
    if (syntheticJob?.total_target && syntheticJob.total_target > 0) {
      setSyntheticSampleTarget(syntheticJob.total_target);
    }
  }, [syntheticJob?.total_target]);

  if (!data) return (
    <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
      <Zap className="animate-bounce text-brand-500" size={32} />
      <p className="text-xs font-black uppercase tracking-widest text-gray-500">Initializing Augmentation Engine...</p>
    </div>
  );

  const latestSyntheticMetrics = syntheticMetrics[0] || null;
  const latestTemporalMetrics = temporalMetrics[0] || null;

  const syntheticProgress = syntheticJob?.total_target
    ? Math.min(100, Math.round((syntheticJob.samples_generated / Math.max(syntheticJob.total_target, 1)) * 100))
    : 0;
  const temporalProgress = temporalJob?.total_frames
    ? Math.min(100, Math.round((temporalJob.processed_frames / Math.max(temporalJob.total_frames, 1)) * 100))
    : 0;

  const dominantExpression = useMemo(() => {
    if (!latestTemporalMetrics?.expression_distribution) return 'n/a';
    const entries = Object.entries(latestTemporalMetrics.expression_distribution);
    if (entries.length === 0) return 'n/a';
    return entries.sort((a, b) => Number(b[1]) - Number(a[1]))[0][0];
  }, [latestTemporalMetrics]);

  const toggleTechnique = (technique: string) => {
    if (!data || !onChange) return;
    onChange({
      ...data,
      techniques: data.techniques.map((tech) =>
        tech.technique === technique ? { ...tech, enabled: !tech.enabled } : tech
      ),
    });
  };

  const toggleGlobal = (key: 'quality_checks_enabled' | 'auto_balance_demographics') => {
    if (!data || !onChange) return;
    onChange({ ...data, [key]: !data[key] });
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
              <Zap className="text-brand-500" size={24} />
            </div>
            <div>
              <CardTitle>Data Augmentation Pipeline</CardTitle>
              <p className="text-sm text-gray-400">Policy-driven synthetic data generation and temporal sequence expansion</p>
            </div>
          </div>
          <div className="flex gap-4 p-4 rounded-xl bg-white/5 border border-white/10">
            <div className="text-right">
              <p className="text-[10px] font-black text-gray-500 uppercase">Quality Gate</p>
              <p className={`text-xs font-bold ${data.quality_checks_enabled ? 'text-emerald-400' : 'text-gray-400'}`}>
                {data.quality_checks_enabled ? 'ENFORCED' : 'BYPASSED'}
              </p>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-8">
          <div className="grid lg:grid-cols-2 gap-6">
            {data.techniques.map((tech, idx) => (
              <motion.div
                key={tech.technique}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: idx * 0.05 }}
                className="group p-6 bg-white/5 border border-white/10 rounded-2xl hover:border-brand-500/30 transition-all duration-300 relative overflow-hidden"
              >
                <div className={`absolute top-0 right-0 w-24 h-24 -mr-8 -mt-8 opacity-5 transition-opacity group-hover:opacity-10 ${tech.enabled ? 'text-brand-500' : 'text-gray-500'}`}>
                  <Zap size={96} />
                </div>

                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className={`p-2 rounded-lg ${tech.enabled ? 'bg-brand-500/10 text-brand-500' : 'bg-white/5 text-gray-600'}`}>
                      <Maximize size={18} />
                    </div>
                    <h3 className="text-sm font-black uppercase tracking-widest text-white">{tech.technique.replace(/_/g, ' ')}</h3>
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleTechnique(tech.technique)}
                    className={`w-3 h-3 rounded-full ${tech.enabled ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-gray-700'}`}
                    title={tech.enabled ? 'Disable technique' : 'Enable technique'}
                  />
                </div>

                <p className="text-sm text-gray-500 mb-6 min-h-[40px]">{tech.description || 'No description provided for this specific technique.'}</p>

                {tech.params && (
                  <div className="grid gap-3 pt-4 border-t border-white/5">
                    {Object.entries(tech.params).map(([k, v]) => (
                      <div key={k} className="flex items-center justify-between bg-black/20 p-3 rounded-xl border border-white/5">
                        <span className="text-xs font-bold text-gray-500 uppercase tracking-tighter">{k.replace(/_/g, ' ')}</span>
                        <span className="font-mono text-xs text-brand-400 font-black">{JSON.stringify(v)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </motion.div>
            ))}
          </div>

          <div className="grid xl:grid-cols-2 gap-6">
            <div className="p-6 rounded-2xl bg-brand-500/5 border border-brand-500/10 space-y-4">
              <h4 className="text-xs font-black uppercase tracking-widest text-brand-400 mb-2 flex items-center gap-2">
                <Info size={14} /> System Recommendations
              </h4>
              <div className="grid gap-2">
                <label className="flex items-center justify-between text-xs text-gray-300 bg-black/20 rounded-lg px-3 py-2">
                  <span>Quality checks</span>
                  <input
                    type="checkbox"
                    checked={data.quality_checks_enabled}
                    onChange={() => toggleGlobal('quality_checks_enabled')}
                  />
                </label>
                <label className="flex items-center justify-between text-xs text-gray-300 bg-black/20 rounded-lg px-3 py-2">
                  <span>Auto-balance demographics</span>
                  <input
                    type="checkbox"
                    checked={data.auto_balance_demographics}
                    onChange={() => toggleGlobal('auto_balance_demographics')}
                  />
                </label>
              </div>
              <div className="space-y-3">
                {data.data_quality_actions.map((action, i) => (
                  <div key={i} className="flex items-start gap-3 text-sm text-gray-400">
                    <ChevronRight size={14} className="text-brand-500 mt-0.5 shrink-0" />
                    {action}
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-end gap-4 pt-4 border-t border-white/10">
                <Button
                  className="px-10 h-14 text-xs font-black tracking-widest uppercase shadow-[0_0_30px_rgba(var(--brand-primary-rgb),0.3)]"
                  disabled={saving}
                  onClick={() => data && onSave?.(data)}
                >
                  {saving ? 'Saving...' : 'Deploy Configuration'}
                </Button>
              </div>
            </div>

            <div className="grid gap-6">
              <div className="grid md:grid-cols-2 gap-4">
                <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
                  <p className="text-[10px] font-black uppercase tracking-widest text-gray-500 mb-2">Synthetic Quality</p>
                  <p className="text-2xl font-black text-white">{latestSyntheticMetrics?.acceptance_rate != null ? `${Math.round(latestSyntheticMetrics.acceptance_rate * 100)}%` : '--'}</p>
                  <p className="text-xs text-gray-400 mt-2">Acceptance rate</p>
                  <div className="mt-3 text-xs text-gray-500 space-y-1">
                    <p>Avg FID: {latestSyntheticMetrics?.avg_fid?.toFixed(3) ?? '--'}</p>
                    <p>LPIPS-like: {latestSyntheticMetrics?.avg_lpips?.toFixed(3) ?? '--'}</p>
                  </div>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
                  <p className="text-[10px] font-black uppercase tracking-widest text-gray-500 mb-2">Temporal Sequences</p>
                  <p className="text-2xl font-black text-white">{latestTemporalMetrics?.acceptance_rate != null ? `${Math.round(latestTemporalMetrics.acceptance_rate * 100)}%` : '--'}</p>
                  <p className="text-xs text-gray-400 mt-2">Sequence acceptance</p>
                  <div className="mt-3 text-xs text-gray-500 space-y-1">
                    <p>Avg confidence: {latestTemporalMetrics?.avg_confidence?.toFixed(3) ?? '--'}</p>
                    <p>Dominant expression: {dominantExpression}</p>
                  </div>
                </div>
              </div>

              <div className="rounded-2xl border border-white/10 bg-black/20 p-5 space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-black uppercase tracking-widest text-gray-500">Synthetic Generation Jobs</p>
                    <p className="text-sm text-gray-400">Launch balanced synthetic batches and monitor quality gates in one place.</p>
                  </div>
                  <Button variant="ghost" className="gap-2" onClick={() => onRefreshMetrics()} disabled={refreshingMetrics}>
                    <RefreshCw size={14} className={refreshingMetrics ? 'animate-spin' : ''} />
                    Refresh
                  </Button>
                </div>
                <div className="grid md:grid-cols-[1fr_auto] gap-3">
                  <Input
                    type="number"
                    min={8}
                    step={8}
                    value={syntheticSampleTarget}
                    onChange={(e) => setSyntheticSampleTarget(Number(e.target.value || 0))}
                    placeholder="Target synthetic sample count"
                  />
                  <Button
                    className="gap-2"
                    disabled={startingSyntheticJob || syntheticSampleTarget <= 0}
                    onClick={() => onStartSyntheticJob(syntheticSampleTarget)}
                  >
                    <Wand2 size={15} />
                    {startingSyntheticJob ? 'Starting...' : 'Start Synthetic Job'}
                  </Button>
                </div>
                {syntheticJob && (
                  <div className="rounded-xl border border-white/10 bg-white/5 p-4 space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-bold text-white">Job {syntheticJob.id.slice(0, 8)}</p>
                        <p className="text-xs text-gray-500 uppercase tracking-widest">Status: {syntheticJob.status}</p>
                      </div>
                      {['completed', 'cancelled', 'failed'].includes(syntheticJob.status) ? null : (
                        <Button variant="danger" className="gap-2" onClick={() => onCancelSyntheticJob(syntheticJob.id)}>
                          <Ban size={14} />
                          Cancel
                        </Button>
                      )}
                    </div>
                    <div className="h-2 rounded-full bg-white/5 overflow-hidden border border-white/5">
                      <div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-emerald-400" style={{ width: `${syntheticProgress}%` }} />
                    </div>
                    <div className="grid sm:grid-cols-3 gap-3 text-xs text-gray-400">
                      <p>Generated: {syntheticJob.samples_generated}/{syntheticJob.total_target}</p>
                      <p>Validated: {syntheticJob.samples_validated}</p>
                      <p>Rejected: {syntheticJob.samples_rejected}</p>
                    </div>
                  </div>
                )}
              </div>

              <div className="rounded-2xl border border-white/10 bg-black/20 p-5 space-y-4">
                <div>
                  <p className="text-xs font-black uppercase tracking-widest text-gray-500">Temporal Augmentation Jobs</p>
                  <p className="text-sm text-gray-400">Run expression interpolation against a real video source and verify temporal smoothness metrics.</p>
                </div>
                <div className="grid md:grid-cols-[1fr_auto] gap-3">
                  <Input
                    value={temporalVideoPath}
                    onChange={(e) => setTemporalVideoPath(e.target.value)}
                    placeholder="Input video path"
                  />
                  <Button
                    className="gap-2"
                    disabled={startingTemporalJob || !temporalVideoPath.trim()}
                    onClick={() => onStartTemporalJob(temporalVideoPath.trim())}
                  >
                    <Video size={15} />
                    {startingTemporalJob ? 'Starting...' : 'Start Temporal Job'}
                  </Button>
                </div>
                {temporalJob && (
                  <div className="rounded-xl border border-white/10 bg-white/5 p-4 space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-bold text-white">Job {temporalJob.id.slice(0, 8)}</p>
                        <p className="text-xs text-gray-500 uppercase tracking-widest">Status: {temporalJob.status}</p>
                      </div>
                      {['completed', 'cancelled', 'failed'].includes(temporalJob.status) ? null : (
                        <Button variant="danger" className="gap-2" onClick={() => onCancelTemporalJob(temporalJob.id)}>
                          <Ban size={14} />
                          Cancel
                        </Button>
                      )}
                    </div>
                    <div className="h-2 rounded-full bg-white/5 overflow-hidden border border-white/5">
                      <div className="h-full rounded-full bg-gradient-to-r from-sky-500 to-emerald-400" style={{ width: `${temporalProgress}%` }} />
                    </div>
                    <div className="grid sm:grid-cols-3 gap-3 text-xs text-gray-400">
                      <p>Frames: {temporalJob.processed_frames}/{temporalJob.total_frames}</p>
                      <p>Sequences: {temporalJob.generated_sequences}</p>
                      <p>Optical flow: {temporalJob.avg_optical_flow?.toFixed(3) ?? '--'}</p>
                    </div>
                    {temporalJob.error_message && <p className="text-xs text-red-400">{temporalJob.error_message}</p>}
                  </div>
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default AugmentationConfigTab;

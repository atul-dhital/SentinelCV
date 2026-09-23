'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { motion } from 'framer-motion';
import { CheckCircle2, XCircle, Zap, Server, AlertTriangle, Layers3, ArrowRight } from 'lucide-react';
import {
  BenchmarkSummaryResponse,
  CurrentCapabilitiesResponse,
  RuntimeModelRegistryResponse,
} from '@/services/api';

interface CapabilitiesTabProps {
  data: CurrentCapabilitiesResponse | null;
  runtimeRegistry: RuntimeModelRegistryResponse | null;
  benchmarkSummary: BenchmarkSummaryResponse | null;
}

const CapabilitiesTab: React.FC<CapabilitiesTabProps> = ({ data, runtimeRegistry, benchmarkSummary }) => {
  if (!data) return (
     <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <Server className="animate-pulse text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Querying System Capabilities...</p>
     </div>
  );

  const formatRuntimeModel = (artifact?: string | null, model?: string) => {
    if (!artifact || artifact === model) return model;
    return `${model} · ${artifact}`;
  };

  const benchmarkCompleted = benchmarkSummary?.status === 'completed';

  const capabilityStatusClasses = (status: string) => {
    const normalized = (status || '').toLowerCase();
    if (normalized === 'live') {
      return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
    }
    if (normalized === 'beta') {
      return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
    }
    if (normalized === 'experimental') {
      return 'bg-violet-500/10 text-violet-400 border-violet-500/20';
    }
    return 'bg-gray-500/10 text-gray-400 border-gray-500/20';
  };

  return (
    <motion.div 
      initial={{ opacity: 0 }} 
      animate={{ opacity: 1 }}
      className="grid lg:grid-cols-2 gap-8"
    >
      {/* Capabilities */}
      <Card>
        <CardHeader className="border-b border-white/5 bg-emerald-500/5">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-3 text-emerald-400">
              <CheckCircle2 size={24} />
              Capability Maturity
            </CardTitle>
            <span className="text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
              v{data.system_version}
            </span>
          </div>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid gap-3">
            {data.implemented_features.map((f, i) => (
              <motion.div 
                key={i}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className="flex items-center gap-4 p-4 rounded-2xl bg-white/5 border border-white/10 group hover:border-emerald-500/30 transition-all"
              >
                <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-500 group-hover:scale-110 transition-transform">
                  <Zap size={16} />
                </div>
                <div className="flex-1 min-w-0">
                   <h4 className="text-sm font-bold text-gray-200">{f.feature}</h4>
                   <p className="text-[10px] text-gray-500 font-mono uppercase tracking-tighter">{f.technology}</p>
                </div>
                <span className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border ${capabilityStatusClasses(f.status)}`}>
                  {f.status}
                </span>
              </motion.div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Limitations */}
      <Card>
        <CardHeader className="border-b border-white/5 bg-red-500/5">
          <CardTitle className="flex items-center gap-3 text-red-400">
            <XCircle size={24} />
            System Constraints
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid gap-3">
            {data.current_limitations.map((lim, i) => (
              <motion.div 
                key={i}
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
                className="flex items-center gap-4 p-4 rounded-2xl bg-white/5 border border-white/10 group hover:border-red-500/30 transition-all opacity-70 hover:opacity-100"
              >
                <div className="p-2 rounded-lg bg-red-500/10 text-red-500 group-hover:rotate-12 transition-transform">
                   <AlertTriangle size={16} />
                </div>
                <div>
                   <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[8px] font-black uppercase tracking-widest px-1.5 py-0.5 rounded ${lim.severity === 'high' ? 'bg-red-500/20 text-red-400' : 'bg-gray-500/20 text-gray-400'}`}>
                         {lim.severity}
                      </span>
                   </div>
                   <p className="text-sm font-medium text-gray-400 group-hover:text-gray-200">{lim.description}</p>
                </div>
              </motion.div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Phase Summary */}
      <Card className="lg:col-span-2">
        <CardHeader className="border-b border-white/5 bg-sky-500/5">
          <CardTitle className="flex items-center gap-3 text-sky-400">
            <Layers3 size={24} />
            Phase-by-Phase Implementation
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid gap-4 md:grid-cols-2">
            {data.phase_summary.map((phase, phaseIndex) => (
              <motion.div
                key={phase.phase}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: phaseIndex * 0.06 }}
                className="rounded-2xl border border-white/10 bg-white/5 p-5"
              >
                <div className="flex items-center justify-between gap-4 mb-3">
                  <div>
                    <p className="text-[10px] font-black uppercase tracking-widest text-sky-400">{phase.phase}</p>
                    <h4 className="text-sm font-bold text-gray-100">{phase.title}</h4>
                  </div>
                  <span className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border ${
                    phase.status === 'implemented'
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                      : phase.status === 'partial'
                        ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                        : 'bg-gray-500/10 text-gray-400 border-gray-500/20'
                  }`}>
                    {phase.status}
                  </span>
                </div>
                <p className="text-xs text-gray-400 mb-4 leading-relaxed">{phase.focus}</p>
                <div className="flex gap-2 mb-4">
                  <span className="text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    {phase.implemented_count} implemented
                  </span>
                  <span className="text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                    {phase.planned_count} planned
                  </span>
                </div>
                <div className="grid gap-2">
                  {phase.items.map((item) => (
                    <div key={`${phase.phase}-${item.name}`} className="flex items-start gap-3 text-sm">
                      {item.status === 'implemented' ? (
                        <CheckCircle2 size={14} className="mt-0.5 text-emerald-400 shrink-0" />
                      ) : (
                        <ArrowRight size={14} className="mt-0.5 text-amber-400 shrink-0" />
                      )}
                      <div>
                        <div className="text-gray-200 font-medium">{item.name}</div>
                        <div className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">{item.component}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </motion.div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-indigo-500/5">
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-3 text-indigo-400">
              <Server size={24} />
              Live Runtime Inventory
            </CardTitle>
            <span className="text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              {runtimeRegistry?.version ? `v${runtimeRegistry.version}` : 'pending'}
            </span>
          </div>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid gap-3">
            {(runtimeRegistry?.components ?? []).map((component, index) => (
              <motion.div
                key={component.component}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.04 }}
                className="rounded-2xl border border-white/10 bg-white/5 p-4"
              >
                <div className="flex items-center justify-between gap-3 mb-2">
                  <div>
                    <div className="text-sm font-bold text-gray-100">{component.display_name}</div>
                    <div className="text-[10px] uppercase tracking-widest text-gray-500 font-mono">{component.component}</div>
                  </div>
                  <span className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border ${
                    component.status === 'active'
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                      : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                  }`}>
                    {component.status}
                  </span>
                </div>
                <div className="space-y-1 text-xs text-gray-400">
                  <div>
                    <span className="text-gray-500">Current:</span>{' '}
                    <span className="text-gray-200">{formatRuntimeModel(component.current_artifact, component.current_model)}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Target:</span>{' '}
                    <span className="text-gray-300">{component.target_model ?? 'n/a'}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Runtime:</span>{' '}
                    <span className="text-gray-300">{component.runtime}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Framework:</span>{' '}
                    <span className="text-gray-300">{component.framework}</span>
                  </div>
                  {component.notes ? <p className="pt-2 text-[11px] leading-relaxed text-gray-500">{component.notes}</p> : null}
                </div>
              </motion.div>
            ))}
            {!runtimeRegistry?.components?.length ? (
              <div className="rounded-2xl border border-dashed border-white/10 bg-white/5 p-4 text-xs text-gray-500">
                Runtime registry not available yet.
              </div>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-amber-500/5">
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-3 text-amber-400">
              <Zap size={24} />
              Benchmark Baseline
            </CardTitle>
            <span className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border ${
              benchmarkCompleted
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
            }`}>
              {benchmarkSummary?.status ?? 'not_run'}
            </span>
          </div>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[10px] uppercase tracking-widest text-gray-500">Baseline Accuracy</div>
              <div className="mt-2 text-2xl font-black text-gray-100">
                {benchmarkSummary?.baseline_accuracy != null ? `${benchmarkSummary.baseline_accuracy.toFixed(1)}%` : 'n/a'}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[10px] uppercase tracking-widest text-gray-500">Multi-Angle Accuracy</div>
              <div className="mt-2 text-2xl font-black text-gray-100">
                {benchmarkSummary?.multi_angle_accuracy != null ? `${benchmarkSummary.multi_angle_accuracy.toFixed(1)}%` : 'n/a'}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[10px] uppercase tracking-widest text-gray-500">Avg Latency</div>
              <div className="mt-2 text-2xl font-black text-gray-100">
                {benchmarkSummary?.avg_latency_ms != null ? `${benchmarkSummary.avg_latency_ms.toFixed(1)}ms` : 'n/a'}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[10px] uppercase tracking-widest text-gray-500">Sample Size</div>
              <div className="mt-2 text-2xl font-black text-gray-100">
                {benchmarkSummary?.sample_size ?? 0}
              </div>
            </div>
          </div>
          <div className="flex gap-2 flex-wrap mb-4">
            <span className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border ${
              benchmarkSummary?.production_ready
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : 'bg-gray-500/10 text-gray-400 border-gray-500/20'
            }`}>
              {benchmarkSummary?.production_ready ? 'production ready' : 'needs tuning'}
            </span>
            <span className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border ${
              benchmarkSummary?.latency_target_met
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
            }`}>
              {benchmarkSummary?.latency_target_met ? 'latency target met' : 'latency target pending'}
            </span>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-gray-300 leading-relaxed">
            {benchmarkSummary?.recommendation ?? 'Run the baseline benchmark suite to populate this summary.'}
          </div>
          {benchmarkSummary?.results_path ? (
            <div className="mt-3 text-[10px] font-mono uppercase tracking-widest text-gray-500">
              Results: {benchmarkSummary.results_path}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default CapabilitiesTab;

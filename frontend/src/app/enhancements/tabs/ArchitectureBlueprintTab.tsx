'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Layers3, AlertTriangle, Cpu, Lock, Radar, Wrench } from 'lucide-react';
import { NextGenBlueprintResponse } from '@/services/api';

interface ArchitectureBlueprintTabProps {
  data: NextGenBlueprintResponse | null;
}

const statusClass = (status: string) => {
  if (status === 'missing') return 'bg-red-500/10 text-red-400 border-red-500/30';
  if (status === 'partial') return 'bg-amber-500/10 text-amber-400 border-amber-500/30';
  return 'bg-sky-500/10 text-sky-400 border-sky-500/30';
};

const ArchitectureBlueprintTab: React.FC<ArchitectureBlueprintTabProps> = ({ data }) => {
  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <Layers3 className="animate-pulse text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Loading Architecture Blueprint...</p>
      </div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="grid gap-8 lg:grid-cols-2">
      <Card>
        <CardHeader className="border-b border-white/5 bg-red-500/5">
          <CardTitle className="flex items-center gap-3 text-red-400">
            <AlertTriangle size={20} />
            Maturity Gaps
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-3">
          {data.gaps.map((gap, index) => (
            <motion.div
              key={`${gap.area}-${index}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.04 }}
              className="rounded-xl border border-white/10 bg-white/5 p-4"
            >
              <div className="flex items-center justify-between gap-3 mb-2">
                <h4 className="text-sm font-bold text-gray-100">{gap.area}</h4>
                <span className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border ${statusClass(gap.status)}`}>
                  {gap.status}
                </span>
              </div>
              <p className="text-xs text-gray-400 mb-2">{gap.notes}</p>
              <span className="text-[10px] uppercase tracking-widest text-gray-500">Impact: {gap.impact}</span>
            </motion.div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-sky-500/5">
          <CardTitle className="flex items-center gap-3 text-sky-400">
            <Layers3 size={20} />
            Target Architecture
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-4">
          {data.target_architecture.map((layer, index) => (
            <motion.div
              key={layer.name}
              initial={{ opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.04 }}
              className="rounded-xl border border-white/10 bg-white/5 p-4"
            >
              <h4 className="text-sm font-bold text-gray-100 mb-2">{layer.name}</h4>
              <div className="grid gap-1.5">
                {layer.capabilities.map((item) => (
                  <p key={`${layer.name}-${item}`} className="text-xs text-gray-400">- {item}</p>
                ))}
              </div>
            </motion.div>
          ))}
        </CardContent>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader className="border-b border-white/5 bg-emerald-500/5">
          <CardTitle className="flex items-center gap-3 text-emerald-400">
            <Radar size={20} />
            Model Recommendations
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid md:grid-cols-2 gap-4">
          {data.model_recommendations.map((item) => (
            <div key={item.task} className="rounded-xl border border-white/10 bg-white/5 p-4">
              <h4 className="text-sm font-bold text-gray-100 mb-1">{item.task}</h4>
              <p className="text-xs text-emerald-300 mb-2">Primary: {item.primary}</p>
              {item.alternatives.length > 0 && (
                <p className="text-xs text-gray-400 mb-2">Alternatives: {item.alternatives.join(', ')}</p>
              )}
              <p className="text-xs text-gray-500">{item.rationale}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-violet-500/5">
          <CardTitle className="flex items-center gap-3 text-violet-400">
            <Cpu size={20} />
            Runtime and MLOps Stack
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-4">
          <div>
            <h4 className="text-xs uppercase tracking-widest text-gray-500 mb-2">Serving</h4>
            <div className="grid gap-1.5">
              {data.serving_stack.map((item) => (
                <p key={`serving-${item}`} className="text-xs text-gray-300">- {item}</p>
              ))}
            </div>
          </div>
          <div>
            <h4 className="text-xs uppercase tracking-widest text-gray-500 mb-2">MLOps</h4>
            <div className="grid gap-1.5">
              {data.mlops_stack.map((item) => (
                <p key={`mlops-${item}`} className="text-xs text-gray-300">- {item}</p>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-amber-500/5">
          <CardTitle className="flex items-center gap-3 text-amber-400">
            <Lock size={20} />
            Security Baseline and Latency Targets
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-4">
          <div className="grid gap-1.5">
            {data.security_baseline.map((item) => (
              <p key={item} className="text-xs text-gray-300">- {item}</p>
            ))}
          </div>
          <div className="rounded-xl border border-white/10 bg-black/30 p-4">
            <h4 className="text-xs uppercase tracking-widest text-gray-500 mb-2">Latency Targets (ms)</h4>
            {Object.entries(data.inference_latency_targets_ms).map(([key, val]) => (
              <div key={key} className="flex items-center justify-between text-xs py-1 border-b last:border-b-0 border-white/5">
                <span className="text-gray-400">{key.replaceAll('_', ' ')}</span>
                <span className="font-mono text-gray-200">{val}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader className="border-b border-white/5 bg-brand-500/5">
          <CardTitle className="flex items-center gap-3 text-brand-400">
            <Wrench size={20} />
            Phased Rollout
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid md:grid-cols-2 gap-4">
          {data.phased_rollout.map((phase) => (
            <div key={phase.phase} className="rounded-xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-bold text-gray-100">{phase.phase}</h4>
                <span className="text-[10px] uppercase tracking-widest text-gray-500">{phase.timeline}</span>
              </div>
              <div className="mb-3">
                <p className="text-[10px] uppercase tracking-widest text-gray-500 mb-1">Goals</p>
                {phase.goals.map((goal) => (
                  <p key={`${phase.phase}-goal-${goal}`} className="text-xs text-gray-300">- {goal}</p>
                ))}
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-widest text-gray-500 mb-1">Deliverables</p>
                {phase.deliverables.map((deliverable) => (
                  <p key={`${phase.phase}-deliv-${deliverable}`} className="text-xs text-gray-400">- {deliverable}</p>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default ArchitectureBlueprintTab;

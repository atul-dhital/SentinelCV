'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { motion } from 'framer-motion';
import { TrendingUp, Target, Activity, BarChart3 } from 'lucide-react';
import { MetricTarget, MetricsTargetsResponse } from '@/services/api';

interface MetricsTabProps {
  data: MetricsTargetsResponse | null;
}

const MetricsTab: React.FC<MetricsTabProps> = ({ data }) => {
  if (!data) return (
     <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <TrendingUp className="animate-pulse text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Aggregating Metric Streams...</p>
     </div>
  );

  const isCacheMetric = (metric: string) => metric.toLowerCase().includes('cache');

  const parsePercent = (value: string) => {
    const trimmed = value.replace(/[^0-9.]/g, '');
    const parsed = Number.parseFloat(trimmed);
    return Number.isNaN(parsed) ? null : parsed;
  };

  const parseTarget = (target: string) => {
    const trimmed = target.trim();
    if (!trimmed || trimmed.toLowerCase() === 'n/a') {
      return { value: null, comparator: '>=' as const };
    }

    const comparator = trimmed.startsWith('<=')
      ? '<='
      : trimmed.startsWith('>=')
      ? '>='
      : trimmed.startsWith('<')
      ? '<'
      : trimmed.startsWith('>')
      ? '>'
      : '>=';

    const rawValue = trimmed.replace(/^[<>]=?/, '');
    return { value: parsePercent(rawValue), comparator };
  };

  const resolveCacheStatus = (current: string, target: string) => {
    const currentValue = parsePercent(current);
    const parsedTarget = parseTarget(target);

    if (currentValue === null || parsedTarget.value === null) {
      return {
        label: 'Unknown',
        variant: 'secondary' as const,
        color: 'text-gray-400',
        tooltip: 'Cache hit ratio is not available yet.',
      };
    }

    const meetsTarget =
      parsedTarget.comparator === '>' || parsedTarget.comparator === '>='
        ? currentValue >= parsedTarget.value
        : currentValue <= parsedTarget.value;

    if (meetsTarget) {
      return {
        label: 'Healthy',
        variant: 'success' as const,
        color: 'text-emerald-400',
        tooltip: `Cache hit ratio meets target (${target}).`,
      };
    }

    return {
      label: 'Low',
      variant: 'destructive' as const,
      color: 'text-red-400',
      tooltip: `Cache hit ratio below target (${target}).`,
    };
  };

  const renderMetricGroup = (
    metrics: MetricTarget[],
    title: string,
    icon: React.ComponentType<{ size?: number }>,
    color: string
  ) => (
    <Card className="hover:border-white/20 transition-all h-full">
      <CardHeader className="border-b border-white/5 bg-white/5">
        <CardTitle className={`text-sm font-black uppercase tracking-widest flex items-center gap-3 ${color}`}>
          {React.createElement(icon, { size: 18 })}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-6 space-y-4">
        {metrics.map((m, i) => (
          <div key={i} className="group relative">
            <div className="flex justify-between items-end mb-2">
               <div>
                  <div className="flex items-center gap-2">
                    <h4 className="text-xs font-bold text-gray-300 group-hover:text-white transition-colors uppercase tracking-tight">{m.metric}</h4>
                    {isCacheMetric(m.metric) && (
                      <Badge variant="secondary" className="px-2 py-0 text-[8px]" title="Cache-based metric">
                        Cache
                      </Badge>
                    )}
                  </div>
                  <p className="text-[8px] font-black text-gray-600 uppercase tracking-widest">Targeting: {m.target}</p>
               </div>
               <div className="text-right">
                  {isCacheMetric(m.metric) ? (
                    (() => {
                      const status = resolveCacheStatus(m.current, m.target);
                      return (
                        <div className="flex items-center justify-end gap-2">
                          <span className={`text-lg font-black ${status.color}`}>{m.current}</span>
                          <Badge variant={status.variant} className="px-2 py-0 text-[8px]" title={status.tooltip}>
                            {status.label}
                          </Badge>
                        </div>
                      );
                    })()
                  ) : (
                    <span className={`text-lg font-black ${color}`}>{m.current}</span>
                  )}
               </div>
            </div>
             <div className="h-1 w-full bg-white/5 rounded-full overflow-hidden">
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${(() => {
                    const parseVal = (s: string) => { const n = parseFloat(s); return isNaN(n) ? 0 : n; };
                    const cur = parseVal(m.current);
                    const tgt = parseVal(m.target);
                    return tgt > 0 ? Math.min(100, (cur / tgt) * 100) : (cur > 0 ? 75 : 0);
                  })()}%` }}
                  className={`h-full ${color.replace('text-', 'bg-')}`}
                />
             </div>
            {m.method && (
               <p className="mt-2 text-[9px] font-mono text-gray-700 uppercase leading-none opacity-0 group-hover:opacity-100 transition-opacity">
                 Method: {m.method}
               </p>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-widest text-gray-500">
        <span className="text-gray-600">Cache status:</span>
        <Badge variant="success" title="Cache hit ratio meets or exceeds target.">Healthy</Badge>
        <Badge variant="secondary" title="Cache hit ratio is not available yet.">Unknown</Badge>
        <Badge variant="destructive" title="Cache hit ratio below target.">Low</Badge>
      </div>
      <motion.div 
        initial={{ opacity: 0, scale: 0.98 }} 
        animate={{ opacity: 1, scale: 1 }}
        className="grid lg:grid-cols-3 gap-6"
      >
        {renderMetricGroup(data.accuracy_metrics, 'Accuracy & Precision', Target, 'text-brand-500')}
        {renderMetricGroup(data.system_metrics, 'System Performance', Activity, 'text-blue-400')}
        {renderMetricGroup(data.business_metrics, 'Business Context', BarChart3, 'text-purple-400')}
      </motion.div>
    </div>
  );
};

export default MetricsTab;

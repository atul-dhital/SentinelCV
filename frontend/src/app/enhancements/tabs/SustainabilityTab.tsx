'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { motion } from 'framer-motion';
import { Leaf, Zap, Cloud, BarChart3, Globe, TrendingUp } from 'lucide-react';
import { CarbonMetricsSummary } from '@/services/api';

interface SustainabilityTabProps {
  data: CarbonMetricsSummary | null;
}

const SustainabilityTab: React.FC<SustainabilityTabProps> = ({ data }) => {
  if (!data) return (
     <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <Leaf className="animate-pulse text-emerald-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Calculating Ecological Footprint...</p>
     </div>
  );

   const trendUsesEfficiencyMetric = (data.monthly_trend || []).some((entry: any) => entry?.efficiency_score != null || entry?.value != null);

   const resolveTrendValue = (entry: any): number => {
      const candidates = [entry?.efficiency_score, entry?.value, entry?.co2_kg, entry?.kwh];
      for (const candidate of candidates) {
         const parsed = Number(candidate);
         if (Number.isFinite(parsed) && parsed > 0) {
            return parsed;
         }
      }
      return 0;
   };

   const trendValues = (data.monthly_trend || []).map((entry: any) => resolveTrendValue(entry));
   const validTrendValues = trendValues.filter((value) => value > 0);
   const hasTrendValues = validTrendValues.length > 0;
   const hasComparativeTrend = validTrendValues.length >= 2;

   const trendToneClass = (() => {
      if (!hasTrendValues) return 'text-gray-500';
      if (!hasComparativeTrend) return 'text-emerald-500';

      const recent = validTrendValues[validTrendValues.length - 1];
      const prev = validTrendValues[validTrendValues.length - 2];
      const isImprovement = trendUsesEfficiencyMetric ? recent >= prev : recent <= prev;
      return isImprovement ? 'text-emerald-500' : 'text-red-400';
   })();

   const trendSummary = (() => {
      if (!hasTrendValues) return 'No Trend Data';
      if (!hasComparativeTrend) return 'Baseline Captured';

      const recent = validTrendValues[validTrendValues.length - 1];
      const prev = validTrendValues[validTrendValues.length - 2];
      if (prev === 0) return recent > 0 ? 'Improving' : 'Stable';

      const pct = ((recent - prev) / prev * 100).toFixed(0);
      const isImprovement = trendUsesEfficiencyMetric ? recent >= prev : recent <= prev;
      const signed = trendUsesEfficiencyMetric
         ? `${recent >= prev ? '+' : ''}${pct}%`
         : `${recent <= prev ? '' : '+'}${Math.abs(Number(pct))}%`;
      return `${signed} ${isImprovement ? 'Improving' : 'Declining'}`;
   })();

  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.98 }} 
      animate={{ opacity: 1, scale: 1 }}
      className="space-y-6"
    >
      <div className="grid lg:grid-cols-4 gap-6">
         <Card className="lg:col-span-2 border-emerald-500/20 bg-emerald-500/5">
            <CardHeader>
               <div className="flex items-center gap-4">
                  <div className="p-3 bg-emerald-500/20 rounded-2xl text-emerald-500">
                     <Leaf size={24} />
                  </div>
                  <div>
                     <CardTitle className="text-emerald-100">Efficiency Score</CardTitle>
                     <p className="text-sm text-emerald-500/60 font-bold uppercase tracking-widest">Optimized Computation Index</p>
                  </div>
               </div>
            </CardHeader>
            <CardContent className="flex items-center justify-center py-6">
               <div className="text-6xl font-black text-emerald-400 tabular-nums">{data.efficiency_score}<span className="text-2xl opacity-40">/100</span></div>
            </CardContent>
         </Card>

         <Card className="hover:border-blue-500/20 transition-all border-white/10">
            <CardContent className="pt-8 flex flex-col items-center text-center">
               <div className="p-3 rounded-full bg-blue-500/10 text-blue-400 mb-4">
                  <Cloud size={24} />
               </div>
               <p className="text-[10px] font-black uppercase tracking-widest text-gray-500 mb-1">CO2 Estimate</p>
               <p className="text-2xl font-black text-white">{data.total_co2_kg.toFixed(2)} <span className="text-xs font-bold text-gray-500">KG</span></p>
            </CardContent>
         </Card>

         <Card className="hover:border-amber-500/20 transition-all border-white/10">
            <CardContent className="pt-8 flex flex-col items-center text-center">
               <div className="p-3 rounded-full bg-amber-500/10 text-amber-500 mb-4">
                  <Zap size={24} />
               </div>
               <p className="text-[10px] font-black uppercase tracking-widest text-gray-500 mb-1">Energy Draw</p>
               <p className="text-2xl font-black text-white">{data.total_kwh.toFixed(1)} <span className="text-xs font-bold text-gray-500">KWH</span></p>
            </CardContent>
         </Card>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
         <Card className="lg:col-span-1">
            <CardHeader>
               <CardTitle className="text-xs uppercase tracking-widest text-gray-500">Resource Utilization</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
               <div className="flex justify-between items-end">
                  <div>
                     <p className="text-[10px] font-black uppercase text-gray-600 tracking-widest">GPU Workload</p>
                     <p className="text-xl font-black text-white">{data.total_gpu_hours} <span className="text-xs text-gray-500 font-bold">HOURS</span></p>
                  </div>
                  <div className="h-10 w-1 rounded bg-brand-500 shadow-[0_0_10px_rgba(var(--brand-primary-rgb),0.5)]" />
               </div>
               <div className="flex justify-between items-end">
                  <div>
                     <p className="text-[10px] font-black uppercase text-gray-600 tracking-widest">CPU Workload</p>
                     <p className="text-xl font-black text-white">{data.total_cpu_hours} <span className="text-xs text-gray-500 font-bold">HOURS</span></p>
                  </div>
                  <div className="h-10 w-1 rounded bg-blue-500" />
               </div>
            </CardContent>
         </Card>

         <Card className="lg:col-span-2 overflow-hidden bg-white/5">
            <CardHeader className="flex flex-row items-center justify-between">
               <CardTitle className="text-xs font-black uppercase tracking-widest text-gray-500 flex items-center gap-2">
                  <BarChart3 size={14} /> Monthly Efficiency Trend
               </CardTitle>
                <span className={`text-[10px] font-bold uppercase flex items-center gap-1 ${trendToneClass}`}>
                   <TrendingUp size={10} /> {trendSummary}
                </span>
            </CardHeader>
             <CardContent className="h-48 flex items-end gap-2 pb-2">
                {(data.monthly_trend && data.monthly_trend.length > 0 ? data.monthly_trend : Array.from({ length: 12 }, (_, i) => ({ month: `M${i + 1}`, efficiency_score: 0 }))).map((entry: any, i: number) => {
                   const val = resolveTrendValue(entry);
                   const maxVal = Math.max(0.0001, ...trendValues);
                   const pct = Math.max(5, (val / maxVal) * 100);
                   return (
                   <motion.div 
                     key={i}
                     initial={{ height: 0 }}
                     animate={{ height: `${pct}%` }}
                     className="flex-1 bg-white/5 rounded-t-lg border-x border-white/5 hover:bg-emerald-500/20 transition-all cursor-pointer relative group"
                   >
                      <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-black/80 text-[8px] font-black px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
                         {entry.month ?? `M${i + 1}`}: {val.toFixed(3)}
                      </div>
                   </motion.div>
                   );
                })}
             </CardContent>
         </Card>
      </div>

      <div className="pt-4 flex justify-between items-center bg-black/40 p-6 rounded-2xl border border-white/5">
         <p className="text-xs text-gray-500 italic flex items-center gap-2">
            <Globe size={14} className="text-emerald-500" /> These metrics are computed using real-time hardware telemetry and region-specific CO2 emission factors.
         </p>
         <Button variant="ghost" className="px-8 h-12 text-xs font-black uppercase tracking-widest text-emerald-500 hover:bg-emerald-500/10">Full Sustainability Report</Button>
      </div>
    </motion.div>
  );
};

export default SustainabilityTab;

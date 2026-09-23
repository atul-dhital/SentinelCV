'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { motion } from 'framer-motion';
import { Gauge, Zap, BarChart3, Clock, ChevronRight, Activity } from 'lucide-react';
import { PerformanceConfigResponse } from '@/services/api';

interface PerformanceTabProps {
  data: PerformanceConfigResponse | null;
}

const PerformanceConfigTab: React.FC<PerformanceTabProps> = ({ data }) => {
  if (!data) return (
     <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <Gauge className="animate-spin text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Profiling Neural Latency...</p>
     </div>
  );

  return (
    <motion.div 
      initial={{ opacity: 0 }} 
      animate={{ opacity: 1 }}
      className="space-y-6"
    >
      <div className="grid lg:grid-cols-2 gap-6">
         {/* Latency Breakdown */}
         <Card className="hover:border-brand-500/30 transition-all">
            <CardHeader className="flex flex-row items-center gap-4">
               <div className="p-3 rounded-2xl bg-brand-500/10 border border-brand-500/20">
                 <Clock className="text-brand-500" size={24} />
               </div>
               <div>
                  <CardTitle>Inference Latency Profile</CardTitle>
                  <p className="text-sm text-gray-500">Real-time processing performance map (ms)</p>
               </div>
            </CardHeader>
            <CardContent className="space-y-6">
               <div className="grid gap-4">
                  {Object.entries(data.current_latency).map(([k, v]) => (
                     <div key={k} className="space-y-2">
                        <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                           <span className="text-gray-500">{k.replace(/_/g, ' ')}</span>
                           <span className="text-white">{v}ms / {data.target_latency[k] || '0'}ms Target</span>
                        </div>
                        <div className="h-2 w-full bg-white/5 rounded-full overflow-hidden border border-white/5">
                           <motion.div 
                             initial={{ width: 0 }}
                             animate={{ width: `${(v / (data.target_latency[k] || v || 1)) * 100}%` }}
                             className={`h-full ${v > (data.target_latency[k] || v) ? 'bg-red-500' : 'bg-brand-500'}`}
                           />
                        </div>
                     </div>
                  ))}
               </div>
            </CardContent>
         </Card>

         {/* Optimizations */}
         <Card className="hover:border-brand-500/30 transition-all">
            <CardHeader className="flex flex-row items-center gap-4 border-b border-white/5 bg-brand-500/5">
               <div className="p-3 rounded-2xl bg-brand-500/10 border border-brand-500/20">
                 <Zap className="text-brand-500" size={24} />
               </div>
               <div>
                  <CardTitle>GPU Execution Policy</CardTitle>
                  <p className="text-sm text-gray-500">Hardware-level optimization toggles</p>
               </div>
            </CardHeader>
            <CardContent className="pt-6">
               <div className="grid md:grid-cols-2 gap-4">
                  {Object.entries(data.gpu_optimizations).map(([k, v]) => (
                     <div key={k} className="p-4 rounded-xl bg-black/40 border border-white/5 flex items-center justify-between group hover:border-brand-500/20 transition-all">
                        <span className="text-xs font-bold text-gray-400 uppercase tracking-tighter">{k.replace(/_/g, ' ')}</span>
                        <div className={`w-3 h-3 rounded-full ${v ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' : 'bg-gray-700'}`} />
                     </div>
                  ))}
               </div>
            </CardContent>
         </Card>
      </div>

      <Card className="bg-white/5 border border-white/10 group overflow-hidden">
         <div className="absolute inset-0 bg-gradient-to-r from-brand-500/0 via-brand-500/5 to-brand-500/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-[2s] pointer-events-none" />
         <CardHeader>
            <CardTitle className="text-sm uppercase tracking-widest text-gray-500 flex items-center gap-2">
               <Activity size={16} className="text-brand-500" /> Active Acceleration Suite
            </CardTitle>
         </CardHeader>
         <CardContent>
            <div className="flex flex-wrap gap-3">
               {data.optimization_techniques.map(tech => (
                  <div key={tech} className="px-5 py-3 rounded-2xl bg-black/40 border border-white/5 flex items-center gap-3 hover:border-brand-500/40 transition-all cursor-crosshair">
                     <BarChart3 size={14} className="text-gray-600" />
                     <span className="text-xs font-black uppercase tracking-widest text-gray-400">{tech}</span>
                     <ChevronRight size={12} className="text-brand-500/40" />
                  </div>
               ))}
            </div>
         </CardContent>
      </Card>
    </motion.div>
  );
};

export default PerformanceConfigTab;

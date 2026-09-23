'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { motion } from 'framer-motion';
import { Brain, Zap, RefreshCw, Target, ChevronRight } from 'lucide-react';
import { TrainingStrategyResponse } from '@/services/api';

interface TrainingTabProps {
  data: TrainingStrategyResponse | null;
}

const TrainingConfigTab: React.FC<TrainingTabProps> = ({ data }) => {
  if (!data) return (
     <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <Brain className="animate-pulse text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Synthesizing Training Logic...</p>
     </div>
  );

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }} 
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      <div className="grid lg:grid-cols-2 gap-6">
         {/* SSL Section */}
         <Card className="hover:border-brand-500/30 transition-all">
            <CardHeader className="flex flex-row items-center gap-4">
               <div className="p-3 rounded-2xl bg-brand-500/10 border border-brand-500/20">
                 <Zap className="text-brand-500" size={24} />
               </div>
               <div>
                  <CardTitle>Self-Supervised Learning</CardTitle>
                  <p className="text-sm text-gray-400">Unlabeled data leverage strategy</p>
               </div>
            </CardHeader>
            <CardContent className="space-y-4">
               <div className="p-4 rounded-xl bg-white/5 border border-white/5">
                  <p className="text-[10px] font-black uppercase text-gray-500 mb-2">Active Methods</p>
                  <div className="flex flex-wrap gap-2">
                     {data.available_ssl_methods.map(m => (
                        <span key={m} className="px-2 py-1 rounded bg-brand-500/10 text-brand-400 text-[10px] font-bold uppercase">{m}</span>
                     ))}
                  </div>
               </div>
               <div className="text-xs text-gray-500 bg-black/40 p-4 rounded-xl">
                  {Object.entries(data.self_supervised).map(([k, v]) => (
                     <div key={k} className="flex justify-between mb-1">
                        <span className="uppercase tracking-tighter">{k.replace(/_/g, ' ')}</span>
                        <span className="font-mono text-brand-400">{JSON.stringify(v)}</span>
                     </div>
                  ))}
               </div>
            </CardContent>
         </Card>

         {/* Continual Learning */}
         <Card className="hover:border-brand-500/30 transition-all">
            <CardHeader className="flex flex-row items-center gap-4">
               <div className="p-3 rounded-2xl bg-purple-500/10 border border-purple-500/20">
                 <RefreshCw className="text-purple-500" size={24} />
               </div>
               <div>
                  <CardTitle>Continual Learning</CardTitle>
                  <p className="text-sm text-gray-400">Stream-based adaptation & plasticity</p>
               </div>
            </CardHeader>
            <CardContent>
               <div className="space-y-4">
                  <div className="p-4 rounded-xl bg-purple-500/5 border border-purple-500/10">
                    <p className="text-xs text-gray-400 leading-relaxed italic">
                       &quot;Prevents catastrophic forgetting during online updates by leveraging elastic weight consolidation.&quot;
                    </p>
                  </div>
                  <div className="grid gap-2">
                     {Object.entries(data.continual_learning).map(([k, v]) => (
                        <div key={k} className="flex items-center justify-between p-3 rounded-lg bg-black/20 border border-white/5">
                           <span className="text-[10px] font-black uppercase text-gray-600 tracking-wider">Property: {k}</span>
                           <span className="text-xs font-bold text-gray-300">{JSON.stringify(v)}</span>
                        </div>
                     ))}
                  </div>
               </div>
            </CardContent>
         </Card>
      </div>

      {/* HPO Section */}
      <Card className="border-brand-500/20 bg-brand-500/5">
         <CardHeader className="flex flex-row items-center justify-between">
            <div className="flex items-center gap-4">
               <div className="p-2 bg-brand-500/20 rounded-xl text-brand-400">
                  <Target size={20} />
               </div>
             <CardTitle>Hyperparameter Optimization (HPO)</CardTitle>
             </div>
          </CardHeader>
         <CardContent>
            <div className="grid md:grid-cols-3 gap-4">
               {data.available_hpo_methods.map(method => (
                  <div key={method} className="flex items-center gap-3 p-4 rounded-xl bg-black/40 border border-white/5 group hover:border-brand-500/30 transition-all cursor-pointer">
                     <ChevronRight size={14} className="text-brand-500 group-hover:translate-x-1 transition-transform" />
                     <span className="text-sm font-bold text-gray-300 uppercase tracking-tighter">{method}</span>
                  </div>
               ))}
            </div>
         </CardContent>
      </Card>
    </motion.div>
  );
};

export default TrainingConfigTab;

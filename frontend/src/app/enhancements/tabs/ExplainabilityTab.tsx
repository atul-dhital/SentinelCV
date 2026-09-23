'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { motion } from 'framer-motion';
import { Brain, Search, Layers, Info, Activity } from 'lucide-react';
import { ExplainabilityResult } from '@/services/api';

const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1').replace('/api/v1', '');

interface ExplainabilityTabProps {
  data: ExplainabilityResult | null;
  onRefresh?: () => void;
}

const ExplainabilityTab: React.FC<ExplainabilityTabProps> = ({ data, onRefresh }) => {
  const [isRefreshing, setIsRefreshing] = React.useState(false);

  const handleRefresh = async () => {
    if (!onRefresh) return;
    setIsRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setIsRefreshing(false);
    }
  };

  if (!data) return (
     <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <Brain className="animate-pulse text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Deconstructing Neural Logic...</p>
     </div>
  );

  return (
    <motion.div 
      initial={{ opacity: 0, x: 20 }} 
      animate={{ opacity: 1, x: 0 }}
      className="space-y-6"
    >
      <div className="flex justify-between items-center mb-4">
        <div>
          <h2 className="text-xl font-black uppercase tracking-tight text-white">XAI Transparency Engine</h2>
          <p className="text-sm text-gray-500 italic">Interpreting deep neural decisions via feature attribution</p>
        </div>
        <button 
          onClick={handleRefresh}
          disabled={isRefreshing}
          className="flex items-center gap-2 px-6 py-2 rounded-xl bg-brand-500 text-white text-[10px] font-black uppercase tracking-widest hover:bg-brand-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Brain size={12} className={isRefreshing ? 'animate-pulse' : ''} />
          {isRefreshing ? 'Analyzing...' : 'Refresh Analysis'}
        </button>
      </div>

      <div className="grid lg:grid-cols-12 gap-6">
         {/* Feature Importance */}
         <Card className="lg:col-span-8">
            <CardHeader className="flex flex-row items-center gap-4">
               <div className="p-3 rounded-2xl bg-brand-500/10 border border-brand-500/20">
                 <Search className="text-brand-500" size={24} />
               </div>
               <div>
                  <CardTitle>Feature Importance Attribution</CardTitle>
                  <p className="text-sm text-gray-500">Contribution mapping using <span className="text-brand-400 font-black uppercase tracking-widest font-mono">{data.explanation_method}</span></p>
               </div>
            </CardHeader>
            <CardContent>
               <div className="space-y-6">
                  {Object.entries(data.feature_importance).map(([feature, importance], idx) => (
                     <div key={feature} className="space-y-2">
                        <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
                           <span className="text-gray-400">{feature.replace(/_/g, ' ')}</span>
                           <span className="text-brand-400">{(importance * 100).toFixed(1)}% Weight</span>
                        </div>
                        <div className="h-1.5 w-full bg-white/5 rounded-full overflow-hidden border border-white/5">
                           <motion.div 
                             initial={{ width: 0 }}
                             animate={{ width: `${importance * 100}%` }}
                             transition={{ delay: idx * 0.1, duration: 1 }}
                             className="h-full bg-brand-500 shadow-[0_0_10px_rgba(var(--brand-primary-rgb),0.5)]"
                           />
                        </div>
                     </div>
                  ))}
               </div>
            </CardContent>
         </Card>

         {/* Model Metadata */}
         <Card className="lg:col-span-4 border-brand-500/20 bg-brand-500/5">
            <CardHeader>
               <CardTitle className="text-sm font-black uppercase tracking-widest text-gray-500">Model Inspector</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
                <div>
                   <p className="text-[10px] font-black uppercase text-brand-500 mb-1">Target Module</p>
                   <p className="text-lg font-black text-white uppercase tracking-tight">{data.model_name}</p>
                </div>
                <div className="p-6 rounded-2xl bg-black/40 border border-white/5">
                   <p className="text-[10px] font-black uppercase text-gray-600 mb-4">Confidence Spectrum</p>
                   <div className="space-y-3">
                      {Object.entries(data.confidence_breakdown).map(([k, v]) => (
                         <div key={k} className="flex justify-between items-center py-2 border-b border-white/5 last:border-0 border-dashed">
                            <span className="text-[10px] font-bold text-gray-500 uppercase">{k}</span>
                             <span className="text-xs font-black text-brand-400">
                                 {k === 'heatmap_overlay' ? (
                                   <a href={`${API_ORIGIN}/api/v1/visitors/face-image?path=${v}`} target="_blank" className="underline hover:text-white">View Heatmap</a>
                                 ) : JSON.stringify(v)}
                             </span>

                         </div>
                      ))}
                   </div>
                </div>
            </CardContent>
         </Card>
      </div>

      <Card>
         <CardHeader>
            <CardTitle className="text-sm font-black uppercase tracking-widest text-gray-500 flex items-center gap-2">
               <Layers size={16} className="text-purple-400" /> Decision Factor Map
            </CardTitle>
         </CardHeader>
         <CardContent>
            <div className="grid md:grid-cols-3 gap-6">
               {data.decision_factors.map((factor, i) => (
                  <div key={i} className="p-5 rounded-2xl bg-white/5 border border-white/10 group hover:border-brand-500/30 transition-all">
                     <div className="flex items-center gap-2 mb-3 text-brand-400">
                        <Info size={14} />
                        <span className="text-[10px] font-black uppercase tracking-widest">Logic Node 0{i+1}</span>
                     </div>
                     <p className="text-sm text-gray-300 font-medium leading-relaxed italic">
                        {Object.entries(factor).map(([k, v]) => `${k}: ${v}`).join(' • ')}
                     </p>
                  </div>
               ))}
            </div>
         </CardContent>
      </Card>
    </motion.div>
  );
};

export default ExplainabilityTab;

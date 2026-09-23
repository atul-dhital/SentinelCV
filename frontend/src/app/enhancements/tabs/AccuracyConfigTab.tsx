'use client';

import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { motion } from 'framer-motion';
import { Target, TrendingUp, Cpu, Maximize2, Zap, Save } from 'lucide-react';
import { AccuracyBoostResponse } from '@/services/api';
import { Button } from '@/components/ui/Button';

interface AccuracyTabProps {
  data: AccuracyBoostResponse | null;
  onSave?: (data: AccuracyBoostResponse) => void;
  saving?: boolean;
}

const AccuracyConfigTab: React.FC<AccuracyTabProps> = ({ data, onSave, saving }) => {
  const [draft, setDraft] = useState<AccuracyBoostResponse | null>(null);

  useEffect(() => {
    if (data) {
      const normalized: AccuracyBoostResponse = {
        ...data,
        multi_angle: {
          ...data.multi_angle,
          multi_angle_enabled: Boolean((data.multi_angle as any)?.multi_angle_enabled ?? (data.multi_angle as any)?.enabled),
          supported_angles: (data.multi_angle as any)?.supported_angles || [],
        },
        consensus_voting: {
          ...data.consensus_voting,
          consensus_voting_enabled: Boolean((data.consensus_voting as any)?.consensus_voting_enabled ?? (data.consensus_voting as any)?.enabled),
          consensus_threshold: Number((data.consensus_voting as any)?.consensus_threshold ?? (data.consensus_voting as any)?.threshold ?? 0.7),
          top_k_scores: Number((data.consensus_voting as any)?.top_k_scores ?? 3),
        },
        temporal_enhancement: {
          ...data.temporal_enhancement,
          temporal_enabled: Boolean((data.temporal_enhancement as any)?.temporal_enabled ?? (data.temporal_enhancement as any)?.enabled),
          recency_weight: Number((data.temporal_enhancement as any)?.recency_weight ?? 0.6),
        },
      };
      setDraft(normalized);
    }
  }, [data]);

  if (!draft) return (
     <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <Target className="animate-spin text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Fine-tuning Precision...</p>
     </div>
  );

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }} 
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      <div className="flex justify-between items-center mb-6">
        <div>
          <h2 className="text-2xl font-black uppercase tracking-tighter">Accuracy Optimization</h2>
          <p className="text-sm text-gray-500">Configure multi-angle recognition and consensus voting</p>
        </div>
        <Button 
          onClick={() => onSave?.(draft)} 
          disabled={saving || !onSave}
          className="bg-brand-500 hover:bg-brand-600 text-white gap-2"
        >
          {saving ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : <Save size={16} />}
          {saving ? 'Saving...' : 'Deploy Configuration'}
        </Button>
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
         {/* Multi-angle Section */}
         <Card className="lg:col-span-2 group overflow-hidden">
            <CardHeader className="flex flex-row items-center justify-between gap-4 bg-brand-500/5 border-b border-brand-500/10">
               <div className="flex items-center gap-4">
                  <div className="p-3 rounded-2xl bg-brand-500/10 border border-brand-500/20 group-hover:scale-110 transition-transform">
                    <Maximize2 className="text-brand-500" size={24} />
                  </div>
                  <div>
                     <CardTitle>Multi-Angle Spatiotemporal Fusion</CardTitle>
                     <p className="text-sm text-gray-400">Geometry-aware identification optimization</p>
                  </div>
               </div>
               <div className="flex items-center gap-2">
                  <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">Enabled</span>
                  <button
                    onClick={() => setDraft({ ...draft, multi_angle: { ...draft.multi_angle, multi_angle_enabled: !draft.multi_angle.multi_angle_enabled } })}
                    className={`relative p-1 rounded-full w-12 h-6 transition-colors ${draft.multi_angle.multi_angle_enabled ? 'bg-brand-500' : 'bg-white/10'}`}
                  >
                    <motion.div 
                      animate={{ x: draft.multi_angle.multi_angle_enabled ? 24 : 0 }}
                      className="w-4 h-4 bg-white rounded-full shadow-lg"
                    />
                  </button>
               </div>
            </CardHeader>
            <CardContent className="pt-6 space-y-6">
               <div className="grid md:grid-cols-2 gap-6">
                  <div className="space-y-4">
                     <p className="text-[10px] font-black uppercase tracking-widest text-gray-500">Config Parameters</p>
                     <div className="grid gap-2">
                        {Object.entries(draft.multi_angle).map(([k, v]) => (
                           <div key={k} className="flex justify-between items-center p-3 rounded-xl bg-white/5 border border-white/5">
                              <span className="text-[10px] font-bold text-gray-500 uppercase tracking-tighter">{k.replace(/_/g, ' ')}</span>
                              {typeof v === 'boolean' ? (
                                <button
                                  onClick={() => setDraft({ ...draft, multi_angle: { ...draft.multi_angle, [k]: !v } })}
                                  className={`text-xs font-black uppercase tracking-widest ${v ? 'text-brand-400' : 'text-gray-600'}`}
                                >
                                  {v ? 'True' : 'False'}
                                </button>
                              ) : (
                                <span className="font-mono text-xs text-brand-400 font-black">{JSON.stringify(v)}</span>
                              )}
                           </div>
                        ))}
                     </div>
                  </div>
                  <div className="space-y-4">
                     <p className="text-[10px] font-black uppercase tracking-widest text-gray-500">Active Viewing Angles</p>
                     <div className="flex flex-wrap gap-2">
                        {draft.available_angles.map(angle => {
                           const isSupported = (draft.multi_angle.supported_angles || []).includes(angle);
                           return (
                              <button 
                                key={angle} 
                                onClick={() => {
                                   const current = draft.multi_angle.supported_angles || [];
                                   const next = isSupported ? current.filter((a: string) => a !== angle) : [...current, angle];
                                   setDraft({ ...draft, multi_angle: { ...draft.multi_angle, supported_angles: next } });
                                }}
                                className={`px-3 py-1.5 rounded-lg border text-xs font-bold transition-all font-mono ${
                                   isSupported 
                                   ? 'bg-brand-500/20 border-brand-500/50 text-brand-400' 
                                   : 'bg-black/40 border-white/5 text-gray-500'
                                }`}
                              >
                                 {angle}
                              </button>
                           );
                        })}
                     </div>
                  </div>
               </div>
            </CardContent>
         </Card>

         <div className="space-y-6">
             {/* Consensus Voting */}
             <Card className="h-full">
                <CardHeader className="flex flex-row items-center justify-between gap-4">
                   <CardTitle className="text-sm font-black uppercase tracking-widest text-emerald-400 flex items-center gap-2">
                      <Zap size={16} /> Consensus Voting
                   </CardTitle>
                   <button
                    onClick={() => setDraft({ ...draft, consensus_voting: { ...draft.consensus_voting, consensus_voting_enabled: !draft.consensus_voting.consensus_voting_enabled } })}
                    className={`relative p-1 rounded-full w-10 h-5 transition-colors ${draft.consensus_voting.consensus_voting_enabled ? 'bg-emerald-500' : 'bg-white/10'}`}
                  >
                    <motion.div 
                      animate={{ x: draft.consensus_voting.consensus_voting_enabled ? 20 : 0 }}
                      className="w-3 h-3 bg-white rounded-full shadow-lg"
                    />
                  </button>
                </CardHeader>
                <CardContent className="space-y-4">
                    <div className="space-y-3">
                       {Object.entries(draft.consensus_voting).map(([k, v]) => (
                          <div key={k} className="flex justify-between items-center py-2 border-b border-white/5 last:border-0">
                             <span className="text-[10px] font-mono text-gray-500 leading-relaxed uppercase">{k.replace(/_/g, ' ')}</span>
                             {typeof v === 'number' ? (
                               <input 
                                 type="number"
                                 step={v < 1 ? 0.1 : 1}
                                 value={v}
                                 onChange={(e) => setDraft({ ...draft, consensus_voting: { ...draft.consensus_voting, [k]: parseFloat(e.target.value) } })}
                                 className="w-16 bg-transparent text-right text-white font-bold border-none outline-none focus:text-emerald-400 transition-colors"
                               />
                             ) : typeof v === 'boolean' ? (
                                <span className={`text-xs font-bold ${v ? 'text-emerald-400' : 'text-gray-600'}`}>{v ? 'ON' : 'OFF'}</span>
                             ) : (
                               <span className="text-white font-bold">{JSON.stringify(v)}</span>
                             )}
                          </div>
                       ))}
                    </div>
                </CardContent>
             </Card>
         </div>
      </div>

      <Card className="bg-white/5 border border-white/10 relative overflow-hidden">
        <div className="absolute top-0 right-0 p-8 opacity-5 text-brand-500">
           <TrendingUp size={120} />
        </div>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
           <CardTitle className="flex items-center gap-3">
              <Cpu size={24} className="text-brand-500" />
              Temporal Enhancement Layer
           </CardTitle>
           <button
            onClick={() => setDraft({ ...draft, temporal_enhancement: { ...draft.temporal_enhancement, temporal_enabled: !draft.temporal_enhancement.temporal_enabled } })}
            className={`relative p-1 rounded-full w-12 h-6 transition-colors ${draft.temporal_enhancement.temporal_enabled ? 'bg-brand-500' : 'bg-white/10'}`}
          >
            <motion.div 
              animate={{ x: draft.temporal_enhancement.temporal_enabled ? 24 : 0 }}
              className="w-4 h-4 bg-white rounded-full shadow-lg"
            />
          </button>
        </CardHeader>
        <CardContent>
           <div className="grid md:grid-cols-3 gap-6 relative">
              {Object.entries(draft.temporal_enhancement).map(([k, v], i) => (
                 <div key={k} className="p-4 rounded-2xl bg-black/40 border border-white/5 flex flex-col gap-2 group hover:border-brand-500/30 transition-all">
                    <span className="text-[10px] font-black uppercase tracking-widest text-gray-600">Metric Segment 0{i + 1}</span>
                    <span className="text-xs font-bold text-gray-300 uppercase underline decoration-brand-500 underline-offset-4">{k.replace(/_/g, ' ')}</span>
                    {typeof v === 'number' ? (
                      <input 
                        type="number"
                        step="0.1"
                        value={v}
                        onChange={(e) => setDraft({ ...draft, temporal_enhancement: { ...draft.temporal_enhancement, [k]: parseFloat(e.target.value) } })}
                        className="text-xl font-black text-white bg-transparent border-none outline-none focus:text-brand-400 transition-colors"
                      />
                    ) : (
                      <span className="text-xl font-black text-white">{JSON.stringify(v)}</span>
                    )}
                 </div>
              ))}
           </div>
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default AccuracyConfigTab;

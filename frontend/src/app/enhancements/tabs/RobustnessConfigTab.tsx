'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { motion } from 'framer-motion';
import { Shield, ShieldAlert, Bug, Target } from 'lucide-react';
import { RobustnessConfigResponse } from '@/services/api';

interface RobustnessTabProps {
  data: RobustnessConfigResponse | null;
}

const RobustnessConfigTab: React.FC<RobustnessTabProps> = ({ data }) => {
  if (!data) return (
     <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <Shield className="animate-pulse text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Hardening Environment...</p>
     </div>
  );

  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.98 }} 
      animate={{ opacity: 1, scale: 1 }}
      className="space-y-6"
    >
      <div className="grid lg:grid-cols-2 gap-6">
         {/* Adversarial Defense */}
         <Card className="hover:border-red-500/20 transition-all border-white/5">
            <CardHeader className="flex flex-row items-center gap-4 border-b border-white/5 bg-red-500/5">
               <div className="p-3 rounded-2xl bg-red-500/10 border border-red-500/20 transition-colors">
                 <ShieldAlert className="text-red-500" size={24} />
               </div>
               <div>
                  <CardTitle className="text-red-100">Adversarial Defense</CardTitle>
                  <p className="text-sm text-gray-500 uppercase tracking-tighter">Neural network robustness verification</p>
               </div>
            </CardHeader>
            <CardContent className="pt-6">
               <div className="space-y-4">
                  <div className="p-4 rounded-xl bg-black/40 border border-white/5">
                     {Object.entries(data.adversarial_defense).map(([k, v]) => (
                        <div key={k} className="flex justify-between items-center py-2 border-b border-white/5 last:border-0">
                           <span className="text-[10px] font-black uppercase text-gray-500 tracking-wider font-mono">{k}</span>
                           <span className="text-xs font-bold text-red-400">{JSON.stringify(v)}</span>
                        </div>
                     ))}
                  </div>
                  <p className="text-xs text-gray-400 p-2 bg-red-500/5 rounded-lg border border-red-500/10 italic">
                     Hardening the model against FGM/PGD adversarial attacks by using adversarial training during foundational phases.
                  </p>
               </div>
            </CardContent>
         </Card>

         {/* Occlusion Handling */}
         <Card className="hover:border-blue-500/20 transition-all border-white/5">
            <CardHeader className="flex flex-row items-center gap-4 border-b border-white/5 bg-blue-500/5">
               <div className="p-3 rounded-2xl bg-blue-500/10 border border-blue-500/20 transition-colors">
                 <Target className="text-blue-500" size={24} />
               </div>
               <div>
                  <CardTitle className="text-blue-100">Occlusion Handling</CardTitle>
                  <p className="text-sm text-gray-500 uppercase tracking-tighter">Robustness to partial feature missing</p>
               </div>
            </CardHeader>
            <CardContent className="pt-6">
               <div className="space-y-4">
                  <div className="p-4 rounded-xl bg-black/40 border border-white/5">
                     {Object.entries(data.occlusion_handling).map(([k, v]) => (
                        <div key={k} className="flex justify-between items-center py-2 border-b border-white/5 last:border-0">
                           <span className="text-[10px] font-black uppercase text-gray-500 tracking-wider font-mono">{k}</span>
                           <span className="text-xs font-bold text-blue-400">{JSON.stringify(v)}</span>
                        </div>
                     ))}
                  </div>
                  <p className="text-xs text-gray-400 p-2 bg-blue-500/5 rounded-lg border border-blue-500/10">
                     Implementing attention-aware sampling to reconstruct partially occluded identifying features.
                  </p>
               </div>
            </CardContent>
         </Card>
      </div>

      <Card className="bg-white/5 border-white/10">
         <CardHeader>
            <CardTitle className="text-sm uppercase tracking-widest text-gray-500 flex items-center gap-2">
               <Bug size={16} className="text-emerald-500" /> Defense Suite Status
            </CardTitle>
         </CardHeader>
         <CardContent>
            <div className="flex flex-wrap gap-3">
               {data.defense_techniques.map(tech => (
                  <div key={tech} className="flex items-center gap-3 px-4 py-3 rounded-xl bg-black/40 border border-white/5 group hover:border-emerald-500/30 transition-all">
                     <span className="w-2 h-2 rounded-full bg-emerald-500" />
                     <span className="text-xs font-black uppercase tracking-widest text-gray-400 group-hover:text-emerald-400">{tech}</span>
                  </div>
               ))}
            </div>
         </CardContent>
      </Card>
    </motion.div>
  );
};

export default RobustnessConfigTab;

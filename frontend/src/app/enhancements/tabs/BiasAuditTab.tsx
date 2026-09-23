'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { motion } from 'framer-motion';
import { Eye, ShieldCheck, AlertCircle, CheckCircle2, Info, ChevronRight } from 'lucide-react';
import { BiasAuditResult } from '@/services/api';

interface BiasAuditTabProps {
  data: BiasAuditResult | null;
  onRefresh?: () => void;
}

const BiasAuditTab: React.FC<BiasAuditTabProps> = ({ data, onRefresh }) => {
  const [isRefreshing, setIsRefreshing] = React.useState(false);

  const handleRunAudit = async () => {
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
        <Eye className="animate-pulse text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Scanning for Algorithmic Bias...</p>
     </div>
  );

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }} 
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      <div className="grid lg:grid-cols-3 gap-6">
         {/* Fairness Score */}
         <Card className="border-brand-500/20 bg-brand-500/5 lg:col-span-1">
            <CardHeader className="text-center pb-2">
               <CardTitle className="text-xs font-black uppercase tracking-widest text-gray-500">Overall Fairness Score</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col items-center justify-center py-8">
               <div className="relative w-32 h-32 flex items-center justify-center">
                  <svg className="w-full h-full transform -rotate-90">
                     <circle cx="64" cy="64" r="58" stroke="currentColor" strokeWidth="8" fill="transparent" className="text-white/5" />
                     <motion.circle 
                        cx="64" cy="64" r="58" stroke="currentColor" strokeWidth="8" fill="transparent" 
                        strokeDasharray={364.4}
                        initial={{ strokeDashoffset: 364.4 }}
                        animate={{ strokeDashoffset: 364.4 - (364.4 * (data.overall_fairness_score / 100)) }}
                        className="text-brand-500"
                        transition={{ duration: 1.5, ease: "easeOut" }}
                     />
                  </svg>
                  <span className="absolute text-3xl font-black text-white">{data.overall_fairness_score}%</span>
               </div>
                <p className={`mt-6 text-xs font-bold uppercase tracking-widest flex items-center gap-2 ${data.overall_fairness_score >= 70 ? 'text-emerald-400' : data.overall_fairness_score >= 40 ? 'text-amber-400' : 'text-red-400'}`}>
                   {data.overall_fairness_score >= 70 ? (
                     <><CheckCircle2 size={14} /> Passed Confidence Threshold</>
                   ) : data.overall_fairness_score >= 40 ? (
                     <><AlertCircle size={14} /> Below Threshold — Review Needed</>
                   ) : (
                     <><AlertCircle size={14} /> Critical — Immediate Action Required</>
                   )}
                </p>
            </CardContent>
         </Card>

         {/* Demographic Split */}
         <Card className="lg:col-span-2">
            <CardHeader className="flex flex-row items-center gap-4">
               <div className="p-3 rounded-2xl bg-brand-500/10 border border-brand-500/20">
                 <ShieldCheck className="text-brand-500" size={24} />
               </div>
               <div>
                  <CardTitle>Demographic Parity Audit</CardTitle>
                  <p className="text-sm text-gray-500 italic">Disparity gap analysis across intersectional groups</p>
               </div>
            </CardHeader>
            <CardContent>
               <div className="grid gap-4">
                  {Object.entries(data.demographic_parity).map(([k, v]) => (
                     <div key={k} className="p-4 rounded-xl bg-white/5 border border-white/5 group hover:border-brand-500/20 transition-all">
                        <div className="flex justify-between items-center mb-2">
                           <span className="text-xs font-black uppercase tracking-widest text-gray-400">{k.replace(/_/g, ' ')}</span>
                           <span className="text-xs font-mono font-bold text-white">{JSON.stringify(v)}</span>
                        </div>
                         <div className="h-1.5 w-full bg-white/5 rounded-full overflow-hidden">
                            <div className="h-full bg-brand-500/50" style={{ width: `${Math.min(100, Math.max(0, typeof v === 'number' ? v * 100 : (typeof v === 'object' && v !== null && 'rate' in v ? (v as any).rate * 100 : 85)))}%` }} />
                         </div>
                     </div>
                  ))}
               </div>
            </CardContent>
         </Card>
      </div>

      <Card className="hover:border-amber-500/30 transition-all border-white/10">
         <CardHeader>
            <CardTitle className="text-sm font-black uppercase tracking-widest text-amber-500 flex items-center gap-2">
               <AlertCircle size={16} /> Remediation Recommendations
            </CardTitle>
         </CardHeader>
         <CardContent>
            <div className="grid md:grid-cols-2 gap-4">
               {data.recommendations.map((rec, i) => (
                  <div key={i} className="flex items-start gap-4 p-4 rounded-2xl bg-amber-500/5 border border-amber-500/10 group">
                     <div className="p-2 rounded-lg bg-amber-500/10 text-amber-500 group-hover:scale-110 transition-transform">
                        <Info size={14} />
                     </div>
                     <p className="text-sm text-gray-300 leading-relaxed">{rec}</p>
                  </div>
               ))}
            </div>
         </CardContent>
      </Card>

      <div className="pt-4 flex items-center justify-between bg-white/5 p-6 rounded-2xl border border-white/10">
         <div className="flex items-center gap-2 text-xs text-gray-500 font-mono">
           <span className="font-black uppercase tracking-widest">Last Audit:</span> {new Date(data.audited_at).toLocaleString()}
         </div>
          <div className="flex gap-4">
             <Button variant="ghost" className="px-8 h-12 text-xs font-black uppercase tracking-widest text-gray-500">Export Full Report</Button>
             <Button 
                onClick={handleRunAudit}
                disabled={isRefreshing}
                className={`px-10 h-12 text-xs font-black uppercase tracking-widest bg-brand-500 text-white shadow-[0_0_20px_rgba(var(--brand-primary-rgb),0.3)] ${isRefreshing ? 'opacity-50' : ''}`}
             >
                {isRefreshing ? 'Scanning...' : 'Run Audit'}
             </Button>
          </div>

      </div>
    </motion.div>
  );
};

export default BiasAuditTab;

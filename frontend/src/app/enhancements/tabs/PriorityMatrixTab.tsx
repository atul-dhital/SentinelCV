'use client';

import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { motion } from 'framer-motion';
import { BarChart3, ArrowUpRight, Minus, TrendingUp } from 'lucide-react';
import { PriorityMatrixResponse } from '@/services/api';

interface PriorityMatrixTabProps {
  data: PriorityMatrixResponse| null;
}

const PriorityMatrixTab: React.FC<PriorityMatrixTabProps> = ({ data }) => {
  if (!data) return (
     <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <BarChart3 className="animate-pulse text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Calculating ROI Vectors...</p>
     </div>
  );

  const renderTier = (items: any[], title: string, color: string, icon: any) => (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-4">
         <div className={`p-1.5 rounded-lg ${color} bg-opacity-10 text-opacity-100`}>
            {React.createElement(icon, { size: 14, className: color.replace('bg-', 'text-') })}
         </div>
         <h3 className="text-[10px] font-black uppercase tracking-widest text-gray-500">{title} ({items.length})</h3>
      </div>
      <div className="grid gap-3">
        {items.map((item, idx) => (
          <motion.div 
            key={idx}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center justify-between p-4 rounded-xl bg-white/5 border border-white/5 hover:border-white/10 transition-all group"
          >
            <div className="flex flex-col">
               <span className="text-xs font-bold text-gray-200 group-hover:text-brand-400 transition-colors uppercase tracking-tight">{item.enhancement}</span>
               <span className="text-[10px] font-mono text-gray-600 uppercase tracking-tighter">{item.category || 'General'}</span>
            </div>
            <div className="flex items-center gap-6">
               <div className="text-right">
                  <p className="text-[8px] font-black text-gray-600 uppercase">Impact</p>
                  <p className="text-[10px] font-bold text-white uppercase">{item.impact}</p>
               </div>
               <div className="text-right">
                  <p className="text-[8px] font-black text-gray-600 uppercase">ROI</p>
                  <p className="text-[10px] font-bold text-brand-400 uppercase">{item.roi}</p>
               </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );

  return (
    <motion.div 
      initial={{ opacity: 0 }} 
      animate={{ opacity: 1 }}
      className="space-y-8"
    >
      <div className="grid lg:grid-cols-2 gap-8">
         {renderTier(data.high_priority, 'Strategic High-Value', 'bg-red-500', ArrowUpRight)}
         {renderTier(data.medium_priority, 'Targeted Improvements', 'bg-amber-500', Minus)}
      </div>

      <Card className="bg-white/5 border-white/10">
         <CardHeader>
            <CardTitle className="text-sm font-black uppercase tracking-widest text-gray-500 flex items-center gap-3">
               <TrendingUp size={16} className="text-blue-400" /> Utility Queue (Total Items: {data.total_items})
            </CardTitle>
         </CardHeader>
         <CardContent>
            <div className="grid md:grid-cols-3 gap-4">
               {data.low_priority.map((item, idx) => (
                  <div key={idx} className="p-4 rounded-xl bg-black/40 border border-white/5 flex items-center justify-between opacity-60 hover:opacity-100 transition-opacity">
                     <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">{item.enhancement}</span>
                     <span className="text-[10px] font-black text-gray-600 uppercase">ROI: {item.roi}</span>
                  </div>
               ))}
            </div>
         </CardContent>
      </Card>
    </motion.div>
  );
};

export default PriorityMatrixTab;

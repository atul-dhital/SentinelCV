'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Sparkles, Layers, Search } from 'lucide-react';
import { FutureEnhancement } from '@/services/api';

interface EnhancementsTabProps {
  data: FutureEnhancement[];
  togglingId?: string | null;
  onToggle: (storyId: string) => void;
}

const EnhancementsTab: React.FC<EnhancementsTabProps> = ({ data, togglingId = null, onToggle }) => {
  const [filter, setFilter] = useState<string>('all');
  const [search, setSearch] = useState('');

  const categories = ['all', ...Array.from(new Set(data.map(e => e.category)))];
  const filtered = data.filter(e => {
    const matchesFilter = filter === 'all' || e.category === filter;
    const matchesSearch = e.title.toLowerCase().includes(search.toLowerCase()) || 
                          e.story_id.toLowerCase().includes(search.toLowerCase());
    return matchesFilter && matchesSearch;
  });

  const STATUS_COLORS: Record<string, string> = {
    planned: 'bg-gray-500/10 text-gray-400 border-gray-500/20',
    research: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
    prototype: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
    testing: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
    deployed: 'bg-green-500/10 text-green-400 border-green-500/20',
    disabled: 'bg-red-500/10 text-red-100 border-red-500/20',
  };

  return (
    <motion.div 
      initial={{ opacity: 0 }} 
      animate={{ opacity: 1 }}
      className="space-y-6"
    >
      <div className="flex flex-col md:flex-row gap-4 justify-between items-start md:items-center bg-white/5 p-4 rounded-2xl border border-white/10">
        <div className="flex gap-2 flex-wrap">
          {categories.map(cat => (
            <button
              key={cat}
              onClick={() => setFilter(cat)}
              className={`px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
                filter === cat 
                ? 'bg-brand-500 text-white shadow-[0_0_15px_rgba(var(--brand-primary-rgb),0.4)]' 
                : 'bg-white/5 text-gray-500 hover:bg-white/10'
              }`}
            >
              {cat === 'all' ? 'All' : cat.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
        <div className="relative w-full md:w-64">
           <Search size={14} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-600" />
           <input 
             type="text" 
             placeholder="Search enhancements..." 
             className="w-full bg-black/40 border border-white/5 rounded-xl py-2 pl-10 pr-4 text-xs focus:border-brand-500/50 outline-none transition-all"
             value={search}
             onChange={(e) => setSearch(e.target.value)}
           />
        </div>
      </div>

      <div className="grid gap-4">
        <AnimatePresence mode="popLayout">
          {filtered.map((enh, idx) => (
            <motion.div
              layout
              key={enh.story_id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ delay: idx * 0.05 }}
              className="glass-card group flex items-center justify-between p-6 hover:border-brand-500/30 transition-all duration-300"
            >
              <div className="flex items-center gap-6">
                <div className={`p-3 rounded-2xl bg-white/5 border border-white/10 group-hover:scale-110 transition-transform ${enh.enabled ? 'text-brand-400' : 'text-gray-600'}`}>
                  <Sparkles size={24} />
                </div>
                <div>
                  <div className="flex items-center gap-3 mb-1">
                    <span className="text-[10px] font-mono text-gray-500 font-bold">{enh.story_id}</span>
                    <span className={`text-[10px] font-black uppercase tracking-widest px-2 py-0.5 rounded border ${STATUS_COLORS[enh.status]}`}>
                       {enh.status}
                    </span>
                  </div>
                  <h3 className="text-base font-bold text-white group-hover:text-brand-400 transition-colors uppercase tracking-tight">{enh.title}</h3>
                  <p className="text-sm text-gray-500 mt-1 max-w-xl line-clamp-1">{enh.description}</p>
                </div>
              </div>

              <div className="flex items-center gap-6">
                <div className="hidden lg:flex flex-col items-end">
                   <span className="text-[10px] font-black uppercase tracking-widest text-gray-600">Priority</span>
                   <span className={`text-xs font-bold ${enh.priority === 'critical' ? 'text-red-500' : 'text-gray-400'}`}>{enh.priority.toUpperCase()}</span>
                </div>
                <button
                  onClick={() => onToggle(enh.story_id)}
                  disabled={togglingId === enh.story_id}
                  className={`relative p-1 rounded-full w-14 h-8 transition-colors ${enh.enabled ? 'bg-brand-500' : 'bg-white/10'}`}
                >
                  <motion.div 
                    animate={{ x: enh.enabled ? 24 : 0 }}
                    className="w-6 h-6 bg-white rounded-full shadow-lg flex items-center justify-center"
                  >
                    {togglingId === enh.story_id ? (
                      <div className="w-3 h-3 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
                    ) : null}
                  </motion.div>
                </button>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {filtered.length === 0 && (
         <div className="p-20 text-center border-2 border-dashed border-white/5 rounded-3xl">
            <Layers size={48} className="mx-auto text-gray-700 mb-4 opacity-20" />
            <p className="text-gray-500 font-black uppercase tracking-widest text-xs">No matching enhancements found</p>
         </div>
      )}
    </motion.div>
  );
};

export default EnhancementsTab;

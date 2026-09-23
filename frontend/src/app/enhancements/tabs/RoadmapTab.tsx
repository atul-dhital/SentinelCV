'use client';

import React from 'react';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { motion } from 'framer-motion';
import { Milestone, Calendar, Timer } from 'lucide-react';
import { RoadmapResponse } from '@/services/api';

interface RoadmapTabProps {
  data: RoadmapResponse | null;
}

const RoadmapTab: React.FC<RoadmapTabProps> = ({ data }) => {
  if (!data) return (
    <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
       <Timer className="animate-spin text-brand-500" size={32} />
       <p className="text-xs font-black uppercase tracking-widest text-gray-500">Awaiting Roadmap Data...</p>
    </div>
  );

  return (
    <div className="space-y-12 py-4">
      {data.phases.map((phase, phaseIdx) => (
        <motion.div 
          key={phase.phase}
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: phaseIdx * 0.1 }}
          className="relative pl-8 border-l border-white/10 ml-4"
        >
          {/* Phase Marker */}
          <div className="absolute -left-3 top-0 w-6 h-6 rounded-full bg-black border-2 border-brand-500 flex items-center justify-center">
             <div className="w-2 h-2 rounded-full bg-brand-500 shadow-[0_0_10px_rgba(var(--brand-primary-rgb),0.5)]" />
          </div>

          <div className="mb-6">
             <div className="flex items-center gap-2 mb-1 text-xs">
                <Badge variant="secondary" className="opacity-50">PHASE 0{phaseIdx + 1}</Badge>
                <div className="h-px w-8 bg-white/10" />
                <span className="text-[10px] font-black text-gray-500 uppercase tracking-tighter flex items-center gap-1">
                   <Calendar size={10} /> {phase.title}
                </span>
                <span className="ml-auto font-black text-brand-500">{phase.progress_percent}% COMPLETE</span>
             </div>
             <h3 className="text-2xl font-black text-white tracking-tight">{phase.description}</h3>
          </div>

          <div className="grid gap-4">
            {phase.enhancements.map((item) => (
              <Card key={item.story_id} className="group hover:scale-[1.01] transition-all duration-300">
                <CardContent className="p-0">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6">
                    <div className="flex items-center gap-4">
                      <div className={`p-2.5 rounded-xl bg-white/5 border border-white/10 group-hover:border-brand-500/30 transition-colors`}>
                         <Milestone size={20} className="text-gray-400 group-hover:text-brand-400" />
                      </div>
                      <div>
                        <h4 className="font-bold text-white group-hover:text-brand-400 transition-colors uppercase tracking-tight">{item.title}</h4>
                        <p className="text-xs font-mono text-gray-500 uppercase">{item.story_id} • {item.category}</p>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                       <Badge variant={item.priority === 'critical' ? 'destructive' : item.priority === 'high' ? 'default' : 'secondary'}>
                          {item.priority}
                       </Badge>
                       <div className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded bg-white/5 border border-white/5 text-gray-400`}>
                          {item.status}
                       </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </motion.div>
      ))}
    </div>
  );
};

export default RoadmapTab;

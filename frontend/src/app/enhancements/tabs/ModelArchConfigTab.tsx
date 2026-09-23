'use client';

import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { motion } from 'framer-motion';
import { FlaskConical, Cpu, Layers, Box, Save } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { ModelArchitectureResponse } from '@/services/api';

interface ModelArchTabProps {
  data: ModelArchitectureResponse | null;
  onSave?: (data: ModelArchitectureResponse) => void;
  saving?: boolean;
}

const ModelArchConfigTab: React.FC<ModelArchTabProps> = ({ data, onSave, saving }) => {
  const [draft, setDraft] = useState<ModelArchitectureResponse | null>(null);

  useEffect(() => {
    if (!data) {
      setDraft(null);
      return;
    }
    const vitConfig = data.vit_config as Record<string, any>;
    const hybridConfig = data.hybrid_config as Record<string, any>;
    const ensembleConfig = data.ensemble_config as Record<string, any>;

    setDraft({
      ...data,
      vit_config: {
        ...vitConfig,
        enabled: Boolean(vitConfig.enabled ?? vitConfig.vit_enabled ?? false),
        variant: vitConfig.variant ?? vitConfig.vit_variant ?? null,
      },
      hybrid_config: {
        ...hybridConfig,
        enabled: Boolean(hybridConfig.enabled ?? hybridConfig.hybrid_cnn_transformer ?? false),
        cnn_backbone: hybridConfig.cnn_backbone ?? 'resnet100',
      },
      ensemble_config: {
        ...ensembleConfig,
        enabled: Boolean(ensembleConfig.enabled ?? ensembleConfig.ensemble_enabled ?? false),
        methods: ensembleConfig.methods ?? ensembleConfig.ensemble_methods ?? [],
      },
    });
  }, [data]);

  if (!draft) return (
     <div className="flex flex-col items-center justify-center p-20 gap-4 opacity-50">
        <FlaskConical className="animate-pulse text-brand-500" size={32} />
        <p className="text-xs font-black uppercase tracking-widest text-gray-500">Loading Neural Blueprint...</p>
     </div>
  );

  const vitConfig = draft.vit_config as Record<string, any>;
  const hybridConfig = draft.hybrid_config as Record<string, any>;
  const ensembleConfig = draft.ensemble_config as Record<string, any>;
  const availableMethods = draft.available_ensemble_methods || [];
  const activeModel = ensembleConfig.enabled
    ? 'ensemble'
    : vitConfig.enabled
      ? 'vit'
      : 'arcface';

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }} 
      animate={{ opacity: 1, y: 0 }}
      className="space-y-8"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-black uppercase tracking-tighter">Model Architecture Control</h2>
          <p className="text-sm text-gray-400">Tune ViT and hybrid settings for next-gen recognition.</p>
        </div>
        <Button onClick={() => onSave?.(draft)} disabled={!onSave || saving} className="gap-2">
          <Save size={16} />
          {saving ? 'Saving...' : 'Save Configuration'}
        </Button>
      </div>

      <Card className="border-white/5 bg-white/5">
        <CardHeader>
          <CardTitle className="text-sm uppercase tracking-widest text-gray-500">Active Runtime Model</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          {[
            { id: 'arcface', label: 'ArcFace (CNN)' },
            { id: 'vit', label: 'Vision Transformer' },
            { id: 'ensemble', label: 'Ensemble (ArcFace + ViT)' },
          ].map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => {
                const nextVitEnabled = option.id !== 'arcface';
                const nextEnsembleEnabled = option.id === 'ensemble';
                setDraft({
                  ...draft,
                  vit_config: { ...vitConfig, enabled: nextVitEnabled },
                  ensemble_config: { ...ensembleConfig, enabled: nextEnsembleEnabled },
                });
              }}
              className={`px-4 py-2 rounded-xl border text-xs font-black uppercase tracking-widest transition-all ${activeModel === option.id
                ? 'bg-brand-500/20 border-brand-500/40 text-brand-300'
                : 'bg-black/40 border-white/10 text-gray-500 hover:text-white'
                }`}
            >
              {option.label}
            </button>
          ))}
          <p className="text-xs text-gray-500 w-full">
            Selection updates the runtime registry for the AI service after save.
          </p>
        </CardContent>
      </Card>

      <div className="grid lg:grid-cols-3 gap-6">
         <Card className="lg:col-span-2">
            <CardHeader className="flex flex-row items-center gap-4">
               <div className="p-3 rounded-2xl bg-brand-500/10 border border-brand-500/20">
                 <FlaskConical className="text-brand-500" size={24} />
               </div>
               <div>
                  <CardTitle>Core Architecture</CardTitle>
                  <p className="text-sm text-gray-400">Current Backbone: <span className="text-brand-400 font-black uppercase tracking-widest">{draft.current_architecture}</span></p>
               </div>
            </CardHeader>
            <CardContent>
               <div className="grid sm:grid-cols-2 gap-4">
                  <div className="p-6 rounded-2xl bg-white/5 border border-white/10 hover:border-brand-500/30 transition-all space-y-3">
                     <div className="flex items-center justify-between">
                       <h4 className="text-[10px] font-black uppercase tracking-widest text-gray-500 flex items-center gap-2">
                          <Layers size={12} className="text-blue-400" /> Vision Transformers (ViT)
                       </h4>
                       <button
                         onClick={() => setDraft({
                           ...draft,
                           vit_config: { ...vitConfig, enabled: !vitConfig.enabled },
                         })}
                         className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded ${vitConfig.enabled ? 'bg-brand-500/20 text-brand-300' : 'bg-white/5 text-gray-500'}`}
                       >
                         {vitConfig.enabled ? 'Enabled' : 'Disabled'}
                       </button>
                     </div>
                     <select
                       value={vitConfig.variant || ''}
                       onChange={(event) => setDraft({
                         ...draft,
                         vit_config: { ...vitConfig, variant: event.target.value || null },
                       })}
                       className="h-10 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-xs text-gray-100"
                     >
                       <option value="">Select ViT variant</option>
                       {draft.available_vit_variants.map((variant) => (
                         <option key={variant} value={variant}>{variant}</option>
                       ))}
                     </select>
                     <p className="text-xs text-gray-400 leading-relaxed">
                        {vitConfig.benefits ? vitConfig.benefits.join(', ') : 'Optimized for global context attention.'}
                     </p>
                  </div>
                  <div className="p-6 rounded-2xl bg-white/5 border border-white/10 hover:border-brand-500/30 transition-all space-y-3">
                     <div className="flex items-center justify-between">
                       <h4 className="text-[10px] font-black uppercase tracking-widest text-gray-500 flex items-center gap-2">
                          <Cpu size={12} className="text-purple-400" /> Hybrid Models
                       </h4>
                       <button
                         onClick={() => setDraft({
                           ...draft,
                           hybrid_config: { ...hybridConfig, enabled: !hybridConfig.enabled },
                         })}
                         className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded ${hybridConfig.enabled ? 'bg-purple-500/20 text-purple-300' : 'bg-white/5 text-gray-500'}`}
                       >
                         {hybridConfig.enabled ? 'Enabled' : 'Disabled'}
                       </button>
                     </div>
                     <select
                       value={hybridConfig.cnn_backbone || ''}
                       onChange={(event) => setDraft({
                         ...draft,
                         hybrid_config: { ...hybridConfig, cnn_backbone: event.target.value },
                       })}
                       className="h-10 w-full rounded-xl border border-white/10 bg-black/30 px-3 text-xs text-gray-100"
                     >
                       {draft.available_backbones.map((backbone) => (
                         <option key={backbone} value={backbone}>{backbone}</option>
                       ))}
                     </select>
                     <p className="text-xs text-gray-400 leading-relaxed">
                        {hybridConfig.description || 'Seamless fusion of CNN and Transformer layers.'}
                     </p>
                  </div>
               </div>
            </CardContent>
         </Card>

         <Card>
            <CardHeader>
               <CardTitle className="text-sm uppercase tracking-widest text-gray-500">Available Components</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
                <div className="space-y-2">
                   <p className="text-[10px] font-black uppercase tracking-widest text-brand-500/60">Backbones</p>
                   <div className="flex flex-wrap gap-2">
                      {draft.available_backbones.map(b => (
                         <span key={b} className="px-2 py-1 rounded bg-white/5 border border-white/10 text-[10px] font-bold text-gray-400 uppercase">{b}</span>
                      ))}
                   </div>
                </div>
                <div className="space-y-2">
                   <p className="text-[10px] font-black uppercase tracking-widest text-brand-500/60">ViT Variants</p>
                   <div className="flex flex-wrap gap-2">
                      {draft.available_vit_variants.map(v => (
                         <span key={v} className="px-2 py-1 rounded bg-white/5 border border-white/10 text-[10px] font-bold text-gray-400 uppercase">{v}</span>
                      ))}
                   </div>
                </div>
            </CardContent>
         </Card>
      </div>

      <Card className="border-brand-500/20 bg-brand-500/5">
        <CardHeader>
           <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                 <div className="p-2 rounded-xl bg-brand-500/20 text-brand-400">
                    <Box size={20} />
                 </div>
               <h3 className="text-base font-black uppercase tracking-widest text-white">Ensemble Fusion Strategy</h3>
               </div>
               <button
                 onClick={() => setDraft({
                   ...draft,
                   ensemble_config: { ...ensembleConfig, enabled: !ensembleConfig.enabled },
                 })}
                 className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded ${ensembleConfig.enabled ? 'bg-brand-500/20 text-brand-300' : 'bg-white/5 text-gray-500'}`}
               >
                 {ensembleConfig.enabled ? 'Enabled' : 'Disabled'}
               </button>
            </div>
        </CardHeader>
        <CardContent>
           <div className="grid md:grid-cols-3 gap-3">
              {availableMethods.map((method) => {
                const isSelected = (ensembleConfig.methods || []).includes(method);
                return (
                  <button
                    type="button"
                    key={method}
                    onClick={() => {
                      const current = ensembleConfig.methods || [];
                      const next = isSelected ? current.filter((m: string) => m !== method) : [...current, method];
                      setDraft({
                        ...draft,
                        ensemble_config: { ...ensembleConfig, methods: next },
                      });
                    }}
                    className={`flex items-center gap-3 p-4 rounded-xl border text-xs font-bold uppercase tracking-tighter transition-all ${
                      isSelected
                        ? 'bg-brand-500/20 border-brand-500/40 text-brand-300'
                        : 'bg-black/40 border-white/5 text-gray-400'
                    }`}
                  >
                    <div className="w-2 h-2 rounded-full bg-brand-500" />
                    {method}
                  </button>
                );
              })}
           </div>
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default ModelArchConfigTab;

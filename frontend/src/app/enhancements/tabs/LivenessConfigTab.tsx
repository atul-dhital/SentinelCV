'use client';

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Shield, Save, RefreshCw, Eye, Video, Scan, Activity } from 'lucide-react';
import { livenessService } from '@/services/api';

interface LivenessConfig {
  enabled: boolean;
  min_face_size: number;
  texture_enabled: boolean;
  motion_enabled: boolean;
  deep_learning_enabled: boolean;
  overall_confidence_threshold: number;
  texture_score_threshold: number;
  motion_score_threshold: number;
  deep_learning_threshold: number;
  video_required: boolean;
  min_video_frames: number;
  min_motion_frames: number;
  challenge_enabled: boolean;
  challenge_types: string[];
  detect_print_attacks: boolean;
  detect_replay_attacks: boolean;
  detect_mask_attacks: boolean;
  ensemble_method: string;
  min_illumination_score: number;
  max_blur_score: number;
}

interface LivenessStatistics {
  total_detections: number;
  live_count: number;
  spoof_count: number;
  live_percentage: number;
  average_liveness_score: number;
  most_common_rejection_reason: string | null;
  attack_detection_rate: number;
  average_processing_time_ms: number;
  method_distribution: Record<string, number>;
}

const DEFAULT_CONFIG: LivenessConfig = {
  enabled: true,
  min_face_size: 80,
  texture_enabled: true,
  motion_enabled: true,
  deep_learning_enabled: true,
  overall_confidence_threshold: 0.7,
  texture_score_threshold: 0.5,
  motion_score_threshold: 0.5,
  deep_learning_threshold: 0.6,
  video_required: true,
  min_video_frames: 30,
  min_motion_frames: 10,
  challenge_enabled: false,
  challenge_types: ['blink'],
  detect_print_attacks: true,
  detect_replay_attacks: true,
  detect_mask_attacks: true,
  ensemble_method: 'average',
  min_illumination_score: 0.3,
  max_blur_score: 0.7,
};

const CHALLENGE_OPTIONS = ['blink', 'head_turn', 'smile'] as const;
const ENSEMBLE_OPTIONS = ['average', 'weighted', 'voting'] as const;

export default function LivenessConfigTab() {
  const [config, setConfig] = useState<LivenessConfig>(DEFAULT_CONFIG);
  const [stats, setStats] = useState<LivenessStatistics | null>(null);
  const [saving, setSaving] = useState(false);
  const [loadingStats, setLoadingStats] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    loadConfig();
    loadStats();
  }, []);

  const loadConfig = async () => {
    try {
      const res = await livenessService.getConfig();
      setConfig({ ...DEFAULT_CONFIG, ...res.data });
    } catch (err) {
      console.error('Failed to load liveness config:', err);
    }
  };

  const loadStats = async () => {
    setLoadingStats(true);
    try {
      const res = await livenessService.getStatistics();
      setStats(res.data);
    } catch (err) {
      console.error('Failed to load liveness statistics:', err);
    } finally {
      setLoadingStats(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const res = await livenessService.updateConfig(config);
      setConfig({ ...DEFAULT_CONFIG, ...res.data });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      console.error('Failed to save liveness config:', err);
    } finally {
      setSaving(false);
    }
  };

  const updateField = <K extends keyof LivenessConfig>(key: K, value: LivenessConfig[K]) => {
    setConfig(prev => ({ ...prev, [key]: value }));
  };

  const toggleChallengeType = (type: string) => {
    setConfig(prev => {
      const types = prev.challenge_types.includes(type)
        ? prev.challenge_types.filter(t => t !== type)
        : [...prev.challenge_types, type];
      return { ...prev, challenge_types: types };
    });
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield className="text-brand-500" size={24} />
          <div>
            <h2 className="text-xl font-bold text-white">Liveness Detection Configuration</h2>
            <p className="text-sm text-gray-400">Configure anti-spoofing detection methods, thresholds, and challenge-response settings</p>
          </div>
        </div>
        <div className="flex gap-3">
          <button
            onClick={loadStats}
            disabled={loadingStats}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold bg-white/5 text-gray-400 hover:bg-white/10 border border-white/10 transition-all"
          >
            <RefreshCw size={14} className={loadingStats ? 'animate-spin' : ''} />
            Refresh Stats
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2 rounded-xl text-xs font-bold bg-brand-600 text-white hover:bg-brand-500 transition-all shadow-[0_0_15px_rgba(var(--brand-primary-rgb),0.3)]"
          >
            <Save size={14} />
            {saving ? 'Saving...' : saved ? 'Saved!' : 'Save Config'}
          </button>
        </div>
      </div>

      {/* Statistics Summary */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Total Detections', value: stats.total_detections, icon: Scan },
            { label: 'Live Rate', value: `${stats.live_percentage.toFixed(1)}%`, icon: Eye },
            { label: 'Attack Detection', value: `${(stats.attack_detection_rate * 100).toFixed(1)}%`, icon: Shield },
            { label: 'Avg Processing', value: `${stats.average_processing_time_ms.toFixed(0)}ms`, icon: Activity },
          ].map(({ label, value, icon: Icon }) => (
            <div key={label} className="bg-white/5 rounded-2xl p-4 border border-white/10">
              <div className="flex items-center gap-2 mb-2">
                <Icon size={14} className="text-brand-500" />
                <span className="text-xs text-gray-500 uppercase tracking-wider">{label}</span>
              </div>
              <span className="text-2xl font-black text-white">{value}</span>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Detection Methods */}
        <div className="bg-white/5 rounded-2xl p-6 border border-white/10 space-y-4">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
            <Scan size={16} className="text-brand-500" />
            Detection Methods
          </h3>

          <ToggleRow label="Liveness Detection Enabled" checked={config.enabled} onChange={v => updateField('enabled', v)} />
          <ToggleRow label="Texture Analysis (LBP)" checked={config.texture_enabled} onChange={v => updateField('texture_enabled', v)} />
          <ToggleRow label="Motion Analysis (Optical Flow)" checked={config.motion_enabled} onChange={v => updateField('motion_enabled', v)} />
          <ToggleRow label="Deep Learning (Spectral/CNN)" checked={config.deep_learning_enabled} onChange={v => updateField('deep_learning_enabled', v)} />

          <div className="pt-2">
            <label className="text-xs text-gray-400 block mb-1">Ensemble Method</label>
            <select
              value={config.ensemble_method}
              onChange={e => updateField('ensemble_method', e.target.value)}
              className="w-full bg-black/30 text-white rounded-xl px-4 py-2 text-sm border border-white/10 focus:border-brand-500 outline-none"
            >
              {ENSEMBLE_OPTIONS.map(opt => (
                <option key={opt} value={opt}>{opt.charAt(0).toUpperCase() + opt.slice(1)}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Thresholds */}
        <div className="bg-white/5 rounded-2xl p-6 border border-white/10 space-y-4">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
            <Activity size={16} className="text-brand-500" />
            Confidence Thresholds
          </h3>

          <SliderRow label="Overall Confidence" value={config.overall_confidence_threshold} onChange={v => updateField('overall_confidence_threshold', v)} />
          <SliderRow label="Texture Score" value={config.texture_score_threshold} onChange={v => updateField('texture_score_threshold', v)} />
          <SliderRow label="Motion Score" value={config.motion_score_threshold} onChange={v => updateField('motion_score_threshold', v)} />
          <SliderRow label="Deep Learning Score" value={config.deep_learning_threshold} onChange={v => updateField('deep_learning_threshold', v)} />
          <SliderRow label="Min Illumination" value={config.min_illumination_score} onChange={v => updateField('min_illumination_score', v)} />
          <SliderRow label="Max Blur Score" value={config.max_blur_score} onChange={v => updateField('max_blur_score', v)} />
        </div>

        {/* Video & Frames */}
        <div className="bg-white/5 rounded-2xl p-6 border border-white/10 space-y-4">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
            <Video size={16} className="text-brand-500" />
            Video Requirements
          </h3>

          <ToggleRow label="Video Required" checked={config.video_required} onChange={v => updateField('video_required', v)} />

          <NumberRow label="Min Video Frames" value={config.min_video_frames} onChange={v => updateField('min_video_frames', v)} min={1} max={300} />
          <NumberRow label="Min Motion Frames" value={config.min_motion_frames} onChange={v => updateField('min_motion_frames', v)} min={1} max={100} />
          <NumberRow label="Min Face Size (px)" value={config.min_face_size} onChange={v => updateField('min_face_size', v)} min={20} max={500} />
        </div>

        {/* Attack Detection */}
        <div className="bg-white/5 rounded-2xl p-6 border border-white/10 space-y-4">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
            <Shield size={16} className="text-brand-500" />
            Attack Detection
          </h3>

          <ToggleRow label="Detect Print Attacks" checked={config.detect_print_attacks} onChange={v => updateField('detect_print_attacks', v)} />
          <ToggleRow label="Detect Replay Attacks" checked={config.detect_replay_attacks} onChange={v => updateField('detect_replay_attacks', v)} />
          <ToggleRow label="Detect Mask Attacks" checked={config.detect_mask_attacks} onChange={v => updateField('detect_mask_attacks', v)} />
        </div>

        {/* Challenge-Response */}
        <div className="bg-white/5 rounded-2xl p-6 border border-white/10 space-y-4 lg:col-span-2">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
            <Eye size={16} className="text-brand-500" />
            Challenge-Response
          </h3>

          <ToggleRow label="Challenge Mode Enabled" checked={config.challenge_enabled} onChange={v => updateField('challenge_enabled', v)} />

          {config.challenge_enabled && (
            <div className="flex gap-3 pt-2">
              {CHALLENGE_OPTIONS.map(type => {
                const active = config.challenge_types.includes(type);
                return (
                  <button
                    key={type}
                    onClick={() => toggleChallengeType(type)}
                    className={`px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wider border transition-all ${
                      active
                        ? 'bg-brand-600/20 text-brand-400 border-brand-500/30'
                        : 'bg-white/5 text-gray-500 border-white/10 hover:bg-white/10'
                    }`}
                  >
                    {type.replace('_', ' ')}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Method Distribution */}
      {stats && Object.keys(stats.method_distribution).length > 0 && (
        <div className="bg-white/5 rounded-2xl p-6 border border-white/10">
          <h3 className="text-sm font-bold text-white uppercase tracking-wider mb-4">Method Usage Distribution</h3>
          <div className="flex gap-4">
            {Object.entries(stats.method_distribution).map(([method, count]) => {
              const total = Object.values(stats.method_distribution).reduce((a, b) => a + b, 0);
              const pct = total > 0 ? ((count / total) * 100).toFixed(1) : '0';
              return (
                <div key={method} className="flex-1 bg-black/20 rounded-xl p-4 border border-white/5">
                  <div className="text-xs text-gray-500 uppercase tracking-wider mb-1">{method}</div>
                  <div className="text-lg font-bold text-white">{count}</div>
                  <div className="text-xs text-brand-400">{pct}%</div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </motion.div>
  );
}

function ToggleRow({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-gray-300">{label}</span>
      <button
        onClick={() => onChange(!checked)}
        className={`relative w-11 h-6 rounded-full transition-colors ${checked ? 'bg-brand-600' : 'bg-white/10'}`}
      >
        <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${checked ? 'translate-x-5' : ''}`} />
      </button>
    </div>
  );
}

function SliderRow({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm text-gray-300">{label}</span>
        <span className="text-xs font-mono text-brand-400">{value.toFixed(2)}</span>
      </div>
      <input
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={value}
        onChange={e => onChange(parseFloat(e.target.value))}
        className="w-full accent-brand-500"
      />
    </div>
  );
}

function NumberRow({ label, value, onChange, min, max }: { label: string; value: number; onChange: (v: number) => void; min: number; max: number }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-gray-300">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={e => onChange(parseInt(e.target.value) || min)}
        className="w-24 bg-black/30 text-white rounded-lg px-3 py-1.5 text-sm border border-white/10 focus:border-brand-500 outline-none text-right"
      />
    </div>
  );
}

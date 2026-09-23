'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { Activity, Brain, Cpu, Gauge, Search, Sparkles } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import {
  ActionInferResponse,
  BehaviorAnalysisResponse,
  BehaviorEventListResponse,
  BenchmarkSummaryResponse,
  ContinuousLearningSignalListResponse,
  CrossCameraMovementListResponse,
  CrossCameraReidResponse,
  HealthReadinessResponse,
  MLflowRegistryResponse,
  MLflowPromotionHealthSummary,
  NLAnalyticsQueryResponse,
  PoseEstimateResponse,
  RuntimeModelRegistryResponse,
  StreamHealthItem,
  VisionAnalyticsHistoryResponse,
} from '@/services/api';

interface FoundationOpsTabProps {
  runtimeRegistry: RuntimeModelRegistryResponse | null;
  benchmarkSummary: BenchmarkSummaryResponse | null;
  readiness: HealthReadinessResponse | null;
  mlflowRegistry: MLflowRegistryResponse | null;
  mlflowHealthSummary: MLflowPromotionHealthSummary | null;
  streamHealth: StreamHealthItem[];
  reidResult: CrossCameraReidResponse | null;
  movementSummary: CrossCameraMovementListResponse | null;
  poseResult: PoseEstimateResponse | null;
  actionResult: ActionInferResponse | null;
  behaviorAnalysis: BehaviorAnalysisResponse | null;
  behaviorEvents: BehaviorEventListResponse | null;
  learningSignals: ContinuousLearningSignalListResponse | null;
  visionHistory?: VisionAnalyticsHistoryResponse | null;
  analyticsAnswer: NLAnalyticsQueryResponse | null;
  runningBenchmark: boolean;
  queryingReid: boolean;
  queryingAnalytics: boolean;
  runningPoseEstimate: boolean;
  runningActionInference: boolean;
  analyzingBehavior: boolean;
  refreshingStreamHealth: boolean;
  syncingMovements: boolean;
  queueingSignals: boolean;
  promotingModel: boolean;
  onRunBenchmark: () => Promise<void>;
  onSearchCrossCameraReid: (data: {
    camera_id?: string;
    lookback_minutes?: number;
    limit?: number;
    min_camera_count?: number;
    min_sightings?: number;
    min_avg_confidence?: number;
    min_reid_score?: number;
  }) => Promise<void>;
  onSyncCrossCameraMovements: (data: {
    camera_id?: string;
    lookback_minutes?: number;
    limit?: number;
    min_camera_count?: number;
    min_sightings?: number;
    min_avg_confidence?: number;
    min_reid_score?: number;
  }) => Promise<void>;
  onRunAnalyticsQuery: (query: string) => Promise<void>;
  onRunPoseEstimate: (cameraId: string) => Promise<void>;
  onRunActionInference: (cameraId: string) => Promise<void>;
  onAnalyzeBehavior: (cameraId: string) => Promise<void>;
  onQueueLearningSignals: () => Promise<void>;
  onUpdateLearningSignal: (signalId: string, data: { status: string; resolution?: string; notes?: string }) => Promise<void>;
  onPromoteLearningSignal: (signalId: string, data?: { visitor_id?: string; is_positive?: boolean; source?: string }) => Promise<void>;
  onRefreshStreamHealth: (probeMode?: boolean) => Promise<void>;
  onRefreshVisionHistory?: () => Promise<void>;
  onPromoteModel: (data: {
    component: string;
    candidate_model: string;
    candidate_artifact?: string;
    reason?: string;
    benchmark_sample_size?: number;
    require_production_ready?: boolean;
  }) => Promise<void>;
}

const FoundationOpsTab: React.FC<FoundationOpsTabProps> = ({
  runtimeRegistry,
  benchmarkSummary,
  readiness,
  mlflowRegistry,
  mlflowHealthSummary,
  streamHealth,
  reidResult,
  movementSummary,
  poseResult,
  actionResult,
  behaviorAnalysis,
  behaviorEvents,
  learningSignals,
  visionHistory,
  analyticsAnswer,
  runningBenchmark,
  queryingReid,
  queryingAnalytics,
  runningPoseEstimate,
  runningActionInference,
  analyzingBehavior,
  refreshingStreamHealth,
  syncingMovements,
  queueingSignals,
  promotingModel,
  onRunBenchmark,
  onSearchCrossCameraReid,
  onSyncCrossCameraMovements,
  onRunAnalyticsQuery,
  onRunPoseEstimate,
  onRunActionInference,
  onAnalyzeBehavior,
  onQueueLearningSignals,
  onUpdateLearningSignal,
  onPromoteLearningSignal,
  onRefreshStreamHealth,
  onRefreshVisionHistory,
  onPromoteModel,
}) => {
  const [analyticsQuery, setAnalyticsQuery] = useState('Show camera health in the last 2 hours');
  const [reidCameraId, setReidCameraId] = useState('');
  const [reidLookbackMinutes, setReidLookbackMinutes] = useState(120);
  const [reidMinSightings, setReidMinSightings] = useState(1);
  const [reidMinConfidence, setReidMinConfidence] = useState(0.0);
  const [reidMinScore, setReidMinScore] = useState(0.0);
  const [visionCameraId, setVisionCameraId] = useState('');
  const [promotionComponent, setPromotionComponent] = useState('');
  const [candidateModel, setCandidateModel] = useState('');
  const [candidateArtifact, setCandidateArtifact] = useState('');
  const [promotionReason, setPromotionReason] = useState('');

  useEffect(() => {
    if (!reidCameraId && streamHealth.length > 0) {
      setReidCameraId(streamHealth[0].camera_id);
    }
    if (!visionCameraId && streamHealth.length > 0) {
      setVisionCameraId(streamHealth[0].camera_id);
    }
  }, [streamHealth, reidCameraId, visionCameraId]);

  useEffect(() => {
    if (!promotionComponent && runtimeRegistry?.components?.length) {
      setPromotionComponent(runtimeRegistry.components[0].component);
    }
  }, [runtimeRegistry, promotionComponent]);

  useEffect(() => {
    if (!promotionComponent || candidateArtifact.trim()) {
      return;
    }
    const selected = (runtimeRegistry?.components || []).find((item) => item.component === promotionComponent);
    if (selected?.target_artifact) {
      setCandidateArtifact(selected.target_artifact);
    }
  }, [runtimeRegistry, promotionComponent, candidateArtifact]);

  const recentPromotions = useMemo(
    () => (mlflowRegistry?.promotions || []).slice(0, 5),
    [mlflowRegistry],
  );

  const handlePromote = async () => {
    if (!promotionComponent || !candidateModel.trim()) {
      return;
    }
    await onPromoteModel({
      component: promotionComponent,
      candidate_model: candidateModel.trim(),
      candidate_artifact: candidateArtifact.trim() || undefined,
      reason: promotionReason.trim() || undefined,
      benchmark_sample_size: 30,
      require_production_ready: true,
    });
    setCandidateModel('');
    setCandidateArtifact('');
    setPromotionReason('');
  };

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader className="border-b border-white/5 bg-sky-500/5">
          <CardTitle className="flex items-center gap-3 text-sky-400">
            <Cpu size={20} />
            Runtime Model Inventory
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-3 max-h-[420px] overflow-auto">
          {(runtimeRegistry?.components || []).map((component) => (
            <div key={component.component} className="rounded-xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center justify-between gap-3 mb-1">
                <h4 className="text-sm font-bold text-gray-100">{component.display_name}</h4>
                <span className="text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border border-white/10 text-gray-400">
                  {component.status}
                </span>
              </div>
              <p className="text-xs text-gray-300">Current: {component.current_model}</p>
              {component.target_model && <p className="text-xs text-gray-500">Target: {component.target_model}</p>}
              {component.target_artifact && <p className="text-xs text-gray-500">Target artifact: {component.target_artifact}</p>}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-indigo-500/5">
          <CardTitle className="flex items-center gap-3 text-indigo-400">
            <Activity size={20} />
            Operational Readiness
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-3">
          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <p className="text-xs text-gray-500 uppercase tracking-widest mb-2">Current posture</p>
            <p className="text-sm text-gray-100 font-bold">{readiness?.status || 'unknown'}</p>
            <p className="text-xs text-gray-500 mt-2">
              This reads the live backend readiness checks, so infrastructure labels reflect the actual runtime environment.
            </p>
          </div>
          {Object.entries(readiness?.checks || {}).map(([key, check]) => (
            <div key={key} className="rounded-xl border border-white/10 bg-black/20 p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-black uppercase tracking-widest text-gray-400">{key.replaceAll('_', ' ')}</p>
                <span
                  className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border ${
                    check.status === 'pass'
                      ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
                      : check.status === 'warn'
                        ? 'border-amber-500/20 bg-amber-500/10 text-amber-400'
                        : 'border-red-500/20 bg-red-500/10 text-red-400'
                  }`}
                >
                  {check.status}
                </span>
              </div>
              <p className="text-sm text-gray-200 mt-2">
                {typeof check.value === 'string' ? check.value : JSON.stringify(check.value)}
              </p>
              <p className="text-xs text-gray-500 mt-1">{check.detail}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-emerald-500/5">
          <CardTitle className="flex items-center gap-3 text-emerald-400">
            <Gauge size={20} />
            Benchmark And Promotion Control
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-4">
          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <p className="text-xs text-gray-500 uppercase tracking-widest mb-2">Baseline Benchmark</p>
            <p className="text-sm text-gray-200">Status: {benchmarkSummary?.status || 'not_run'}</p>
            <p className="text-sm text-gray-200">Baseline Accuracy: {benchmarkSummary?.baseline_accuracy ?? '-'}%</p>
            <p className="text-sm text-gray-200">Avg Latency: {benchmarkSummary?.avg_latency_ms ?? '-'} ms</p>
            <p className="text-xs text-gray-500 mt-2">{benchmarkSummary?.recommendation || 'Run baseline benchmark to populate metrics.'}</p>
          </div>
          <Button onClick={onRunBenchmark} disabled={runningBenchmark}>
            {runningBenchmark ? 'Running Benchmark...' : 'Run Baseline Benchmark'}
          </Button>

          <div className="rounded-xl border border-white/10 bg-white/5 p-4 grid gap-2">
            <p className="text-xs text-gray-500 uppercase tracking-widest">MLflow Registry</p>
            <p className="text-xs text-gray-300">Tracking URI: {mlflowRegistry?.tracking_uri || '-'}</p>
            <p className="text-xs text-gray-300">MLflow runtime: {mlflowRegistry?.mlflow_available ? 'available' : 'not installed'}</p>
            <div className="grid grid-cols-3 gap-2 text-[11px]">
              <div className="rounded-lg border border-white/10 bg-black/20 p-2">
                <p className="text-gray-500 uppercase tracking-widest">Total</p>
                <p className="text-gray-100 font-bold">{mlflowHealthSummary?.total_promotions ?? 0}</p>
              </div>
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-2">
                <p className="text-emerald-300 uppercase tracking-widest">Applied</p>
                <p className="text-emerald-200 font-bold">{mlflowHealthSummary?.applied_promotions ?? 0}</p>
              </div>
              <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2">
                <p className="text-amber-300 uppercase tracking-widest">Blocked</p>
                <p className="text-amber-200 font-bold">{mlflowHealthSummary?.blocked_promotions ?? 0}</p>
              </div>
            </div>
            <p className="text-xs text-gray-500">Last promotion: {mlflowHealthSummary?.last_promotion_at || 'n/a'}</p>
            <p className="text-xs text-gray-500">If candidate artifact is empty, promotion uses component target artifact mapping.</p>
            <select
              value={promotionComponent}
              onChange={(e) => setPromotionComponent(e.target.value)}
              className="h-11 rounded-xl border border-white/10 bg-white/5 px-3 text-sm text-gray-100"
            >
              {(runtimeRegistry?.components || []).map((component) => (
                <option key={component.component} value={component.component}>
                  {component.display_name}
                </option>
              ))}
            </select>
            <Input value={candidateModel} onChange={(e) => setCandidateModel(e.target.value)} placeholder="Candidate model (for example AdaFace)" />
            <Input value={candidateArtifact} onChange={(e) => setCandidateArtifact(e.target.value)} placeholder="Candidate artifact path (optional)" />
            <Input value={promotionReason} onChange={(e) => setPromotionReason(e.target.value)} placeholder="Promotion reason (optional)" />
            <Button onClick={handlePromote} disabled={promotingModel || !promotionComponent || !candidateModel.trim()}>
              {promotingModel ? 'Promoting...' : 'Promote Candidate (Benchmark Gated)'}
            </Button>
            {recentPromotions.length > 0 && (
              <div className="pt-2 grid gap-2">
                {recentPromotions.map((item) => (
                  <div key={item.promotion_id} className="rounded-lg border border-white/10 bg-black/20 p-2">
                    <p className="text-xs text-gray-200">
                      {item.component}: {item.previous_model || '-'} {'->'} {item.candidate_model}
                    </p>
                    <p className="text-[11px] text-gray-500">
                      {item.applied ? 'applied' : 'blocked'} | benchmark={item.benchmark_status}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-amber-500/5">
          <CardTitle className="flex items-center gap-3 text-amber-400">
            <Activity size={20} />
            Stream Health
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-3 max-h-[420px] overflow-auto">
          <div className="flex gap-2">
            <Button className="flex-1" onClick={() => onRefreshStreamHealth(false)} disabled={refreshingStreamHealth}>
              {refreshingStreamHealth ? 'Refreshing...' : 'Refresh (DB)'}
            </Button>
            <Button className="flex-1" onClick={() => onRefreshStreamHealth(true)} disabled={refreshingStreamHealth}>
              Active Probe
            </Button>
          </div>
          {streamHealth.length === 0 && <p className="text-xs text-gray-500">No camera health records yet.</p>}
          {streamHealth.map((item) => (
            <div key={item.camera_id} className="rounded-xl border border-white/10 bg-white/5 p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-gray-100">{item.camera_name}</p>
                <span className={`text-[10px] uppercase tracking-widest px-2 py-1 rounded border ${item.is_stale ? 'text-red-400 border-red-500/30 bg-red-500/10' : 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10'}`}>
                  {item.is_stale ? 'stale' : 'healthy'}
                </span>
              </div>
              <p className="text-xs text-gray-400">Status: {item.status}</p>
              <p className="text-xs text-gray-500">{item.recovery_hint}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-indigo-500/5">
          <CardTitle className="flex items-center gap-3 text-indigo-400">
            <Search size={20} />
            Cross-Camera ReID
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-3">
          <select
            value={reidCameraId}
            onChange={(e) => setReidCameraId(e.target.value)}
            className="h-11 rounded-xl border border-white/10 bg-white/5 px-3 text-sm text-gray-100"
          >
            <option value="">Any camera</option>
            {streamHealth.map((camera) => (
              <option key={camera.camera_id} value={camera.camera_id}>
                {camera.camera_name}
              </option>
            ))}
          </select>
          <Input
            type="number"
            value={reidLookbackMinutes}
            onChange={(e) => setReidLookbackMinutes(Number(e.target.value) || 120)}
            placeholder="Lookback minutes"
          />
          <div className="grid gap-2 md:grid-cols-3">
            <Input
              type="number"
              value={reidMinSightings}
              onChange={(e) => setReidMinSightings(Number(e.target.value) || 1)}
              placeholder="Min sightings"
            />
            <Input
              type="number"
              step="0.05"
              value={reidMinConfidence}
              onChange={(e) => setReidMinConfidence(Number(e.target.value) || 0)}
              placeholder="Min avg confidence"
            />
            <Input
              type="number"
              step="0.05"
              value={reidMinScore}
              onChange={(e) => setReidMinScore(Number(e.target.value) || 0)}
              placeholder="Min ReID score"
            />
          </div>
          <div className="flex gap-2">
            <Button
              className="flex-1"
              onClick={() => onSearchCrossCameraReid({
                camera_id: reidCameraId || undefined,
                lookback_minutes: reidLookbackMinutes,
                limit: 10,
                min_camera_count: 2,
                min_sightings: reidMinSightings,
                min_avg_confidence: reidMinConfidence,
                min_reid_score: reidMinScore,
              })}
              disabled={queryingReid}
            >
              {queryingReid ? 'Searching...' : 'Run ReID Search'}
            </Button>
            <Button
              className="flex-1"
              onClick={() => onSyncCrossCameraMovements({
                camera_id: reidCameraId || undefined,
                lookback_minutes: reidLookbackMinutes,
                limit: 10,
                min_camera_count: 2,
                min_sightings: reidMinSightings,
                min_avg_confidence: reidMinConfidence,
                min_reid_score: reidMinScore,
              })}
              disabled={syncingMovements}
            >
              {syncingMovements ? 'Syncing...' : 'Persist Movements'}
            </Button>
          </div>

          {reidResult && (
            <div className="rounded-xl border border-white/10 bg-white/5 p-4 grid gap-2">
              <p className="text-xs text-gray-400">
                Matches: {reidResult.matches.length} | candidates: {reidResult.candidate_visitors} | logs: {reidResult.evaluated_logs}
              </p>
              {(reidResult.matches || []).slice(0, 3).map((match) => (
                <div key={match.visitor_id} className="rounded-lg border border-white/10 bg-black/20 p-2">
                  <p className="text-sm text-gray-100">{match.visitor_name || match.visitor_id}</p>
                  <p className="text-xs text-gray-400">score {match.reid_score.toFixed(3)} | sightings {match.sightings} | transitions {match.transition_count}</p>
                </div>
              ))}
            </div>
          )}

          {movementSummary && movementSummary.items.length > 0 && (
            <div className="rounded-xl border border-white/10 bg-black/20 p-4 grid gap-2">
              <p className="text-xs text-gray-400">
                Persisted movement summaries: {movementSummary.total}
              </p>
              {movementSummary.items.slice(0, 3).map((item) => (
                <div key={item.id} className="rounded-lg border border-white/10 bg-white/5 p-2">
                  <p className="text-sm text-gray-100">
                    {item.visitor_name || item.visitor_id}
                  </p>
                  <p className="text-xs text-gray-400">
                    {item.from_camera_name || item.from_camera_id} {'->'} {item.to_camera_name || item.to_camera_id}
                  </p>
                  <p className="text-xs text-gray-500">
                    transitions {item.transition_count} | score {item.reid_score.toFixed(3)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-fuchsia-500/5">
          <CardTitle className="flex items-center gap-3 text-fuchsia-400">
            <Brain size={20} />
            Pose And Action Inference
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-3">
          <select
            value={visionCameraId}
            onChange={(e) => setVisionCameraId(e.target.value)}
            className="h-11 rounded-xl border border-white/10 bg-white/5 px-3 text-sm text-gray-100"
          >
            {streamHealth.map((camera) => (
              <option key={camera.camera_id} value={camera.camera_id}>
                {camera.camera_name}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <Button className="flex-1" onClick={() => onRunPoseEstimate(visionCameraId)} disabled={runningPoseEstimate || !visionCameraId}>
              {runningPoseEstimate ? 'Estimating...' : 'Run Pose Estimate'}
            </Button>
            <Button className="flex-1" onClick={() => onRunActionInference(visionCameraId)} disabled={runningActionInference || !visionCameraId}>
              {runningActionInference ? 'Inferring...' : 'Run Action Inference'}
            </Button>
          </div>
          <Button onClick={() => onAnalyzeBehavior(visionCameraId)} disabled={analyzingBehavior || !visionCameraId}>
            {analyzingBehavior ? 'Analyzing Behavior...' : 'Analyze Behavior And Persist Event'}
          </Button>
          {onRefreshVisionHistory && (
            <Button onClick={onRefreshVisionHistory}>
              Refresh Vision History
            </Button>
          )}

          {poseResult && (
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <p className="text-sm text-gray-100">Pose: {poseResult.posture}</p>
              <p className="text-xs text-gray-400">keypoints {poseResult.keypoint_count} | visibility {poseResult.average_visibility}</p>
              {poseResult.snapshot_thumbnail && (
                <img
                  src={poseResult.snapshot_thumbnail}
                  alt="Pose analyzed frame"
                  className="mt-3 h-36 w-full object-cover rounded-lg border border-white/10"
                />
              )}
            </div>
          )}
          {actionResult && (
            <div className="rounded-xl border border-white/10 bg-white/5 p-3">
              <p className="text-sm text-gray-100">Action: {actionResult.action} / {actionResult.gesture}</p>
              <p className="text-xs text-gray-400">confidence {actionResult.confidence} | posture {actionResult.posture}</p>
              {actionResult.snapshot_thumbnail && (
                <img
                  src={actionResult.snapshot_thumbnail}
                  alt="Action analyzed frame"
                  className="mt-3 h-36 w-full object-cover rounded-lg border border-white/10"
                />
              )}
            </div>
          )}
          {behaviorAnalysis && (
            <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-4 grid gap-2">
              <p className="text-xs text-rose-300 uppercase tracking-widest">
                Latest Behavior Event
              </p>
              <p className="text-sm text-gray-100">
                {behaviorAnalysis.event.anomaly_label} | severity {behaviorAnalysis.event.severity}
              </p>
              <p className="text-xs text-gray-400">
                score {behaviorAnalysis.event.anomaly_score.toFixed(2)} | signal {behaviorAnalysis.signal_created ? 'created' : 'not needed'}
              </p>
              {behaviorAnalysis.anomaly_reasons.length > 0 && (
                <p className="text-xs text-gray-500">
                  reasons: {behaviorAnalysis.anomaly_reasons.join(', ')}
                </p>
              )}
            </div>
          )}
          {visionHistory && (
            <div className="rounded-xl border border-white/10 bg-black/20 p-3 grid gap-2">
              <p className="text-xs text-gray-500">
                Vision history: {visionHistory.total} persisted pose/action event(s) in the last {visionHistory.lookback_hours} hour(s).
              </p>
              {(visionHistory.items || []).slice(0, 3).map((item) => (
                <div key={item.id} className="rounded-lg border border-white/10 bg-white/5 p-2 grid gap-1">
                  <p className="text-xs text-gray-200">{item.event_type} | {item.camera_name || item.camera_id || 'no camera'}</p>
                  <p className="text-[11px] text-gray-500">{item.summary || 'No summary available'}</p>
                  {item.snapshot_url && (
                    <img
                      src={item.snapshot_url}
                      alt="Persisted vision snapshot"
                      className="mt-1 h-24 w-full object-cover rounded-md border border-white/10"
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-rose-500/5">
          <CardTitle className="flex items-center gap-3 text-rose-400">
            <Brain size={20} />
            Continuous Learning Queue
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-3">
          <div className="rounded-xl border border-white/10 bg-white/5 p-4">
            <p className="text-sm text-gray-100">Open signals: {learningSignals?.open_count ?? 0}</p>
            <p className="text-sm text-gray-100">Queued signals: {learningSignals?.queued_count ?? 0}</p>
            <p className="text-xs text-gray-500 mt-2">
              Behavior anomalies and low-confidence detections are promoted into active-learning jobs from here.
            </p>
          </div>
          <Button onClick={onQueueLearningSignals} disabled={queueingSignals || !learningSignals?.open_count}>
            {queueingSignals ? 'Queueing Signals...' : 'Queue Open Signals'}
          </Button>
          {learningSignals?.items?.slice(0, 3).map((signal) => (
            <div key={signal.id} className="rounded-lg border border-white/10 bg-black/20 p-3">
              <p className="text-sm text-gray-100">{signal.signal_type} | {signal.priority}</p>
              <p className="text-xs text-gray-400">
                {signal.visitor_name || signal.visitor_id || 'unassigned'} | status {signal.status}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => onPromoteLearningSignal(signal.id, {
                    visitor_id: signal.visitor_id || undefined,
                    is_positive: true,
                    source: 'behavior_signal',
                  })}
                  disabled={signal.status === 'resolved'}
                >
                  Promote
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => onUpdateLearningSignal(signal.id, {
                    status: 'resolved',
                    resolution: 'dismissed',
                  })}
                  disabled={signal.status === 'resolved'}
                >
                  Resolve
                </Button>
              </div>
            </div>
          ))}
          {behaviorEvents && (
            <p className="text-xs text-gray-500">
              Behavior feed: {behaviorEvents.total} events, {behaviorEvents.anomaly_count} anomalies, {behaviorEvents.critical_count} critical.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b border-white/5 bg-violet-500/5">
          <CardTitle className="flex items-center gap-3 text-violet-400">
            <Sparkles size={20} />
            Natural-Language Analytics
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 grid gap-3">
          <Input value={analyticsQuery} onChange={(e) => setAnalyticsQuery(e.target.value)} placeholder="Ask about anomalies, unidentified traffic, camera health..." />
          <Button onClick={() => onRunAnalyticsQuery(analyticsQuery)} disabled={queryingAnalytics || !analyticsQuery.trim()}>
            {queryingAnalytics ? 'Querying...' : 'Run Query'}
          </Button>
          {analyticsAnswer && (
            <div className="rounded-xl border border-white/10 bg-white/5 p-4">
              <p className="text-[10px] uppercase tracking-widest text-gray-500 mb-2">Intent: {analyticsAnswer.interpreted_intent}</p>
              <p className="text-sm text-gray-200">{analyticsAnswer.summary}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
};

export default FoundationOpsTab;

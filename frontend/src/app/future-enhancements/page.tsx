'use client'

import React, { Suspense, useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
    Rocket, Map, Shield, Zap, Eye, Leaf, Monitor, Activity, Brain, BarChart3, Target, TrendingUp, Gauge, FlaskConical, Layers3, Cpu, Box
} from 'lucide-react'
import Navbar from '@/components/Navbar'
import {
    futureEnhancementService,
    healthService,
    syntheticDataService,
    temporalAugmentationService,
    FutureEnhancement,
    RoadmapResponse,
    BiasAuditResult,
    ExplainabilityResult,
    RateLimitRule,
    CarbonMetricsSummary,
    AugmentationConfigResponse,
    ModelArchitectureResponse,
    TrainingStrategyResponse,
    RobustnessConfigResponse,
    AccuracyBoostResponse,
    PerformanceConfigResponse,
    PriorityMatrixResponse,
    MetricsTargetsResponse,
    CurrentCapabilitiesResponse,
    NextGenBlueprintResponse,
    RuntimeModelRegistryResponse,
    BenchmarkSummaryResponse,
    StreamHealthItem,
    NLAnalyticsQueryResponse,
    CrossCameraReidResponse,
    CrossCameraMovementListResponse,
    PoseEstimateResponse,
    ActionInferResponse,
    MLflowRegistryResponse,
    ModelPromotionRequest,
    BehaviorEventListResponse,
    ContinuousLearningSignalListResponse,
    BehaviorAnalysisResponse,
    VisionAnalyticsHistoryResponse,
    SyntheticGenerationJob,
    SyntheticQualityMetrics,
    TemporalAugmentationJob,
    TemporalExpressionMetrics,
    MLflowPromotionHealthSummary,
    HealthReadinessResponse,
} from '@/services/api'

// Import standardized tabs from the central index
import {
    RoadmapTab,
    EnhancementsTab,
    ArchitectureBlueprintTab,
    FoundationOpsTab,
    CapabilitiesTab,
    AugmentationConfigTab,
    ModelArchConfigTab,
    TrainingConfigTab,
    RobustnessConfigTab,
    AccuracyConfigTab,
    PerformanceConfigTab,
    BiasAuditTab,
    ExplainabilityTab,
    PriorityMatrixTab,
    MetricsTab,
    RateLimitsTab,
    SustainabilityTab,
    ThreeDFaceTab,
    LivenessConfigTab
} from '@/app/enhancements/tabs'

const TABS = [
    { id: 'roadmap', label: 'Roadmap', icon: Map },
    { id: 'enhancements', label: 'Enhancements', icon: Rocket },
    { id: 'blueprint', label: 'Blueprint', icon: Cpu },
    { id: 'foundationops', label: 'Foundation Ops', icon: Activity },
    { id: 'capabilities', label: 'Capabilities', icon: Monitor },
    { id: 'augmentation', label: 'Augmentation', icon: Zap },
    { id: 'modelarch', label: 'Model Arch', icon: FlaskConical },
    { id: 'training', label: 'Training', icon: Brain },
    { id: 'robustness', label: 'Robustness', icon: Shield },
    { id: 'accuracy', label: 'Accuracy', icon: Target },
    { id: 'performance', label: 'Performance', icon: Gauge },
    { id: 'threeface', label: '3D Face', icon: Box },
    { id: 'bias', label: 'Bias & Fairness', icon: Eye },
    { id: 'explainability', label: 'Explainability', icon: Brain },
    { id: 'prioritymatrix', label: 'Priority Matrix', icon: BarChart3 },
    { id: 'metrics', label: 'Metrics', icon: TrendingUp },
    { id: 'ratelimits', label: 'Rate Limits', icon: Gauge },
    { id: 'carbon', label: 'Sustainability', icon: Leaf },
    { id: 'liveness', label: 'Liveness', icon: Shield },
] as const

type TabId = typeof TABS[number]['id']

export default function FutureEnhancementsPage() {
    const [activeTab, setActiveTab] = useState<TabId>('roadmap')
    const [enhancements, setEnhancements] = useState<FutureEnhancement[]>([])
    const [roadmap, setRoadmap] = useState<RoadmapResponse | null>(null)
    const [biasAudit, setBiasAudit] = useState<BiasAuditResult | null>(null)
    const [explainability, setExplainability] = useState<ExplainabilityResult | null>(null)
    const [rateLimits, setRateLimits] = useState<RateLimitRule[]>([])
    const [carbonSummary, setCarbonSummary] = useState<CarbonMetricsSummary | null>(null)
    const [augConfig, setAugConfig] = useState<AugmentationConfigResponse | null>(null)
    const [modelArchConfig, setModelArchConfig] = useState<ModelArchitectureResponse | null>(null)
    const [trainingConfig, setTrainingConfig] = useState<TrainingStrategyResponse | null>(null)
    const [robustnessConfig, setRobustnessConfig] = useState<RobustnessConfigResponse | null>(null)
    const [accuracyConfig, setAccuracyConfig] = useState<AccuracyBoostResponse | null>(null)
    const [performanceConfig, setPerformanceConfig] = useState<PerformanceConfigResponse | null>(null)
    const [priorityMatrix, setPriorityMatrix] = useState<PriorityMatrixResponse | null>(null)
    const [metricsTargets, setMetricsTargets] = useState<MetricsTargetsResponse | null>(null)
    const [capabilities, setCapabilities] = useState<CurrentCapabilitiesResponse | null>(null)
    const [blueprint, setBlueprint] = useState<NextGenBlueprintResponse | null>(null)
    const [runtimeRegistry, setRuntimeRegistry] = useState<RuntimeModelRegistryResponse | null>(null)
    const [benchmarkSummary, setBenchmarkSummary] = useState<BenchmarkSummaryResponse | null>(null)
    const [mlflowRegistry, setMlflowRegistry] = useState<MLflowRegistryResponse | null>(null)
    const [mlflowHealthSummary, setMlflowHealthSummary] = useState<MLflowPromotionHealthSummary | null>(null)
    const [readiness, setReadiness] = useState<HealthReadinessResponse | null>(null)
    const [streamHealth, setStreamHealth] = useState<StreamHealthItem[]>([])
    const [syntheticJob, setSyntheticJob] = useState<SyntheticGenerationJob | null>(null)
    const [temporalJob, setTemporalJob] = useState<TemporalAugmentationJob | null>(null)
    const [syntheticMetrics, setSyntheticMetrics] = useState<SyntheticQualityMetrics[]>([])
    const [temporalMetrics, setTemporalMetrics] = useState<TemporalExpressionMetrics[]>([])
    const [reidResult, setReidResult] = useState<CrossCameraReidResponse | null>(null)
    const [movementSummary, setMovementSummary] = useState<CrossCameraMovementListResponse | null>(null)
    const [poseResult, setPoseResult] = useState<PoseEstimateResponse | null>(null)
    const [actionResult, setActionResult] = useState<ActionInferResponse | null>(null)
    const [behaviorAnalysis, setBehaviorAnalysis] = useState<BehaviorAnalysisResponse | null>(null)
    const [behaviorEvents, setBehaviorEvents] = useState<BehaviorEventListResponse | null>(null)
    const [learningSignals, setLearningSignals] = useState<ContinuousLearningSignalListResponse | null>(null)
    const [visionHistory, setVisionHistory] = useState<VisionAnalyticsHistoryResponse | null>(null)
    const [analyticsAnswer, setAnalyticsAnswer] = useState<NLAnalyticsQueryResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [togglingId, setTogglingId] = useState<string | null>(null)
    const [savingAccConfig, setSavingAccConfig] = useState(false)
    const [savingModelArch, setSavingModelArch] = useState(false)
    const [savingBiasAudit, setSavingBiasAudit] = useState(false)
    const [savingAugConfig, setSavingAugConfig] = useState(false)
    const [augDraft, setAugDraft] = useState<AugmentationConfigResponse | null>(null)
    const [savingRateLimits, setSavingRateLimits] = useState(false)
    const [runningBenchmark, setRunningBenchmark] = useState(false)
    const [queryingReid, setQueryingReid] = useState(false)
    const [queryingAnalytics, setQueryingAnalytics] = useState(false)
    const [runningPoseEstimate, setRunningPoseEstimate] = useState(false)
    const [runningActionInference, setRunningActionInference] = useState(false)
    const [analyzingBehavior, setAnalyzingBehavior] = useState(false)
    const [refreshingStreamHealth, setRefreshingStreamHealth] = useState(false)
    const [syncingMovements, setSyncingMovements] = useState(false)
    const [queueingSignals, setQueueingSignals] = useState(false)
    const [promotingModel, setPromotingModel] = useState(false)
    const [startingSyntheticJob, setStartingSyntheticJob] = useState(false)
    const [startingTemporalJob, setStartingTemporalJob] = useState(false)
    const [refreshingAugmentationMetrics, setRefreshingAugmentationMetrics] = useState(false)

    const phaseCards = capabilities?.phase_summary ?? []

    useEffect(() => {

        fetchData()
    }, [])

    useEffect(() => {
        if (augConfig) {
            setAugDraft(augConfig)
        }
    }, [augConfig])

    useEffect(() => {
        const syntheticActive = syntheticJob && !['completed', 'cancelled', 'failed'].includes(syntheticJob.status)
        const temporalActive = temporalJob && !['completed', 'cancelled', 'failed'].includes(temporalJob.status)
        if (!syntheticActive && !temporalActive) {
            return
        }

        const intervalId = window.setInterval(async () => {
            try {
                if (syntheticActive && syntheticJob) {
                    const res = await syntheticDataService.getJob(syntheticJob.id)
                    setSyntheticJob(res.data)
                }
                if (temporalActive && temporalJob) {
                    const res = await temporalAugmentationService.getJob(temporalJob.id)
                    setTemporalJob(res.data)
                }
                await refreshAugmentationMetrics()
            } catch (err) {
                console.error('Failed to poll augmentation jobs:', err)
            }
        }, 4000)

        return () => window.clearInterval(intervalId)
    }, [syntheticJob, temporalJob])

    const fetchData = async () => {
        try {
            const [
                enhRes, roadmapRes, biasRes, xaiRes, rlRes, carbonRes,
                augRes, modelRes, trainRes, robRes, accRes, perfRes, prioRes, metRes, capRes, blueprintRes,
                runtimeRegistryRes, benchmarkSummaryRes, mlflowRegistryRes, mlflowHealthRes, streamHealthRes,
                readinessRes,
                movementSummaryRes, behaviorEventsRes, learningSignalsRes, visionHistoryRes, syntheticMetricsRes,
                temporalMetricsRes,
            ] = await Promise.allSettled([
                futureEnhancementService.list(),
                futureEnhancementService.getRoadmap(),
                futureEnhancementService.runBiasAudit(),
                futureEnhancementService.getExplainability(),
                futureEnhancementService.listRateLimits(),
                futureEnhancementService.getCarbonSummary(),
                futureEnhancementService.getAugmentationConfig(),
                futureEnhancementService.getModelArchConfig(),
                futureEnhancementService.getTrainingStrategyConfig(),
                futureEnhancementService.getRobustnessConfig(),
                futureEnhancementService.getAccuracyBoostConfig(),
                futureEnhancementService.getPerformanceConfig(),
                futureEnhancementService.getPriorityMatrix(),
                futureEnhancementService.getMetricsTargets(),
                futureEnhancementService.getCurrentCapabilities(),
                futureEnhancementService.getNextGenBlueprint(),
                futureEnhancementService.getRuntimeModelRegistry(),
                futureEnhancementService.getBaselineBenchmarkSummary(),
                futureEnhancementService.getMlflowRegistry(),
                futureEnhancementService.getMlflowHealthSummary(),
                futureEnhancementService.getStreamHealth(),
                healthService.readiness(),
                futureEnhancementService.listCrossCameraMovements({ limit: 10 }),
                futureEnhancementService.listBehaviorEvents({ limit: 10 }),
                futureEnhancementService.listContinuousLearningSignals({ limit: 10 }),
                futureEnhancementService.getVisionHistory({ limit: 20, lookback_hours: 72 }),
                syntheticDataService.listMetrics(),
                temporalAugmentationService.listMetrics(),
            ])
            
            if (enhRes.status === 'fulfilled') setEnhancements(enhRes.value.data)
            if (roadmapRes.status === 'fulfilled') setRoadmap(roadmapRes.value.data)
            if (biasRes.status === 'fulfilled') setBiasAudit(biasRes.value.data)
            if (xaiRes.status === 'fulfilled') setExplainability(xaiRes.value.data)
            if (rlRes.status === 'fulfilled') setRateLimits(rlRes.value.data)
            if (carbonRes.status === 'fulfilled') setCarbonSummary(carbonRes.value.data)
            if (augRes.status === 'fulfilled') setAugConfig(augRes.value.data)
            if (modelRes.status === 'fulfilled') setModelArchConfig(modelRes.value.data)
            if (trainRes.status === 'fulfilled') setTrainingConfig(trainRes.value.data)
            if (robRes.status === 'fulfilled') setRobustnessConfig(robRes.value.data)
            if (accRes.status === 'fulfilled') setAccuracyConfig(accRes.value.data)
            if (perfRes.status === 'fulfilled') setPerformanceConfig(perfRes.value.data)
            if (prioRes.status === 'fulfilled') setPriorityMatrix(prioRes.value.data)
            if (metRes.status === 'fulfilled') setMetricsTargets(metRes.value.data)
            if (capRes.status === 'fulfilled') setCapabilities(capRes.value.data)
            if (blueprintRes.status === 'fulfilled') setBlueprint(blueprintRes.value.data)
            if (runtimeRegistryRes.status === 'fulfilled') setRuntimeRegistry(runtimeRegistryRes.value.data)
            if (benchmarkSummaryRes.status === 'fulfilled') setBenchmarkSummary(benchmarkSummaryRes.value.data)
            if (mlflowRegistryRes.status === 'fulfilled') setMlflowRegistry(mlflowRegistryRes.value.data)
            if (mlflowHealthRes.status === 'fulfilled') setMlflowHealthSummary(mlflowHealthRes.value.data)
            if (readinessRes.status === 'fulfilled') setReadiness(readinessRes.value.data)
            if (streamHealthRes.status === 'fulfilled') setStreamHealth(streamHealthRes.value.data)
            if (movementSummaryRes.status === 'fulfilled') setMovementSummary(movementSummaryRes.value.data)
            if (behaviorEventsRes.status === 'fulfilled') setBehaviorEvents(behaviorEventsRes.value.data)
            if (learningSignalsRes.status === 'fulfilled') setLearningSignals(learningSignalsRes.value.data)
            if (visionHistoryRes.status === 'fulfilled') setVisionHistory(visionHistoryRes.value.data)
            if (syntheticMetricsRes.status === 'fulfilled') setSyntheticMetrics(syntheticMetricsRes.value.data)
            if (temporalMetricsRes.status === 'fulfilled') setTemporalMetrics(temporalMetricsRes.value.data)
        } catch (err: any) {
            console.error('Failed to fetch future enhancement data:', err)
        } finally {
            setLoading(false)
        }
    }

    const refreshAugmentationMetrics = async () => {
        setRefreshingAugmentationMetrics(true)
        try {
            const [syntheticRes, temporalRes] = await Promise.all([
                syntheticDataService.listMetrics(syntheticJob ? { job_id: syntheticJob.id } : undefined).catch(() => ({ data: [] })),
                temporalAugmentationService.listMetrics(temporalJob ? { job_id: temporalJob.id } : undefined).catch(() => ({ data: [] })),
            ])
            setSyntheticMetrics(syntheticRes.data)
            setTemporalMetrics(temporalRes.data)
        } catch (err) {
            console.error('Failed to refresh augmentation metrics:', err)
        } finally {
            setRefreshingAugmentationMetrics(false)
        }
    }

    const refreshVisionHistory = async () => {
        try {
            const res = await futureEnhancementService.getVisionHistory({ limit: 20, lookback_hours: 72 })
            setVisionHistory(res.data)
        } catch (err) {
            console.error('Failed to refresh vision history:', err)
        }
    }

    const handleToggle = async (storyId: string) => {
        setTogglingId(storyId)
        try {
            const res = await futureEnhancementService.toggle(storyId)
            setEnhancements(prev => prev.map(e => e.story_id === storyId ? res.data : e))
        } catch (err) {
            console.error('Toggle failed:', err)
        } finally {
            setTogglingId(null)
        }
    }

    const handleSaveAugmentationConfig = async (data: AugmentationConfigResponse) => {
        setSavingAugConfig(true)
        try {
            const res = await futureEnhancementService.updateAugmentationConfig({
                techniques: data.techniques,
                quality_checks_enabled: data.quality_checks_enabled,
                auto_balance_demographics: data.auto_balance_demographics,
            })
            setAugConfig(res.data)
            setAugDraft(res.data)
        } catch (err) {
            console.error('Failed to save augmentation config:', err)
        } finally {
            setSavingAugConfig(false)
        }
    }

    const handleCreateRateLimit = async (data: { endpoint_pattern: string; max_requests: number; window_seconds: number; is_active: boolean }) => {
        setSavingRateLimits(true)
        try {
            const res = await futureEnhancementService.createRateLimit(data)
            setRateLimits(prev => [res.data, ...prev])
        } catch (err) {
            console.error('Failed to create rate limit:', err)
        } finally {
            setSavingRateLimits(false)
        }
    }

    const handleUpdateRateLimit = async (ruleId: string, data: { endpoint_pattern: string; max_requests: number; window_seconds: number; is_active: boolean }) => {
        setSavingRateLimits(true)
        try {
            const res = await futureEnhancementService.updateRateLimit(ruleId, data)
            setRateLimits(prev => prev.map(rule => (rule.id === ruleId ? res.data : rule)))
        } catch (err) {
            console.error('Failed to update rate limit:', err)
        } finally {
            setSavingRateLimits(false)
        }
    }

    const handleDeleteRateLimit = async (ruleId: string) => {
        setSavingRateLimits(true)
        try {
            await futureEnhancementService.deleteRateLimit(ruleId)
            setRateLimits(prev => prev.filter(rule => rule.id !== ruleId))
        } catch (err) {
            console.error('Failed to delete rate limit:', err)
        } finally {
            setSavingRateLimits(false)
        }
    }

    const handleSaveAccuracyConfig = async (data: AccuracyBoostResponse) => {
        setSavingAccConfig(true)
        try {
            const multiAngle = data.multi_angle || {}
            const consensus = data.consensus_voting || {}
            const temporal = data.temporal_enhancement || {}

            const res = await futureEnhancementService.updateAccuracyBoostConfig({
                multi_angle_enabled: Boolean(multiAngle.multi_angle_enabled ?? multiAngle.enabled),
                supported_angles: multiAngle.supported_angles || [],
                consensus_voting_enabled: Boolean(consensus.consensus_voting_enabled ?? consensus.enabled),
                consensus_threshold: Number(consensus.consensus_threshold ?? consensus.threshold ?? 0.7),
                top_k_scores: Number(consensus.top_k_scores ?? 3),
                temporal_enhancement_enabled: Boolean(temporal.temporal_enabled ?? temporal.enabled),
                recency_weight: Number(temporal.recency_weight ?? 0.6),
            })
            setAccuracyConfig(res.data)
        } catch (err) {
            console.error('Failed to save accuracy config:', err)
        } finally {
            setSavingAccConfig(false)
        }
    }

    const handleSaveModelArch = async (data: ModelArchitectureResponse) => {
        setSavingModelArch(true)
        try {
            const vitConfig = data.vit_config as Record<string, any>
            const hybridConfig = data.hybrid_config as Record<string, any>
            const ensembleConfig = data.ensemble_config as Record<string, any>

            const res = await futureEnhancementService.updateModelArchConfig({
                vit_enabled: Boolean(vitConfig.enabled),
                vit_variant: vitConfig.variant || null,
                hybrid_cnn_transformer: Boolean(hybridConfig.enabled),
                cnn_backbone: hybridConfig.cnn_backbone || 'resnet100',
                ensemble_enabled: Boolean(ensembleConfig.enabled),
                ensemble_methods: ensembleConfig.methods || [],
            })
            setModelArchConfig(res.data)
            const registryRes = await futureEnhancementService.getRuntimeModelRegistry()
            setRuntimeRegistry(registryRes.data)
        } catch (err) {
            console.error('Failed to save model architecture config:', err)
        } finally {
            setSavingModelArch(false)
        }
    }

    const handleRefreshBiasAudit = async () => {
        setSavingBiasAudit(true)
        try {
            const res = await futureEnhancementService.runBiasAudit()
            setBiasAudit(res.data)
        } catch (err) {
            console.error('Failed to run bias audit:', err)
        } finally {
            setSavingBiasAudit(false)
        }
    }

    const handleRunBenchmark = async () => {
        setRunningBenchmark(true)
        try {
            const res = await futureEnhancementService.runBaselineBenchmark(30)
            setBenchmarkSummary(res.data)
        } catch (err) {
            console.error('Failed to run baseline benchmark:', err)
        } finally {
            setRunningBenchmark(false)
        }
    }

    const handlePromoteModel = async (data: ModelPromotionRequest) => {
        setPromotingModel(true)
        try {
            const res = await futureEnhancementService.promoteMlflowModel(data)
            setRuntimeRegistry(res.data.runtime_registry)
            setBenchmarkSummary(res.data.benchmark_summary)

            const registryRes = await futureEnhancementService.getMlflowRegistry()
            setMlflowRegistry(registryRes.data)
            const healthRes = await futureEnhancementService.getMlflowHealthSummary()
            setMlflowHealthSummary(healthRes.data)
        } catch (err) {
            console.error('Failed to promote model candidate:', err)
        } finally {
            setPromotingModel(false)
        }
    }

    const handleSearchCrossCameraReid = async (data: {
        camera_id?: string;
        lookback_minutes?: number;
        limit?: number;
        min_camera_count?: number;
        min_sightings?: number;
        min_avg_confidence?: number;
        min_reid_score?: number;
    }) => {
        setQueryingReid(true)
        try {
            const res = await futureEnhancementService.searchCrossCameraReid(data)
            setReidResult(res.data)
        } catch (err) {
            console.error('Failed to search cross-camera ReID:', err)
        } finally {
            setQueryingReid(false)
        }
    }

    const handleSyncCrossCameraMovements = async (data: {
        camera_id?: string;
        lookback_minutes?: number;
        limit?: number;
        min_camera_count?: number;
        min_sightings?: number;
        min_avg_confidence?: number;
        min_reid_score?: number;
    }) => {
        setSyncingMovements(true)
        try {
            await futureEnhancementService.syncCrossCameraMovements({ ...data, overwrite_existing: true })
            const summaryRes = await futureEnhancementService.listCrossCameraMovements({ limit: 10 })
            setMovementSummary(summaryRes.data)
        } catch (err) {
            console.error('Failed to sync cross-camera movement summaries:', err)
        } finally {
            setSyncingMovements(false)
        }
    }

    const handleRunAnalyticsQuery = async (query: string) => {
        setQueryingAnalytics(true)
        try {
            const res = await futureEnhancementService.queryAnalytics(query, 24)
            setAnalyticsAnswer(res.data)
        } catch (err) {
            console.error('Failed to run analytics query:', err)
        } finally {
            setQueryingAnalytics(false)
        }
    }

    const handleRunPoseEstimate = async (cameraId: string) => {
        setRunningPoseEstimate(true)
        try {
            const res = await futureEnhancementService.runPoseEstimate({ camera_id: cameraId })
            setPoseResult(res.data)
            await refreshVisionHistory()
        } catch (err) {
            console.error('Failed to run pose estimate:', err)
        } finally {
            setRunningPoseEstimate(false)
        }
    }

    const handleRunActionInference = async (cameraId: string) => {
        setRunningActionInference(true)
        try {
            const res = await futureEnhancementService.runActionInference({ camera_id: cameraId })
            setActionResult(res.data)
            await refreshVisionHistory()
        } catch (err) {
            console.error('Failed to run action inference:', err)
        } finally {
            setRunningActionInference(false)
        }
    }

    const handleAnalyzeBehavior = async (cameraId: string) => {
        setAnalyzingBehavior(true)
        try {
            const res = await futureEnhancementService.analyzeBehavior({ camera_id: cameraId })
            setBehaviorAnalysis(res.data)
            setPoseResult(res.data.pose_estimate)
            setActionResult(res.data.action_inference)

            const [eventsRes, signalsRes] = await Promise.all([
                futureEnhancementService.listBehaviorEvents({ limit: 10 }).catch(() => ({ data: [] })),
                futureEnhancementService.listContinuousLearningSignals({ limit: 10 }).catch(() => ({ data: [] })),
            ])
            setBehaviorEvents(eventsRes.data as BehaviorEventListResponse)
            setLearningSignals(signalsRes.data as ContinuousLearningSignalListResponse)
            await refreshVisionHistory()
        } catch (err) {
            console.error('Failed to analyze behavior snapshot:', err)
        } finally {
            setAnalyzingBehavior(false)
        }
    }

    const handleQueueLearningSignals = async () => {
        setQueueingSignals(true)
        try {
            await futureEnhancementService.queueContinuousLearningSignals({
                max_samples: 10,
                min_priority: 'medium',
                strategy: 'anomaly_first',
            })
            const signalsRes = await futureEnhancementService.listContinuousLearningSignals({ limit: 10 })
            setLearningSignals(signalsRes.data)
        } catch (err) {
            console.error('Failed to queue continuous-learning signals:', err)
        } finally {
            setQueueingSignals(false)
        }
    }

    const handleUpdateLearningSignal = async (signalId: string, data: { status: string; resolution?: string; notes?: string }) => {
        try {
            await futureEnhancementService.updateLearningSignal(signalId, data)
            const signalsRes = await futureEnhancementService.listContinuousLearningSignals({ limit: 10 })
            setLearningSignals(signalsRes.data)
        } catch (err) {
            console.error('Failed to update learning signal:', err)
        }
    }

    const handlePromoteLearningSignal = async (signalId: string, data?: { visitor_id?: string; is_positive?: boolean; source?: string }) => {
        try {
            await futureEnhancementService.promoteLearningSignal(signalId, data || {})
            const signalsRes = await futureEnhancementService.listContinuousLearningSignals({ limit: 10 })
            setLearningSignals(signalsRes.data)
        } catch (err) {
            console.error('Failed to promote learning signal:', err)
        }
    }

    const handleRefreshStreamHealth = async (probeMode = false) => {
        setRefreshingStreamHealth(true)
        try {
            const res = await futureEnhancementService.getStreamHealth(90, probeMode, 4)
            setStreamHealth(res.data)
        } catch (err) {
            console.error('Failed to refresh stream health:', err)
        } finally {
            setRefreshingStreamHealth(false)
        }
    }

    const handleStartSyntheticJob = async (totalSamples: number) => {
        setStartingSyntheticJob(true)
        try {
            const res = await syntheticDataService.startGeneration(totalSamples)
            setSyntheticJob(res.data)
            const metricsRes = await syntheticDataService.listMetrics({ job_id: res.data.id })
            setSyntheticMetrics(metricsRes.data)
        } catch (err) {
            console.error('Failed to start synthetic generation job:', err)
        } finally {
            setStartingSyntheticJob(false)
        }
    }

    const handleCancelSyntheticJob = async (jobId: string) => {
        try {
            const res = await syntheticDataService.cancelJob(jobId)
            setSyntheticJob(res.data)
            await refreshAugmentationMetrics()
        } catch (err) {
            console.error('Failed to cancel synthetic generation job:', err)
        }
    }

    const handleStartTemporalJob = async (inputVideoPath: string) => {
        setStartingTemporalJob(true)
        try {
            const res = await temporalAugmentationService.startJob(inputVideoPath)
            setTemporalJob(res.data)
            const metricsRes = await temporalAugmentationService.listMetrics({ job_id: res.data.id })
            setTemporalMetrics(metricsRes.data)
        } catch (err) {
            console.error('Failed to start temporal augmentation job:', err)
        } finally {
            setStartingTemporalJob(false)
        }
    }

    const handleCancelTemporalJob = async (jobId: string) => {
        try {
            const res = await temporalAugmentationService.cancelJob(jobId)
            setTemporalJob(res.data)
            await refreshAugmentationMetrics()
        } catch (err) {
            console.error('Failed to cancel temporal augmentation job:', err)
        }
    }

    if (loading) {
        return (
            <div className="min-h-screen">
                <Navbar />
                <main className="pt-24 pb-20 px-6 container mx-auto">
                    <div className="animate-pulse space-y-6">
                        <div className="h-8 bg-gray-800 rounded w-64" />
                        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                            {[1, 2, 3, 4].map(i => <div key={i} className="h-32 bg-gray-800 rounded-xl" />)}
                        </div>
                        <div className="h-96 bg-gray-800 rounded-xl" />
                    </div>
                </main>
            </div>
        )
    }

    return (
        <div className="min-h-screen">
            <Navbar />
            <main className="pt-24 pb-20 px-6 container mx-auto">
                <motion.div initial={{ opacity: 0, y: -20 }} animate={{ opacity: 1, y: 0 }} className="mb-8 p-12 rounded-[2rem] bg-gradient-to-br from-brand-600/20 to-transparent border border-white/5 relative overflow-hidden">
                    <div className="absolute top-0 right-0 p-12 opacity-5 pointer-events-none">
                        <Rocket size={240} />
                    </div>
                    <h1 className="text-4xl font-black mb-3 tracking-tighter uppercase">Future Enhancements</h1>
                    <p className="text-gray-400 max-w-2xl text-lg font-medium leading-relaxed">
                        Computer vision research roadmap, neural architecture evolutions, and infrastructure-scale capabilities for the next generation of identification.
                    </p>
                </motion.div>

                <div className="flex flex-wrap items-center gap-3 mb-6">
                    <span className="text-[10px] font-black uppercase tracking-[0.2em] text-gray-500">Legend</span>
                    {[
                        { label: 'Implemented', className: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
                        { label: 'Partial', className: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
                        { label: 'Planned', className: 'bg-gray-500/10 text-gray-400 border-gray-500/20' },
                    ].map(item => (
                        <span key={item.label} className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border ${item.className}`}>
                            {item.label}
                        </span>
                    ))}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
                    {[
                        { label: 'Intelligence Nodes', val: roadmap?.total_enhancements || enhancements.length, icon: Rocket, color: 'text-brand-500' },
                        { label: 'Operational Status', val: roadmap?.enabled_count || enhancements.filter(e => e.enabled).length, icon: Zap, color: 'text-green-400' },
                        { label: 'Network Progress', val: `${roadmap?.completion_percent || 0}%`, icon: Activity, color: 'text-purple-400' },
                        { label: 'Eco-Efficiency', val: `${carbonSummary?.efficiency_score || 100}%`, icon: Leaf, color: 'text-emerald-400' },
                    ].map((stat, i) => (
                        <motion.div 
                          key={i} 
                          initial={{ opacity: 0, scale: 0.9 }} 
                          animate={{ opacity: 1, scale: 1 }} 
                          transition={{ delay: i * 0.1 }} 
                          className="glass-card rounded-[1.5rem] p-6 group hover:border-white/20 transition-all border-white/5"
                        >
                            <div className="flex items-center gap-4 mb-4">
                                <div className={`p-3 rounded-2xl bg-white/5 border border-white/10 group-hover:scale-110 transition-transform ${stat.color}`}>
                                    <stat.icon size={20} />
                                </div>
                                <span className="text-[10px] font-black uppercase tracking-[0.2em] text-gray-500">{stat.label}</span>
                            </div>
                            <p className="text-3xl font-black tabular-nums tracking-tighter">{stat.val}</p>
                        </motion.div>
                    ))}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 mb-8">
                    {phaseCards.map((phase, i) => (
                        <motion.div
                            key={phase.phase}
                            initial={{ opacity: 0, y: 12 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.08 }}
                            className="glass-card rounded-[1.5rem] p-6 border-white/5 group hover:border-white/20 transition-all"
                        >
                            <div className="flex items-center justify-between gap-3 mb-4">
                                <div className="flex items-center gap-3">
                                    <div className="p-3 rounded-2xl bg-white/5 border border-white/10 text-sky-400">
                                        <Layers3 size={18} />
                                    </div>
                                    <div>
                                        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-gray-500">{phase.phase}</p>
                                        <h3 className="text-sm font-bold text-gray-100">{phase.title}</h3>
                                    </div>
                                </div>
                                <span className={`text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded border ${
                                    phase.status === 'implemented'
                                        ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                                        : phase.status === 'partial'
                                            ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                                            : 'bg-gray-500/10 text-gray-400 border-gray-500/20'
                                }`}>
                                    {phase.status}
                                </span>
                            </div>
                            <p className="text-xs text-gray-400 leading-relaxed mb-4">{phase.focus}</p>
                            <div className="flex gap-2 flex-wrap">
                                <span className="text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                    {phase.implemented_count} implemented
                                </span>
                                <span className="text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                                    {phase.planned_count} planned
                                </span>
                                <span className="text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20">
                                    {phase.items.length} total items
                                </span>
                            </div>
                            <div className="mt-4">
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-[10px] font-black uppercase tracking-widest text-gray-500">Phase progress</span>
                                    <span className="text-[10px] font-black uppercase tracking-widest text-gray-400">
                                        {Math.round((phase.implemented_count / Math.max(phase.items.length, 1)) * 100)}%
                                    </span>
                                </div>
                                <div className="h-2 rounded-full bg-white/5 overflow-hidden border border-white/5">
                                    <div
                                        className="h-full rounded-full bg-gradient-to-r from-emerald-400 via-sky-400 to-amber-400"
                                        style={{ width: `${(phase.implemented_count / Math.max(phase.items.length, 1)) * 100}%` }}
                                    />
                                </div>
                            </div>
                        </motion.div>
                    ))}
                </div>

                <div className="flex gap-2 mb-8 overflow-x-auto pb-4 scrollbar-hide">
                    {TABS.map(tab => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`flex items-center gap-3 px-6 py-3 rounded-2xl text-xs font-black uppercase tracking-widest transition-all duration-300 border ${activeTab === tab.id
                                ? 'bg-brand-600/20 text-brand-500 border-brand-500/20 shadow-[0_0_20px_rgba(var(--brand-primary-rgb),0.1)]'
                                : 'text-gray-500 hover:text-white border-transparent hover:bg-white/5'
                                }`}
                        >
                            <tab.icon size={14} />
                            {tab.label}
                        </button>
                    ))}
                </div>

                <motion.div
                  key={activeTab}
                  initial={{ opacity: 0, filter: 'blur(10px)' }}
                  animate={{ opacity: 1, filter: 'blur(0px)' }}
                  transition={{ duration: 0.4 }}
                  className="bg-black/20 p-8 rounded-[2rem] border border-white/5 min-h-[600px]"
                >
                  <Suspense fallback={
                    <div className="flex items-center justify-center min-h-[400px] text-xs uppercase tracking-widest text-gray-500">
                      Loading tab…
                    </div>
                  }>
                    {activeTab === 'roadmap' && <RoadmapTab data={roadmap} />}
                    {activeTab === 'enhancements' && (
                        <EnhancementsTab
                            data={enhancements}
                            togglingId={togglingId}
                            onToggle={handleToggle}
                        />
                    )}
                    {activeTab === 'blueprint' && <ArchitectureBlueprintTab data={blueprint} />}
                    {activeTab === 'foundationops' && (
                        <FoundationOpsTab
                            runtimeRegistry={runtimeRegistry}
                            benchmarkSummary={benchmarkSummary}
                            readiness={readiness}
                            mlflowRegistry={mlflowRegistry}
                            mlflowHealthSummary={mlflowHealthSummary}
                            streamHealth={streamHealth}
                            reidResult={reidResult}
                            movementSummary={movementSummary}
                            poseResult={poseResult}
                            actionResult={actionResult}
                            behaviorAnalysis={behaviorAnalysis}
                            behaviorEvents={behaviorEvents}
                            learningSignals={learningSignals}
                            visionHistory={visionHistory}
                            analyticsAnswer={analyticsAnswer}
                            runningBenchmark={runningBenchmark}
                            queryingReid={queryingReid}
                            queryingAnalytics={queryingAnalytics}
                            runningPoseEstimate={runningPoseEstimate}
                            runningActionInference={runningActionInference}
                            analyzingBehavior={analyzingBehavior}
                            refreshingStreamHealth={refreshingStreamHealth}
                            syncingMovements={syncingMovements}
                            queueingSignals={queueingSignals}
                            promotingModel={promotingModel}
                            onRunBenchmark={handleRunBenchmark}
                            onSearchCrossCameraReid={handleSearchCrossCameraReid}
                            onSyncCrossCameraMovements={handleSyncCrossCameraMovements}
                            onRunAnalyticsQuery={handleRunAnalyticsQuery}
                            onRunPoseEstimate={handleRunPoseEstimate}
                            onRunActionInference={handleRunActionInference}
                            onAnalyzeBehavior={handleAnalyzeBehavior}
                            onQueueLearningSignals={handleQueueLearningSignals}
                            onUpdateLearningSignal={handleUpdateLearningSignal}
                            onPromoteLearningSignal={handlePromoteLearningSignal}
                            onRefreshStreamHealth={handleRefreshStreamHealth}
                            onPromoteModel={handlePromoteModel}
                            onRefreshVisionHistory={refreshVisionHistory}
                        />
                    )}
                    {activeTab === 'capabilities' && (
                        <CapabilitiesTab
                            data={capabilities}
                            runtimeRegistry={runtimeRegistry}
                            benchmarkSummary={benchmarkSummary}
                        />
                    )}
                    {activeTab === 'augmentation' && (
                        <AugmentationConfigTab
                            data={augDraft}
                            syntheticJob={syntheticJob}
                            temporalJob={temporalJob}
                            syntheticMetrics={syntheticMetrics}
                            temporalMetrics={temporalMetrics}
                            startingSyntheticJob={startingSyntheticJob}
                            startingTemporalJob={startingTemporalJob}
                            refreshingMetrics={refreshingAugmentationMetrics}
                            onChange={setAugDraft}
                            onSave={handleSaveAugmentationConfig}
                            onStartSyntheticJob={handleStartSyntheticJob}
                            onCancelSyntheticJob={handleCancelSyntheticJob}
                            onStartTemporalJob={handleStartTemporalJob}
                            onCancelTemporalJob={handleCancelTemporalJob}
                            onRefreshMetrics={refreshAugmentationMetrics}
                            saving={savingAugConfig}
                        />
                    )}
                    {activeTab === 'modelarch' && (
                        <ModelArchConfigTab
                            data={modelArchConfig}
                            onSave={handleSaveModelArch}
                            saving={savingModelArch}
                        />
                    )}
                    {activeTab === 'training' && <TrainingConfigTab data={trainingConfig} />}
                    {activeTab === 'robustness' && <RobustnessConfigTab data={robustnessConfig} />}
                    {activeTab === 'accuracy' && (
                        <AccuracyConfigTab 
                            data={accuracyConfig} 
                            onSave={handleSaveAccuracyConfig}
                            saving={savingAccConfig}
                        />
                    )}
                    {activeTab === 'threeface' && <ThreeDFaceTab />}
                    {activeTab === 'performance' && <PerformanceConfigTab data={performanceConfig} />}
                    {activeTab === 'bias' && (
                        <BiasAuditTab 
                            data={biasAudit} 
                            onRefresh={handleRefreshBiasAudit} 
                        />
                    )}
                    {activeTab === 'explainability' && (
                        <ExplainabilityTab 
                            data={explainability} 
                            onRefresh={async () => {
                                const res = await futureEnhancementService.getExplainability();
                                setExplainability(res.data);
                            }}
                        />
                    )}
                    {activeTab === 'prioritymatrix' && <PriorityMatrixTab data={priorityMatrix} />}
                    {activeTab === 'metrics' && <MetricsTab data={metricsTargets} />}
                    {activeTab === 'ratelimits' && (
                        <RateLimitsTab
                            rules={rateLimits}
                            saving={savingRateLimits}
                            onCreate={handleCreateRateLimit}
                            onUpdate={handleUpdateRateLimit}
                            onDelete={handleDeleteRateLimit}
                        />
                    )}
                    {activeTab === 'carbon' && <SustainabilityTab data={carbonSummary} />}
                    {activeTab === 'liveness' && <LivenessConfigTab />}
                  </Suspense>
                </motion.div>
            </main>
        </div>
    )
}

// Lazy-load every tab so the future-enhancements page only ships the
// JS for the tab the user is currently viewing. Each tab averages a
// few hundred KB once recharts/framer/etc. transitive dependencies
// are factored in; loading 19 of them eagerly bloats the first paint.
//
// Consumers must wrap the rendered tab in <Suspense fallback={...}>.
import { lazy } from 'react';

export const AccuracyConfigTab = lazy(() => import('./AccuracyConfigTab'));
export const ArchitectureBlueprintTab = lazy(() => import('./ArchitectureBlueprintTab'));
export const AugmentationConfigTab = lazy(() => import('./AugmentationConfigTab'));
export const BiasAuditTab = lazy(() => import('./BiasAuditTab'));
export const CapabilitiesTab = lazy(() => import('./CapabilitiesTab'));
export const EnhancementsTab = lazy(() => import('./EnhancementsTab'));
export const ExplainabilityTab = lazy(() => import('./ExplainabilityTab'));
export const FoundationOpsTab = lazy(() => import('./FoundationOpsTab'));
export const MetricsTab = lazy(() => import('./MetricsTab'));
export const ModelArchConfigTab = lazy(() => import('./ModelArchConfigTab'));
export const PerformanceConfigTab = lazy(() => import('./PerformanceConfigTab'));
export const PriorityMatrixTab = lazy(() => import('./PriorityMatrixTab'));
export const RateLimitsTab = lazy(() => import('./RateLimitsTab'));
export const RoadmapTab = lazy(() => import('./RoadmapTab'));
export const RobustnessConfigTab = lazy(() => import('./RobustnessConfigTab'));
export const SustainabilityTab = lazy(() => import('./SustainabilityTab'));
export const TrainingConfigTab = lazy(() => import('./TrainingConfigTab'));
export const ThreeDFaceTab = lazy(() => import('./ThreeDFaceTab'));
export const LivenessConfigTab = lazy(() => import('./LivenessConfigTab'));

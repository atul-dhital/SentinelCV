// Core utilities and realtime
export { API_BASE_URL, api, realtimeService } from './core';
export type {
    AuthTokenResponse,
    AuthServiceResponse,
    AuthRequestError,
} from './core';

// Auth, user, and organization services
export { authService, userService, orgService } from './authService';
export type {
    Organization,
    AuditLog,
    PaginatedResponse,
} from './authService';

// Visitor & activity services (Phase 2)
export {
    visitorService,
    livenessService,
    cameraSessionService,
    logService,
    auditLogService,
    videoService,
    alertService,
    recommendationService,
} from './visitorService';

// Camera & device services (Phase 2)
export {
    cameraService,
    edgeDeviceService,
    healthService,
} from './cameraService';

// Analytics & reporting services (Phase 2)
export {
    analyticsService,
    accuracyService,
    dataQualityService,
    advancedAnalyticsService,
    modelService,
} from './analyticsService';

// Compliance & integration services (Phase 2)
export {
    complianceService,
    gdprService,
    webhookService,
    ssoService,
    ldapService,
    notificationService,
} from './complianceService';

// Advanced & experimental services (Phase 2)
export {
    futureEnhancementService,
    threeDFaceService,
    multimodalService,
    advancedLivenessService,
    federatedService,
    emotionService,
    reidService,
    edgeDeployService,
    vitService,
    multispectralService,
    mobileService,
    integrationsApiService,
    abTestingService,
    securityApiService,
    syntheticDataService,
    temporalAugmentationService,
} from './advancedService';

// Re-export the full legacy contract while the domain modules provide grouped entrypoints.
export * from './api';

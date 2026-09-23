import axios from 'axios';
import type { AxiosRequestConfig } from 'axios';
import {
    clearAccessToken,
    ensureAccessToken,
    getAccessToken,
    hasAccessToken,
    registerAccessTokenRestorer,
    restoreAccessToken,
    setAccessToken,
} from '@/lib/authSession';
import type { UserInfo, UserSession } from '@/types/user';
export type { UserInfo, UserSession } from '@/types/user';

const _rawApiUrl = process.env.NEXT_PUBLIC_API_URL;
if (!_rawApiUrl && process.env.NODE_ENV === 'production') {
    throw new Error('NEXT_PUBLIC_API_URL must be set in production. Refusing to fall back to localhost.');
}
export const API_BASE_URL = _rawApiUrl || 'http://localhost:8000/api/v1';

export const realtimeService = {
    /**
     * Build the dashboard websocket URL.
     *
     * The backend derives organization_id from the access token (the previous
     * behaviour of trusting the org id from the query string was an
     * authorization bypass). Pass the current access token; the server rejects
     * the connection if it is missing or invalid.
     */
    dashboardSocketUrl: (_organizationId?: string) => {
        const apiOrigin = API_BASE_URL.replace('/api/v1', '');
        const wsOrigin = apiOrigin.replace('https://', 'wss://').replace('http://', 'ws://');
        const token = getAccessToken();
        const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
        return `${wsOrigin}/api/v1/ws/dashboard${tokenParam}`;
    },
};

const api = axios.create({
    baseURL: API_BASE_URL,
    withCredentials: true,
});

// The backend stores and emits naive UTC timestamps (no "Z" / offset suffix).
// JavaScript's Date parses those as LOCAL time, shifting every displayed
// time by the user's UTC offset (e.g. +5:45 in Nepal → "6h ago" on fresh
// logs). Normalize every naive ISO datetime string in API responses to
// explicit UTC so all `new Date(...)` call sites render correctly in the
// viewer's local timezone.
const NAIVE_ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/;

function normalizeApiDates(value: unknown): void {
    if (!value || typeof value !== 'object') return;
    if (Array.isArray(value)) {
        for (let i = 0; i < value.length; i++) {
            const item = value[i];
            if (typeof item === 'string' && NAIVE_ISO_DATETIME.test(item)) {
                value[i] = `${item}Z`;
            } else {
                normalizeApiDates(item);
            }
        }
        return;
    }
    const record = value as Record<string, unknown>;
    for (const key of Object.keys(record)) {
        const item = record[key];
        if (typeof item === 'string' && NAIVE_ISO_DATETIME.test(item)) {
            record[key] = `${item}Z`;
        } else {
            normalizeApiDates(item);
        }
    }
}

api.interceptors.response.use((response) => {
    const data = response.data;
    if (data && typeof data === 'object' && !(data instanceof Blob) && !(data instanceof ArrayBuffer)) {
        normalizeApiDates(data);
    }
    return response;
});

type AuthTokenResponse = {
    access_token: string;
    refresh_token?: string;
    token_type: string;
};

type AuthServiceResponse<T> = {
    data: T;
};

type AuthRequestError = Error & {
    status?: number;
    response?: {
        status: number;
        data: unknown;
    };
};

async function parseAuthResponse<T>(response: Response): Promise<T | null> {
    const rawBody = await response.text();
    if (!rawBody) {
        return null;
    }

    return JSON.parse(rawBody) as T;
}

async function postAuthJson<T>(path: string, body?: Record<string, unknown>): Promise<AuthServiceResponse<T>> {
    const response = await fetch(`${API_BASE_URL}${path}`, {
        method: 'POST',
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
        },
        body: body ? JSON.stringify(body) : undefined,
    });

    const data = await parseAuthResponse<T>(response);
    if (!response.ok) {
        const error = new Error(
            typeof data === 'object' && data !== null && 'detail' in data && typeof data.detail === 'string'
                ? data.detail
                : `Request failed with status ${response.status}`,
        ) as AuthRequestError;
        error.status = response.status;
        error.response = {
            status: response.status,
            data,
        };
        throw error;
    }

    return { data: (data ?? {}) as T };
}

function redirectToLogin() {
    if (typeof window === 'undefined') return;
    if (window.location.pathname !== '/login') {
        window.location.href = '/login';
    }
}

async function refreshAccessToken(force = false): Promise<string | null> {
    if (!force && hasAccessToken()) {
        return getAccessToken();
    }

    try {
        const res = await postAuthJson<AuthTokenResponse>('/auth/refresh', {});
        setAccessToken(res.data.access_token);
        return res.data.access_token;
    } catch (err: unknown) {
        const e = err as AuthRequestError;
        // Network errors (no status) are transient — don't clear the session.
        // Auth errors (401/403) mean the refresh token is invalid/expired.
        if (e?.status === 401 || e?.status === 403) {
            clearAccessToken();
            return null;
        }
        // Transient failure (network, 5xx) — preserve existing token if any.
        if (hasAccessToken()) {
            return getAccessToken();
        }
        return null;
    }
}

registerAccessTokenRestorer(() => refreshAccessToken());

api.interceptors.request.use(async (config) => {
    const isAuthRequest = config.url?.includes('/auth/');
    const token = getAccessToken() || (isAuthRequest ? null : await restoreAccessToken());
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    } else if (config.headers?.Authorization) {
        delete config.headers.Authorization;
    }
    if (config.withCredentials === undefined) {
        config.withCredentials = true;
    }
    return config;
});

api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const originalRequest = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined;
        if (
            error.response?.status === 401 &&
            originalRequest &&
            !originalRequest._retry &&
            !originalRequest.url?.includes('/auth/')
        ) {
            originalRequest._retry = true;
            const token = await restoreAccessToken(true);
            if (token) {
                originalRequest.headers = originalRequest.headers ?? {};
                originalRequest.headers.Authorization = `Bearer ${token}`;
                originalRequest.withCredentials = true;
                return api(originalRequest);
            }
            clearAccessToken();
            redirectToLogin();
        }
        return Promise.reject(error);
    }
);

// Types

export interface PaginatedResponse<T> {
    items: T[];
    total: number;
    page: number;
    limit: number;
    pages: number;
    /** ISO timestamp cursor for the next page (cursor-based pagination). */
    next_cursor?: string | null;
}

export interface DashboardStats {
    identified_count: number;
    unidentified_count: number;
    total_events: number;
    total_visitors: number;
    pending_review: number;
    cameras_online: number;
}

export interface EmotionAnalyticsTimelinePoint {
    date: string;
    total_events: number;
    dominant_emotion: string;
    avg_valence: number;
    avg_arousal: number;
}

export interface EmotionAnalyticsSummary {
    lookback_days: number;
    since: string;
    total_events: number;
    dominant_emotion: string;
    avg_valence: number;
    avg_arousal: number;
    emotion_distribution: Record<string, number>;
    emotion_counts: Record<string, number>;
    timeline: EmotionAnalyticsTimelinePoint[];
    generated_at: string;
}

export interface VisitorFlowTotals {
    total_events: number;
    unique_visitors: number;
    identified_events: number;
    identified_rate: number;
}

export interface VisitorFlowHourlyPoint {
    hour: string;
    visitor_events: number;
}

export interface VisitorFlowCameraDensityItem {
    camera_id: string;
    camera_name: string;
    events: number;
    share: number;
}

export interface VisitorFlowPeakCamera {
    camera_id?: string | null;
    camera_name?: string | null;
    events: number;
}

export interface VisitorFlowDwellTime {
    median_seconds: number;
    average_seconds: number;
    sample_count: number;
}

export interface VisitorFlowHeatmap {
    grid_size: number[];
    raw_grid: number[][];
    normalized_grid: number[][];
    peak_cell_events: number;
}

export interface VisitorFlowAnalytics {
    lookback_hours: number;
    since: string;
    totals: VisitorFlowTotals;
    hourly_timeline: VisitorFlowHourlyPoint[];
    camera_density: VisitorFlowCameraDensityItem[];
    peak_camera: VisitorFlowPeakCamera;
    dwell_time: VisitorFlowDwellTime;
    heatmap: VisitorFlowHeatmap;
    generated_at: string;
}

// UserInfo type is defined in @/types/user and re-exported from this module

export interface Visitor {
    id: string;
    name: string | null;
    email: string | null;
    phone: string | null;
    description: string | null;
    notes: string | null;
    metadata: Record<string, any> | null;
    is_known: boolean;
    is_active: boolean;
    organization_id: string;
    created_at: string;
    updated_at: string | null;
    primary_face_image_url?: string | null;
    face_count?: number;
}

export interface VisitorDetail extends Visitor {
    face_data: FaceData[];
    log_count: number;
    custom_threshold?: number | null;
    auto_learn?: boolean;
}

export interface FaceData {
    id: string;
    visitor_id: string;
    image_url: string | null;
    quality_score: number;
    face_angle?: string | null;
    is_primary: boolean;
    created_at: string;
}

export interface VisitorLog {
    id: string;
    organization_id: string;
    visitor_id: string | null;
    camera_id: string | null;
    face_data_id: string | null;
    face_image_path: string | null;
    video_snippet_path: string | null;
    confidence: number;
    status: string;
    identified: boolean;
    timestamp: string;
    track_id: number | null;
    source_video: string | null;
    visitor_name?: string | null;
    visitor_image_url?: string | null;
    visitor_known?: boolean | null;
}

export interface VisitorMediaUploadResult {
    visitor_id: string;
    images_added: number;
    video_frames_added: number;
    video_url: string | null;
    warnings: string[];
    message: string;
}

export interface Camera {
    id: string;
    name: string;
    rtsp_url: string | null;
    location: string | null;
    organization_id: string;
    is_active: boolean;
    status: string;
    last_seen: string | null;
    created_at: string;
}

export interface EdgeDevice {
    id: string;
    organization_id: string;
    name: string;
    device_type: string;
    status: string;
    is_active: boolean;
    location?: string | null;
    endpoint_url?: string | null;
    ip_address?: string | null;
    serial_number?: string | null;
    hardware_info?: Record<string, any> | null;
    tags?: string[] | null;
    model_version_id?: string | null;
    model_artifact_path?: string | null;
    model_config?: Record<string, any> | null;
    token_prefix: string;
    last_seen?: string | null;
    last_metrics?: Record<string, any> | null;
    last_sync_at?: string | null;
    last_sync_count?: number;
    last_sync_status?: string | null;
    last_export_at?: string | null;
    last_export_status?: string | null;
    last_export_path?: string | null;
    last_export_details?: Record<string, any> | null;
    created_at: string;
    updated_at?: string | null;
}

export interface EdgeDeviceTokenResponse {
    device: EdgeDevice;
    device_token: string;
}

export interface EdgeDeviceEvent {
    id: string;
    organization_id: string;
    edge_device_id: string;
    event_type: string;
    severity: string;
    title: string;
    message?: string | null;
    payload: Record<string, any> | null;
    created_at: string;
}

export interface Organization {
    id: string;
    name: string;
    face_confidence_threshold: number;
    log_retention_days: number;
    notification_email: boolean;
    notification_unidentified: boolean;
    /** Optional dedicated address for alert notification emails. */
    notification_email_address?: string | null;
    settings: Record<string, any> | null;
    created_at: string;
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export interface VideoProcessingJob {
    id: string;
    organization_id: string;
    file_id: string;
    file_path: string;
    status: string;
    message: string | null;
    people_detected: number;
    people_identified: number;
    created_at: string;
    updated_at: string | null;
}

export interface BulkImportResult {
    total: number;
    created: number;
    face_enrolled?: number;
    errors: { row: number; error: string }[];
}

export const authService = {
    login: async (email: string, password: string) => {
        const res = await postAuthJson<AuthTokenResponse>('/auth/login', { email, password });
        setAccessToken(res.data.access_token);
        return res;
    },
    register: async (data: { email: string; full_name: string; password: string; organization_name: string }) => {
        const res = await postAuthJson<AuthTokenResponse>('/auth/register', data);
        setAccessToken(res.data.access_token);
        return res;
    },
    refresh: async (refresh_token?: string) => {
        const res = await postAuthJson<AuthTokenResponse>('/auth/refresh', refresh_token ? { refresh_token } : {});
        setAccessToken(res.data.access_token);
        return res;
    },
    logout: async (refresh_token?: string) => {
        try {
            return await postAuthJson<Record<string, never>>('/auth/logout', refresh_token ? { refresh_token } : {});
        } finally {
            clearAccessToken();
        }
    },
    me: async () => {
        await ensureAccessToken()
        return api.get<UserInfo>('/auth/me')
    },
    ensureSession: () => ensureAccessToken(),
    hasAccessToken: () => hasAccessToken(),
    clearSession: () => clearAccessToken(),
    getLoginHistory: (params?: {
        user_id?: string;
        include_failed?: boolean;
        date_from?: string;
        date_to?: string;
        page?: number;
        limit?: number;
    }) => api.get<PaginatedResponse<AuditLog>>('/auth/login-history', { params }),
    forgotPassword: (email: string) =>
        api.post('/auth/forgot-password', { email }),
    resetPassword: (token: string, new_password: string) =>
        api.post('/auth/reset-password', { token, new_password }),
};

// ── Organizations ────────────────────────────────────────────────────────────

export const orgService = {
    getMyOrg: () => api.get<Organization>('/organizations/me'),
    updateMyOrg: (data: {
        name?: string;
        face_confidence_threshold?: number;
        log_retention_days?: number;
        notification_email?: boolean;
        notification_unidentified?: boolean;
        notification_email_address?: string | null;
        settings?: Record<string, any>;
    }) => api.put('/organizations/me', data),
    getStats: () => api.get('/organizations/me/stats'),
};

// ── Users ────────────────────────────────────────────────────────────────────

export const userService = {
    getUsers: (params?: { skip?: number; limit?: number }) =>
        api.get<UserInfo[]>('/users/', { params }),
    getUser: (userId: string) => api.get<UserInfo>(`/users/${userId}`),
    createUser: (data: { email: string; full_name: string; password: string; role?: string }) =>
        api.post<UserInfo>('/users/', data),
    updateUser: (userId: string, data: { full_name?: string; role?: string; is_active?: boolean }) =>
        api.put<UserInfo>(`/users/${userId}`, data),
    deleteUser: (userId: string) => api.delete(`/users/${userId}`),
    getCurrentUser: () => api.get<UserInfo>('/users/me'),
    changePassword: (data: { current_password: string; new_password: string }) =>
        api.post('/users/me/change-password', data),
    getSessions: () => api.get<UserSession[]>('/users/me/sessions'),
    revokeSession: (jti: string) => api.delete(`/users/me/sessions/${jti}`),
};

// ── Visitors ─────────────────────────────────────────────────────────────────

export const visitorService = {
    getVisitors: (params?: { search?: string; page?: number; limit?: number; after_cursor?: string }) =>
        api.get<PaginatedResponse<Visitor>>('/visitors/', { params }),
    getVisitor: (visitorId: string) =>
        api.get<VisitorDetail>(`/visitors/${visitorId}`),
    createVisitor: (data: {
        name?: string;
        email?: string;
        phone?: string;
        description?: string;
        notes?: string;
        is_known?: boolean;
        is_active?: boolean;
    }) => api.post('/visitors/', data),
    updateVisitor: (visitorId: string, data: {
        name?: string;
        email?: string;
        phone?: string;
        description?: string;
        notes?: string;
        is_known?: boolean;
        is_active?: boolean;
    }) => api.put(`/visitors/${visitorId}`, data),
    deleteVisitor: (visitorId: string) => api.delete(`/visitors/${visitorId}`),
    getFaceData: (visitorId: string) =>
        api.get<FaceData[]>(`/visitors/${visitorId}/face-data`),
    uploadFaceData: (visitorId: string, data: {
        embedding: number[];
        image_url?: string;
        quality_score?: number;
        face_angle?: string;
        is_primary?: boolean;
    }) => api.post(`/visitors/${visitorId}/face-data`, { ...data, visitor_id: visitorId }),
    setPrimaryFace: (visitorId: string, faceDataId: string) =>
        api.post<FaceData>(`/visitors/${visitorId}/face-data/${faceDataId}/primary`),
    deleteFaceData: (visitorId: string, faceDataId: string) =>
        api.delete(`/visitors/${visitorId}/face-data/${faceDataId}`),
    uploadFaceImage: (visitorId: string, file: File, faceAngle?: string) => {
        const formData = new FormData();
        formData.append('file', file);
        if (faceAngle) {
            formData.append('face_angle', faceAngle);
        }
        return api.post(`/visitors/${visitorId}/face-upload`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
    },
    uploadMedia: (visitorId: string, data: {
        images?: File[];
        video?: File | null;
    }) => {
        const formData = new FormData();
        (data.images || []).forEach((file) => formData.append('images', file));
        if (data.video) {
            formData.append('video', data.video);
        }
        return api.post<VisitorMediaUploadResult>(`/visitors/${visitorId}/media`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
            // Enrollment runs face detection + embedding per image/frame on the AI
            // service (seconds each on CPU). Cap the wait so a stall fails cleanly
            // with a message instead of an infinite "Finalizing Enrollment" spinner.
            timeout: 120000,
        });
    },
    bulkImport: (file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        return api.post<BulkImportResult>('/visitors/bulk-import', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
    },
    exportCsv: (params?: { search?: string; is_active?: boolean }) =>
        api.get('/visitors/export', { params, responseType: 'blob' }),
};

// ── Cameras ──────────────────────────────────────────────────────────────────

export const cameraService = {
    getCameras: () => api.get<Camera[]>('/cameras/'),
    getCamera: (cameraId: string) => api.get<Camera>(`/cameras/${cameraId}`),
    getCameraStreamFrame: (cameraId: string) =>
        api.get<Blob>(`/cameras/${cameraId}/stream-frame`, { responseType: 'blob' }),
    getCameraStreamFrameAnalyzed: (cameraId: string) =>
        api.get<AnalyzedFrameResponse>(`/cameras/${cameraId}/stream-frame/analyzed`),
    createCamera: (data: { name: string; rtsp_url?: string; location?: string }) =>
        api.post('/cameras/', data),
    updateCamera: (cameraId: string, data: { name?: string; rtsp_url?: string; location?: string; is_active?: boolean }) =>
        api.put(`/cameras/${cameraId}`, data),
    deleteCamera: (cameraId: string) => api.delete(`/cameras/${cameraId}`),
    testCamera: (cameraId: string) => api.post(`/cameras/${cameraId}/test`),
    // S21: Camera Groups
    getGroups: () => api.get('/cameras/groups'),
    createGroup: (data: { name: string; description?: string; color?: string }) =>
        api.post('/cameras/groups', data),
    updateGroup: (groupId: string, data: { name?: string; description?: string; color?: string }) =>
        api.put(`/cameras/groups/${groupId}`, data),
    deleteGroup: (groupId: string) => api.delete(`/cameras/groups/${groupId}`),
    assignGroup: (cameraId: string, groupId: string | null) =>
        api.post(`/cameras/${cameraId}/assign-group`, null, { params: { group_id: groupId } }),
    getCameraHealth: () => api.get('/cameras/health'),
};

// ── Edge Devices ───────────────────────────────────────────────────────────

export const edgeDeviceService = {
    list: () => api.get<EdgeDevice[]>('/edge-devices/'),
    get: (deviceId: string) => api.get<EdgeDevice>(`/edge-devices/${deviceId}`),
    create: (data: {
        name: string;
        device_type?: string;
        location?: string;
        endpoint_url?: string;
        ip_address?: string;
        serial_number?: string;
        hardware_info?: Record<string, any>;
        tags?: string[];
        model_version_id?: string;
        model_artifact_path?: string;
        model_config?: Record<string, any>;
    }) => api.post<EdgeDeviceTokenResponse>('/edge-devices/', data),
    update: (deviceId: string, data: Partial<EdgeDevice>) =>
        api.put<EdgeDevice>(`/edge-devices/${deviceId}`, data),
    delete: (deviceId: string) => api.delete(`/edge-devices/${deviceId}`),
    rotateToken: (deviceId: string) =>
        api.post<EdgeDeviceTokenResponse>(`/edge-devices/${deviceId}/rotate-token`),
    listEvents: (deviceId: string, limit = 50) =>
        api.get<EdgeDeviceEvent[]>(`/edge-devices/${deviceId}/events`, { params: { limit } }),
    exportOnnx: (deviceId: string, data: {
        model_path: string;
        input_shape?: number[];
        output_path?: string;
        model_name?: string;
        opset_version?: number;
    }) => api.post(`/edge-devices/${deviceId}/export/onnx`, data),
};

// ── Video Upload ─────────────────────────────────────────────────────────────

export const videoService = {
    uploadVideo: (file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        return api.post('/video/upload', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
    },
    getProcessingStatus: (jobId: string) =>
        api.get<VideoProcessingJob>(`/video/status/${jobId}`),
    getProcessingJobs: (params?: { page?: number; limit?: number }) =>
        api.get<PaginatedResponse<VideoProcessingJob>>('/video/jobs', { params }),
};

// ── Logs ─────────────────────────────────────────────────────────────────────

export const logService = {
    getLogs: (params?: {
        search?: string;
        status?: string;
        camera_id?: string;
        date_from?: string;
        date_to?: string;
        page?: number;
        limit?: number;
        after_cursor?: string;
    }) => api.get<PaginatedResponse<VisitorLog>>('/logs/', { params }),
    getUnidentifiedLogs: (params?: { page?: number; limit?: number }) =>
        api.get<PaginatedResponse<VisitorLog>>('/logs/unidentified', { params }),
    getLog: (logId: string) => api.get<VisitorLog>(`/logs/${logId}`),
    assignLog: (
        logId: string,
        visitorId: string,
        options?: {
            propagate_similar?: boolean;
            similarity_threshold?: number;
            lookback_days?: number;
            max_candidates?: number;
        },
    ) =>
        api.post(`/logs/${logId}/assign`, {
            visitor_id: visitorId,
            ...(options || {}),
        }),
    createVisitorFromLog: (logId: string, data: {
        name: string;
        email?: string;
        phone?: string;
        notes?: string;
    }) => api.post(`/logs/${logId}/create-visitor`, data),
    exportCsv: (params?: {
        search?: string;
        status?: string;
        camera_id?: string;
        date_from?: string;
        date_to?: string;
    }) => api.get('/logs/export', { params, responseType: 'blob' }),
    exportExcel: (params?: {
        search?: string;
        status?: string;
        camera_id?: string;
        date_from?: string;
        date_to?: string;
    }) => api.get('/logs/export', { params: { ...params, format: 'excel' }, responseType: 'blob' }),
    confirmLog: (logId: string, action: 'confirm' | 'reject', visitor_id?: string) =>
        api.post(`/logs/${logId}/confirm`, { confirmed: action === 'confirm', visitor_id }),
    getDashboardStats: () => api.get<DashboardStats>('/logs/stats/dashboard'),
};

// ── Audit Logs ──────────────────────────────────────────────────────────────

export interface AuditLog {
    id: string;
    organization_id: string;
    user_id: string | null;
    action: string;
    entity_type: string | null;
    entity_id: string | null;
    details: Record<string, any> | null;
    timestamp: string;
}

export const auditLogService = {
    getAuditLogs: (params?: {
        skip?: number;
        limit?: number;
        search?: string;
        action?: string;
        user_id?: string;
        date_from?: string;
        date_to?: string;
    }) =>
        api.get<PaginatedResponse<AuditLog>>('/audit-logs', { params }),
    exportCsv: (params?: {
        search?: string;
        action?: string;
        user_id?: string;
        date_from?: string;
        date_to?: string;
    }) =>
        api.get('/audit-logs/export', { params, responseType: 'blob' }),
};

// ── Live Activity Session ───────────────────────────────────────────────────

export interface CameraSession {
    id: string;
    organization_id: string;
    user_id: string;
    camera_id: string | null;
    status: string;
    started_at: string;
    ended_at: string | null;
    total_frames: number;
    total_detections: number;
    total_identifications: number;
    settings: Record<string, any> | null;
}

export interface DetectionResult {
    bbox: { x1: number; y1: number; x2: number; y2: number };
    confidence: number;
    identified: boolean;
    visitor_id: string | null;
    visitor_name: string | null;
    face_image_path: string | null;
}

export interface AnalyzedFrameResponse {
    frame_data: string; // base64-encoded JPEG
    width: number;
    height: number;
    detections: DetectionResult[];
}

export interface PersonBox {
    bbox: { x1: number; y1: number; x2: number; y2: number };
    confidence: number;
}

export interface ProcessFrameResponse {
    detections: DetectionResult[];
    persons?: PersonBox[];
    frame_number: number;
    processing_time_ms: number;
    ai_processing_time_ms?: number | null;
    ai_roundtrip_time_ms?: number | null;
    identification_time_ms?: number | null;
    average_identification_time_ms?: number | null;
}

export interface DetectionLog {
    id: string;
    session_id: string;
    visitor_id: string | null;
    timestamp: string;
    confidence: number;
    bbox: Record<string, any> | null;
    face_image_path: string | null;
    identified: boolean;
}

export interface StartLivenessChallengeResponse {
    challenge_id: string;
    challenge_type: string;
    instruction: string;
    timeout_seconds: number;
}

export interface VerifyLivenessChallengeResponse {
    challenge_id: string;
    verified: boolean;
    confidence: number;
    details: Record<string, any>;
    attempts: number;
}

export const cameraSessionService = {
    startSession: (data?: { camera_id?: string; settings?: Record<string, any> }) =>
        api.post<CameraSession>('/camera/start-session', data || {}),
    processFrame: (sessionId: string, frameData: string) =>
        api.post<ProcessFrameResponse>('/camera/process-frame', {
            session_id: sessionId,
            frame_data: frameData,
        }),
    endSession: (sessionId: string) =>
        api.post<CameraSession>(`/camera/end-session/${sessionId}`),
    getSessionLogs: (sessionId: string, params?: { skip?: number; limit?: number }) =>
        api.get<DetectionLog[]>(`/camera/session/${sessionId}/logs`, { params }),
    manualAssign: (detectionLogId: string, visitorId: string) =>
        api.post('/camera/manual-assign', {
            detection_log_id: detectionLogId,
            visitor_id: visitorId,
        }),
    listSessions: (params?: { status?: string }) =>
        api.get<CameraSession[]>('/camera/sessions', { params }),
};

export const livenessService = {
    startChallenge: (data: { visitor_log_id: string; challenge_type?: string }) =>
        api.post<StartLivenessChallengeResponse>('/liveness/challenge/start', data),
    verifyChallenge: (data: { challenge_id: string; video_frame?: string; video_frames?: string[]; video_path?: string }) =>
        api.post<VerifyLivenessChallengeResponse>('/liveness/challenge/verify', data),
    getConfig: () =>
        api.get('/liveness/config'),
    updateConfig: (config: Record<string, any>) =>
        api.put('/liveness/config', config),
    getStatistics: () =>
        api.get('/liveness/statistics'),
};

// ── Health ───────────────────────────────────────────────────────────────────

export const healthService = {
    check: () => api.get('/health'),
    readiness: () =>
        axios.get<HealthReadinessResponse>(
            `${API_BASE_URL.replace('/api/v1', '')}/health/readiness`,
        ),
};

// ── Alerts ───────────────────────────────────────────────────────────────────

export interface AlertConfig {
    id: string;
    organization_id: string;
    alerts_enabled: boolean;
    email_alerts_enabled: boolean;
    webhook_alerts_enabled: boolean;
    min_confidence_threshold: number;
    alert_duplicate_window_seconds: number;
    enabled_alert_types: string[];
    default_action: string;
    created_at: string;
    updated_at: string | null;
}

export interface AlertRule {
    id: string;
    organization_id: string;
    alert_config_id: string;
    name: string;
    description: string | null;
    is_active: boolean;
    trigger_type: string;
    min_confidence: number;
    action: string;
    order: number;
    created_at: string;
    updated_at: string | null;
}

export const alertService = {
    getConfig: () => api.get<AlertConfig>('/alerts/config'),
    updateConfig: (data: Partial<AlertConfig>) =>
        api.put<AlertConfig>('/alerts/config', data),
    getRules: (params?: { is_active?: boolean; trigger_type?: string }) =>
        api.get<AlertRule[]>('/alerts/rules', { params }),
    getRule: (ruleId: string) =>
        api.get<AlertRule>(`/alerts/rules/${ruleId}`),
    createRule: (data: {
        name: string;
        description?: string;
        is_active?: boolean;
        trigger_type: string;
        min_confidence?: number;
        action?: string;
    }) => api.post<AlertRule>('/alerts/rules', data),
    updateRule: (ruleId: string, data: Partial<AlertRule>) =>
        api.put<AlertRule>(`/alerts/rules/${ruleId}`, data),
    deleteRule: (ruleId: string) =>
        api.delete(`/alerts/rules/${ruleId}`),
    activateRule: (ruleId: string) =>
        api.post(`/alerts/rules/${ruleId}/activate`),
    deactivateRule: (ruleId: string) =>
        api.post(`/alerts/rules/${ruleId}/deactivate`),
    getTriggers: (params?: { rule_id?: string; days?: number }) =>
        api.get('/alerts/triggers', { params }),
    getStats: (params?: { days?: number }) =>
        api.get('/alerts/stats', { params }),
};

// ── S14: Training Data & Model Management ───────────────────────────────────

export const modelService = {
    retrain: () => api.post('/models/retrain'),
    importDirectory: () => api.post('/models/import-directory'),
    batchUpload: (visitorId: string, files: File[]) => {
        const formData = new FormData();
        files.forEach(f => formData.append('files', f));
        return api.post(`/models/batch-upload/${visitorId}`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
    },
    qualityCheck: (files: File[]) => {
        const formData = new FormData();
        files.forEach(f => formData.append('files', f));
        return api.post('/models/quality-check', formData, {
            headers: { 'Content-Type': 'multipart/form-data' },
        });
    },
    getTrainingStats: () => api.get('/models/training-stats'),
    augment: (visitorId: string) => api.post(`/models/augment/${visitorId}`),
};

// ── S15: Recommendations ────────────────────────────────────────────────────

export const recommendationService = {
    getAll: () => api.get('/recommendations/'),
    getFaceQuality: () => api.get('/recommendations/face-quality'),
    getThresholdOptimization: () => api.get('/recommendations/threshold-optimization'),
};

// ── S16: Accuracy ───────────────────────────────────────────────────────────

export const accuracyService = {
    getStats: () => api.get('/accuracy/stats'),
    setVisitorThreshold: (visitorId: string, data: { custom_threshold: number | null; auto_learn?: boolean }) =>
        api.put(`/accuracy/visitor/${visitorId}/threshold`, data),
    getLivenessConfig: () => api.get('/accuracy/liveness-config'),
    updateLivenessConfig: (config: Record<string, any>) =>
        api.put('/accuracy/liveness-config', config),
    getAntiSpoofingConfig: () => api.get('/accuracy/anti-spoofing-config'),
    updateAntiSpoofingConfig: (config: Record<string, any>) =>
        api.put('/accuracy/anti-spoofing-config', config),
    triggerContinuousLearning: (logId: string) =>
        api.post(`/accuracy/continuous-learning/${logId}`),
};

// ── S17: Data Quality ───────────────────────────────────────────────────────

export const dataQualityService = {
    getReport: () => api.get('/data-quality/report'),
    getConfig: () => api.get('/data-quality/config'),
    updateConfig: (config: Record<string, any>) => api.post('/data-quality/config', config),
    startAudit: (datasetName: string) =>
        api.post('/data-quality/audit', null, { params: { dataset_name: datasetName } }),
    getAuditJob: (jobId: string) => api.get(`/data-quality/audit/${jobId}`),
    getTrends: () => api.get('/data-quality/trends'),
};

// ── S18: Analytics & Insights ───────────────────────────────────────────────

export const analyticsService = {
    getAccuracyDashboard: () => api.get('/analytics/accuracy-dashboard'),
    getVisitorPatterns: () => api.get('/analytics/visitor-patterns'),
    getSystemHealth: () => api.get('/analytics/system-health'),
    getEmotionAnalytics: (lookbackDays = 7) =>
        api.get<EmotionAnalyticsSummary>('/analytics/emotion-analytics', { params: { lookback_days: lookbackDays } }),
    getVisitorFlow: (lookbackHours = 24, cameraId?: string) =>
        api.get<VisitorFlowAnalytics>('/analytics/visitor-flow', { params: { lookback_hours: lookbackHours, camera_id: cameraId } }),
    getRealtimeTracking: () => api.get('/analytics/realtime-tracking'),
    generateReport: (
        data: { report_type: string; format?: string; period?: string; date_from?: string; date_to?: string },
        config?: AxiosRequestConfig
    ) => api.post('/analytics/reports', data, config),
};

// ── S19: Webhooks & API Keys ────────────────────────────────────────────────

export const webhookService = {
    list: () => api.get('/webhooks/'),
    create: (data: { url: string; events: string[]; secret?: string }) =>
        api.post('/webhooks/', data),
    update: (id: string, data: { url?: string; events?: string[]; is_active?: boolean }) =>
        api.put(`/webhooks/${id}`, data),
    delete: (id: string) => api.delete(`/webhooks/${id}`),
    test: (id: string) => api.post(`/webhooks/${id}/test`),
    getLogs: (id: string) => api.get(`/webhooks/${id}/logs`),
    // API Keys
    listApiKeys: () => api.get('/webhooks/api-keys/'),
    createApiKey: (data: { name: string; permissions?: string[] }) =>
        api.post('/webhooks/api-keys/', data),
    deleteApiKey: (id: string) => api.delete(`/webhooks/api-keys/${id}`),
};

// ── S20: Compliance ─────────────────────────────────────────────────────────

export interface EncryptionVerification {
    encryption_enabled: boolean;
    total_embeddings: number;
    encrypted_count: number;
    unencrypted_count: number;
    verification_status: 'passed' | 'warning' | 'failed';
}

export interface RetentionPolicy {
    id: string;
    organization_id: string;
    entity_type: string;
    retention_days: number;
    auto_delete: boolean;
    last_cleanup_at: string | null;
    created_at: string;
}

export const complianceService = {
    verifyEncryption: () => api.get<EncryptionVerification>('/compliance/encryption-verify'),
    getRetentionPolicies: () => api.get<RetentionPolicy[]>('/compliance/retention-policies'),
    createRetentionPolicy: (data: { entity_type: string; retention_days: number; auto_delete: boolean }) =>
        api.post<RetentionPolicy>('/compliance/retention-policies', data),
    runRetentionCleanup: () => api.post<{ entity_type: string; records_deleted: number; cutoff_date: string }[]>('/compliance/retention-cleanup'),
    gdprExport: (visitorId: string) => api.get(`/compliance/gdpr/export/${visitorId}`),
    gdprDelete: (visitorId: string) => api.delete(`/compliance/gdpr/delete/${visitorId}`),
};

// ── Reports (PDF exports) — stable core routes, `backend/api/reports.py` ────

export const reportService = {
    getAuditPdf: (params?: { start_date?: string; end_date?: string }) =>
        api.get('/reports/audit/pdf', { params, responseType: 'blob' }),
};

export interface GdprRetentionPolicy {
    id: string;
    data_type: 'face_images' | 'face_embeddings' | 'logs';
    retention_days: number;
    auto_delete_enabled: boolean;
    created_at: string;
}

export interface GdprRequest {
    id: string;
    visitor_id: string;
    request_type: 'data_export' | 'data_deletion' | 'consent_withdrawal';
    status: 'pending' | 'processing' | 'completed';
    request_date: string;
    completion_date?: string;
    response_file_url?: string;
    notes?: string;
}

export interface GdprRetentionPolicyPayload {
    data_type: GdprRetentionPolicy['data_type'];
    retention_days: number;
    auto_delete_enabled: boolean;
}

export const gdprService = {
    listPolicies: (organizationId: string) =>
        api.get<GdprRetentionPolicy[]>(`/gdpr/policies/${organizationId}`),
    listPendingRequests: () => api.get<GdprRequest[]>('/gdpr/pending'),
    updatePolicies: (organizationId: string, policies: GdprRetentionPolicyPayload[]) =>
        api.put<GdprRetentionPolicy[]>(`/gdpr/policies/${organizationId}`, policies),
    processRequest: (requestId: string, data: { action: 'approve' | 'reject' }) =>
        api.post(`/gdpr/requests/${requestId}/process`, data),
    bulkProcess: (requestIds: string[], action: 'approve' | 'reject') =>
        api.post<{ action: string; results: Record<string, string>; processed: number }>(
            '/gdpr/requests/bulk-process',
            { request_ids: requestIds, action },
        ),
};

export interface SsoProvider {
    id: string;
    provider_type: 'saml' | 'oauth2' | 'openid';
    provider_name: string;
    entity_id?: string;
    sso_url?: string;
    certificate?: string;
    active: boolean;
    created_at: string;
}

export interface SsoProviderPayload {
    provider_type: SsoProvider['provider_type'];
    provider_name: string;
    entity_id?: string;
    sso_url?: string;
    certificate?: string;
}

export const ssoService = {
    listProviders: () => api.get<SsoProvider[]>('/sso/providers'),
    createProvider: (data: SsoProviderPayload) => api.post<SsoProvider>('/sso/configure', data),
    updateProvider: (providerId: string, data: Partial<SsoProviderPayload> & { active?: boolean }) =>
        api.put<SsoProvider>(`/sso/providers/${providerId}`, data),
    deleteProvider: (providerId: string) => api.delete(`/sso/providers/${providerId}`),
};

// ── LDAP ───────────────────────────────────────────────────────────────────

export interface LdapConfig {
    id: string;
    organization_id: string;
    ldap_server: string;
    ldap_port: number;
    use_ssl: boolean;
    bind_dn?: string | null;
    user_search_base: string;
    group_search_base?: string | null;
    user_attribute: string;
    group_attribute: string;
    active: boolean;
    has_bind_password: boolean;
    last_sync_at?: string | null;
    last_sync_status?: string | null;
    created_at: string;
    updated_at?: string | null;
}

export interface LdapConfigPayload {
    ldap_server: string;
    ldap_port: number;
    use_ssl: boolean;
    bind_dn?: string | null;
    bind_password?: string;
    user_search_base: string;
    group_search_base?: string | null;
    user_attribute: string;
    group_attribute: string;
    active: boolean;
}

export interface LdapConnectionTestResponse {
    status: string;
    message: string;
    details: Record<string, string>;
}

export interface LdapSyncLog {
    id: string;
    organization_id: string;
    ldap_config_id: string;
    users_synced: number;
    groups_synced: number;
    users_disabled: number;
    status: string;
    error_message?: string | null;
    created_at: string;
}

export interface LdapSyncLogListResponse {
    total: number;
    items: LdapSyncLog[];
}

export interface LdapSyncResponse {
    status: string;
    message: string;
    users_synced: number;
    groups_synced: number;
    users_disabled: number;
    log_id: string;
}

export const ldapService = {
    getConfig: () => api.get<LdapConfig | null>('/ldap/config'),
    listConfigs: () => api.get<LdapConfig[]>('/ldap/configs'),
    createConfig: (data: LdapConfigPayload) => api.post<LdapConfig>('/ldap/config', data),
    updateConfig: (configId: string, data: Partial<LdapConfigPayload>) =>
        api.put<LdapConfig>(`/ldap/config/${configId}`, data),
    deleteConfig: (configId: string) => api.delete(`/ldap/config/${configId}`),
    testConfig: (configId: string) => api.post<LdapConnectionTestResponse>(`/ldap/config/${configId}/test`),
    sync: (configId: string) => api.post<LdapSyncResponse>(`/ldap/config/${configId}/sync`),
    listSyncLogs: (limit = 25) => api.get<LdapSyncLogListResponse>('/ldap/sync-logs', { params: { limit } }),
};

// ── S22: Notifications ──────────────────────────────────────────────────────

export interface Notification {
    id: string;
    type: string;
    title: string;
    message: string;
    is_read: boolean;
    data: Record<string, any> | null;
    created_at: string;
}

export const notificationService = {
    list: (unreadOnly?: boolean) =>
        api.get('/notifications/', { params: unreadOnly ? { unread_only: true } : {} }),
    getUnreadCount: () => api.get<{ count: number }>('/notifications/unread-count'),
    markRead: (id: string) => api.put(`/notifications/${id}/read`),
    markAllRead: () => api.put('/notifications/read-all'),
    delete: (id: string) => api.delete(`/notifications/${id}`),
    getPreferences: () => api.get('/notifications/preferences'),
    updatePreferences: (prefs: Record<string, any>) =>
        api.put('/notifications/preferences', prefs),
};

// ── S26-S27: Future Enhancements ────────────────────────────────────────────

export interface FutureEnhancement {
    id: string;
    organization_id: string;
    story_id: string;
    category: string;
    title: string;
    description: string | null;
    status: string;
    priority: string;
    config: Record<string, any> | null;
    metrics: Record<string, any> | null;
    roadmap_phase: string | null;
    enabled: boolean;
    created_at: string;
    updated_at: string | null;
}

export interface RateLimitRule {
    id: string;
    organization_id: string;
    endpoint_pattern: string;
    max_requests: number;
    window_seconds: number;
    current_count: number;
    window_start: string | null;
    is_active: boolean;
    created_at: string;
}

export interface CarbonMetricsRecord {
    id: string;
    organization_id: string;
    period_start: string;
    period_end: string;
    gpu_hours: number;
    cpu_hours: number;
    estimated_kwh: number;
    estimated_co2_kg: number;
    training_runs: number;
    inference_count: number;
    optimization_notes: string | null;
    created_at: string;
}

export interface CarbonMetricsSummary {
    total_gpu_hours: number;
    total_cpu_hours: number;
    total_kwh: number;
    total_co2_kg: number;
    total_training_runs: number;
    total_inference_count: number;
    efficiency_score: number;
    monthly_trend: Record<string, any>[];
}

export interface RoadmapTask {
    task: string;
    description: string;
    effort: string;
}

export interface RoadmapPhase {
    phase: string;
    title: string;
    description: string;
    timeline: string;
    tasks: RoadmapTask[];
    enhancements: FutureEnhancement[];
    progress_percent: number;
}

export interface RoadmapResponse {
    phases: RoadmapPhase[];
    total_enhancements: number;
    enabled_count: number;
    completion_percent: number;
}

export interface BiasAuditResult {
    overall_fairness_score: number;
    demographic_parity: Record<string, any>;
    equal_opportunity: Record<string, any>;
    recommendations: string[];
    audited_at: string;
}

export interface ExplainabilityResult {
    model_name: string;
    feature_importance: Record<string, number>;
    decision_factors: Record<string, any>[];
    confidence_breakdown: Record<string, any>;
    explanation_method: string;
}

// S27 interfaces
export interface AugmentationTechniqueConfig {
    technique: string;
    enabled: boolean;
    params: Record<string, any> | null;
    description: string | null;
}

export interface AugmentationConfigResponse {
    techniques: AugmentationTechniqueConfig[];
    quality_checks_enabled: boolean;
    auto_balance_demographics: boolean;
    data_quality_actions: string[];
}

export interface ModelArchitectureResponse {
    current_architecture: string;
    vit_config: Record<string, any>;
    hybrid_config: Record<string, any>;
    ensemble_config: Record<string, any>;
    available_backbones: string[];
    available_vit_variants: string[];
    available_ensemble_methods: string[];
}

export interface TrainingStrategyResponse {
    self_supervised: Record<string, any>;
    continual_learning: Record<string, any>;
    hyperparameter_optimization: Record<string, any>;
    available_ssl_methods: string[];
    available_hpo_methods: string[];
}

export interface RobustnessConfigResponse {
    adversarial_defense: Record<string, any>;
    occlusion_handling: Record<string, any>;
    defense_techniques: string[];
}

export interface AccuracyBoostResponse {
    multi_angle: Record<string, any>;
    consensus_voting: Record<string, any>;
    temporal_enhancement: Record<string, any>;
    available_angles: string[];
}

export interface PerformanceConfigResponse {
    current_latency: Record<string, number>;
    target_latency: Record<string, number>;
    gpu_optimizations: Record<string, boolean>;
    optimization_techniques: string[];
}

export interface PriorityMatrixItem {
    enhancement: string;
    impact: string;
    effort: string;
    roi: string;
    priority_tier: string;
    category: string | null;
}

export interface PriorityMatrixResponse {
    high_priority: PriorityMatrixItem[];
    medium_priority: PriorityMatrixItem[];
    low_priority: PriorityMatrixItem[];
    total_items: number;
}

export interface MetricTarget {
    metric: string;
    current: string;
    target: string;
    method: string | null;
}

export interface MetricsTargetsResponse {
    accuracy_metrics: MetricTarget[];
    system_metrics: MetricTarget[];
    business_metrics: MetricTarget[];
}

export interface CurrentCapability {
    feature: string;
    technology: string;
    status: string;
}

export interface CurrentLimitation {
    description: string;
    severity: string;
}

export interface CurrentPhaseItem {
    name: string;
    component: string;
    status: string;
}

export interface CurrentPhaseSummary {
    phase: string;
    title: string;
    focus: string;
    status: string;
    implemented_count: number;
    planned_count: number;
    items: CurrentPhaseItem[];
}

export interface CurrentCapabilitiesResponse {
    implemented_features: CurrentCapability[];
    current_limitations: CurrentLimitation[];
    phase_summary: CurrentPhaseSummary[];
    system_version: string;
}

export interface HealthReadinessCheck {
    status: string;
    value: any;
    detail: string;
    missing?: string[];
}

export interface HealthReadinessResponse {
    status: string;
    checks: Record<string, HealthReadinessCheck>;
    timestamp: string;
}

export interface BlueprintGapItem {
    area: string;
    status: string;
    impact: string;
    notes: string;
}

export interface BlueprintLayer {
    name: string;
    capabilities: string[];
}

export interface BlueprintModelRecommendation {
    task: string;
    primary: string;
    alternatives: string[];
    rationale: string;
}

export interface BlueprintPhase {
    phase: string;
    timeline: string;
    goals: string[];
    deliverables: string[];
}

export interface NextGenBlueprintResponse {
    platform_status: string;
    gaps: BlueprintGapItem[];
    target_architecture: BlueprintLayer[];
    model_recommendations: BlueprintModelRecommendation[];
    serving_stack: string[];
    mlops_stack: string[];
    security_baseline: string[];
    inference_latency_targets_ms: Record<string, number>;
    phased_rollout: BlueprintPhase[];
}

export interface RuntimeModelComponent {
    component: string;
    display_name: string;
    current_model: string;
    current_artifact?: string | null;
    target_model?: string | null;
    target_artifact?: string | null;
    framework: string;
    runtime: string;
    status: string;
    notes?: string | null;
}

export interface RuntimeModelRegistryResponse {
    version: string;
    source: string;
    last_updated_at?: string | null;
    data_dir?: string | null;
    components: RuntimeModelComponent[];
}

export interface RuntimeModelRegistryUpdate {
    version?: string;
    components: RuntimeModelComponent[];
}

export interface BenchmarkSummaryResponse {
    status: string;
    sample_size: number;
    run_at?: string | null;
    baseline_accuracy?: number | null;
    multi_angle_accuracy?: number | null;
    multi_angle_boost_pct?: number | null;
    mean_reciprocal_rank?: number | null;
    avg_latency_ms?: number | null;
    latency_target_met: boolean;
    production_ready: boolean;
    target_baseline_accuracy: number;
    target_latency_ms: number;
    accuracy_gap_pct?: number | null;
    latency_budget_remaining_ms?: number | null;
    recommendation?: string | null;
    results_path?: string | null;
    gate_metrics: BenchmarkGateMetric[];
    history: BenchmarkTrendPoint[];
}

export interface BenchmarkGateMetric {
    name: string;
    status: string;
    current_value?: number | null;
    target_value?: number | null;
    unit: string;
    detail: string;
}

export interface BenchmarkTrendPoint {
    run_at: string;
    sample_size: number;
    status: string;
    baseline_accuracy?: number | null;
    multi_angle_accuracy?: number | null;
    avg_latency_ms?: number | null;
    production_ready: boolean;
    latency_target_met: boolean;
}

export interface StreamHealthItem {
    camera_id: string;
    camera_name: string;
    status: string;
    is_active: boolean;
    has_rtsp: boolean;
    last_seen: string | null;
    seconds_since_last_seen: number | null;
    is_stale: boolean;
    health_source: string;
    probe_attempted: boolean;
    probe_connected?: boolean | null;
    probe_latency_ms?: number | null;
    probe_width?: number | null;
    probe_height?: number | null;
    probe_fps?: number | null;
    probe_error?: string | null;
    recovery_hint: string;
}

export interface CrossCameraReidMatch {
    visitor_id: string;
    visitor_name: string | null;
    camera_ids: string[];
    sightings: number;
    average_confidence: number;
    first_seen: string;
    last_seen: string;
    transition_count: number;
    reid_score: number;
    top_transitions: {
        from_camera_id: string;
        to_camera_id: string;
        count: number;
        avg_transition_seconds: number | null;
    }[];
}

export interface CrossCameraReidResponse {
    query_camera_id: string | null;
    lookback_minutes: number;
    evaluated_logs: number;
    candidate_visitors: number;
    generated_at: string | null;
    matches: CrossCameraReidMatch[];
}

export interface CrossCameraMovementSummaryItem {
    id: string;
    visitor_id: string;
    visitor_name?: string | null;
    from_camera_id: string;
    from_camera_name?: string | null;
    to_camera_id: string;
    to_camera_name?: string | null;
    first_seen: string;
    last_seen: string;
    transition_count: number;
    sightings: number;
    average_confidence: number;
    avg_transition_seconds?: number | null;
    reid_score: number;
    source: string;
    details: Record<string, any>;
    updated_at?: string | null;
}

export interface CrossCameraMovementSyncResponse {
    lookback_minutes: number;
    synced_matches: number;
    upserted_movements: number;
    generated_at?: string | null;
    items: CrossCameraMovementSummaryItem[];
}

export interface CrossCameraMovementListResponse {
    total: number;
    items: CrossCameraMovementSummaryItem[];
}

export interface NLAnalyticsQueryResponse {
    query: string;
    interpreted_intent: string;
    summary: string;
    result: Record<string, any>;
}

export interface VisionInferenceRequest {
    camera_id?: string;
    rtsp_url?: string;
    frame_data?: string;
    image_path?: string;
}

export interface PoseEstimateResponse {
    source: string;
    camera_id?: string | null;
    status: string;
    available: boolean;
    model: string;
    posture: string;
    keypoint_count: number;
    average_visibility: number;
    processing_time_ms: number;
    message?: string | null;
    snapshot_thumbnail?: string | null;
    analytics_event_id?: string | null;
}

export interface ActionInferRequest extends VisionInferenceRequest {
    track_id?: string;
}

export interface ActionInferResponse {
    source: string;
    camera_id?: string | null;
    status: string;
    available: boolean;
    model: string;
    action: string;
    gesture: string;
    confidence: number;
    posture: string;
    keypoint_count: number;
    processing_time_ms: number;
    message?: string | null;
    flags: Record<string, any>;
    snapshot_thumbnail?: string | null;
    analytics_event_id?: string | null;
}

export interface VisionAnalyticsHistoryItem {
    id: string;
    event_type: string;
    source: string;
    camera_id?: string | null;
    camera_name?: string | null;
    model?: string | null;
    status: string;
    summary?: string | null;
    posture?: string | null;
    action?: string | null;
    gesture?: string | null;
    confidence?: number | null;
    snapshot_url?: string | null;
    created_at: string;
}

export interface VisionAnalyticsHistoryResponse {
    event_type?: string | null;
    lookback_hours: number;
    total: number;
    items: VisionAnalyticsHistoryItem[];
}

export interface BehaviorAnalyzeRequest extends ActionInferRequest {
    visitor_id?: string;
    visitor_log_id?: string;
    source?: string;
}

export interface BehaviorEventItem {
    id: string;
    event_type: string;
    source: string;
    visitor_id?: string | null;
    visitor_name?: string | null;
    visitor_log_id?: string | null;
    camera_id?: string | null;
    camera_name?: string | null;
    posture?: string | null;
    action?: string | null;
    gesture?: string | null;
    confidence: number;
    anomaly_score: number;
    anomaly_label: string;
    severity: string;
    reviewed: boolean;
    details: Record<string, any>;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface BehaviorEventListResponse {
    total: number;
    anomaly_count: number;
    critical_count: number;
    items: BehaviorEventItem[];
}

export interface BehaviorEventUpdateRequest {
    reviewed: boolean;
    notes?: string;
}

export interface ContinuousLearningSignalItem {
    id: string;
    signal_type: string;
    priority: string;
    status: string;
    confidence?: number | null;
    source: string;
    visitor_id?: string | null;
    visitor_name?: string | null;
    visitor_log_id?: string | null;
    behavior_event_id?: string | null;
    details: Record<string, any>;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface ContinuousLearningSignalListResponse {
    total: number;
    open_count: number;
    queued_count: number;
    items: ContinuousLearningSignalItem[];
}

export interface ContinuousLearningSignalUpdateRequest {
    status: string;
    resolution?: string;
    notes?: string;
}

export interface ContinuousLearningSignalPromoteRequest {
    visitor_id?: string;
    is_positive?: boolean;
    source?: string;
    confidence?: number;
    face_image_path?: string;
}

export interface ContinuousLearningSignalPromoteResponse {
    signal: ContinuousLearningSignalItem;
    sample_id?: string | null;
}

export interface ThreeDFaceCapturePayload {
    visitor_id: string;
    detection_log_id?: string;
    depth_map_path?: string;
    point_cloud_path?: string;
    face_mesh?: Record<string, any>;
    texture_map_path?: string;
    face_width_mm?: number;
    face_height_mm?: number;
    face_depth_mm?: number;
    forehead_width_mm?: number;
    nose_height_mm?: number;
    embedding_3d?: number[];
    embedding_confidence?: number;
    capture_quality_score?: number;
    mesh_density?: number;
    depth_map_resolution?: string;
}

export interface ThreeDFaceResponse {
    id: string;
    visitor_id: string;
    detection_log_id?: string | null;
    embedding_confidence: number;
    capture_quality_score: number;
    created_at: string;
}

export interface ThreeDFaceComparePayload {
    face_data_1_id: string;
    face_data_2_id: string;
    match_threshold?: number;
}

export interface ThreeDFaceCompareResponse {
    id: string;
    face_data_1_id: string;
    face_data_2_id: string;
    euclidean_distance?: number | null;
    cosine_similarity?: number | null;
    l2_distance?: number | null;
    shape_similarity?: number | null;
    texture_similarity?: number | null;
    geometric_liveness_score?: number | null;
    match_confidence: number;
    is_same_person: boolean;
    created_at: string;
}

export interface ThreeDFaceLivenessResponse {
    face_data_id: string;
    geometric_liveness_score: number;
}

export interface ContinuousLearningQueueRequest {
    signal_ids?: string[];
    max_samples?: number;
    min_priority?: string;
    strategy?: string;
}

export interface ContinuousLearningQueueResponse {
    job_id: string;
    queued_signal_count: number;
    selected_signal_ids: string[];
    strategy: string;
    training_recommended: boolean;
}

export interface SyntheticGenerationJob {
    id: string;
    organization_id: string;
    status: string;
    total_target: number;
    samples_generated: number;
    samples_validated: number;
    samples_rejected: number;
    avg_fid?: number | null;
    avg_lpips?: number | null;
    avg_detection_confidence?: number | null;
    started_at?: string | null;
    completed_at?: string | null;
}

export interface SyntheticQualityMetrics {
    id: string;
    job_id: string;
    measurement_timestamp: string;
    total_samples: number;
    valid_samples: number;
    acceptance_rate?: number | null;
    avg_fid?: number | null;
    avg_lpips?: number | null;
    avg_detection_confidence?: number | null;
    demographic_distribution: Record<string, any>;
}

export interface TemporalAugmentationJob {
    id: string;
    organization_id: string;
    config_id: string;
    input_video_path?: string | null;
    input_face_id?: string | null;
    status: string;
    error_message?: string | null;
    total_frames: number;
    processed_frames: number;
    generated_sequences: number;
    avg_expression_confidence?: number | null;
    avg_optical_flow?: number | null;
    started_at?: string | null;
    completed_at?: string | null;
    duration_seconds?: number | null;
    created_at: string;
}

export interface TemporalExpressionMetrics {
    id: string;
    organization_id: string;
    job_id: string;
    measurement_timestamp: string;
    expression_distribution: Record<string, number>;
    transition_distribution: Record<string, number>;
    avg_confidence?: number | null;
    acceptance_rate?: number | null;
    created_at: string;
}

export interface BehaviorAnalysisResponse {
    pose_estimate: PoseEstimateResponse;
    action_inference: ActionInferResponse;
    event: BehaviorEventItem;
    signal_created: boolean;
    learning_signal?: ContinuousLearningSignalItem | null;
    anomaly_reasons: string[];
}

export interface MLflowModelVersionSummary {
    component: string;
    registered_model: string;
    version: string;
    stage: string;
    run_id?: string | null;
    artifact_uri?: string | null;
    metrics: Record<string, number>;
    tags: Record<string, string>;
    last_transitioned_at?: string | null;
}

export interface ModelPromotionRecord {
    promotion_id: string;
    component: string;
    previous_model?: string | null;
    previous_artifact?: string | null;
    candidate_model: string;
    candidate_artifact?: string | null;
    requested_by: string;
    requested_at: string;
    benchmark_status: string;
    benchmark_production_ready: boolean;
    benchmark_sample_size: number;
    reason?: string | null;
    applied: boolean;
    applied_at?: string | null;
    notes?: string | null;
}

export interface MLflowRegistryResponse {
    status: string;
    tracking_uri: string;
    mlflow_available: boolean;
    last_updated_at?: string | null;
    models: MLflowModelVersionSummary[];
    promotions: ModelPromotionRecord[];
}

export interface MLflowPromotionHealthSummary {
    total_promotions: number;
    applied_promotions: number;
    blocked_promotions: number;
    last_promotion_at?: string | null;
}

export interface ModelPromotionRequest {
    component: string;
    candidate_model: string;
    candidate_artifact?: string;
    reason?: string;
    benchmark_sample_size?: number;
    require_production_ready?: boolean;
}

export interface ModelPromotionResponse {
    status: string;
    message: string;
    promotion: ModelPromotionRecord;
    runtime_registry: RuntimeModelRegistryResponse;
    benchmark_summary: BenchmarkSummaryResponse;
}

export const futureEnhancementService = {
    // Enhancements CRUD
    list: (params?: { category?: string; status?: string; roadmap_phase?: string }) =>
        api.get<FutureEnhancement[]>('/future-enhancements/', { params }),
    get: (storyId: string) =>
        api.get<FutureEnhancement>(`/future-enhancements/${storyId}`),
    create: (data: { story_id: string; category: string; title: string; description?: string; priority?: string; roadmap_phase?: string }) =>
        api.post<FutureEnhancement>('/future-enhancements/', data),
    update: (storyId: string, data: { title?: string; description?: string; status?: string; priority?: string; config?: Record<string, any>; enabled?: boolean }) =>
        api.put<FutureEnhancement>(`/future-enhancements/${storyId}`, data),
    toggle: (storyId: string) =>
        api.post<FutureEnhancement>(`/future-enhancements/${storyId}/toggle`),

    // Roadmap
    getRoadmap: () =>
        api.get<RoadmapResponse>('/future-enhancements/roadmap/overview'),

    // Bias audit
    runBiasAudit: () =>
        api.get<BiasAuditResult>('/future-enhancements/audit/bias'),

    // Explainability
    getExplainability: () =>
        api.get<ExplainabilityResult>('/future-enhancements/explainability/summary'),

    // Rate limits
    listRateLimits: () =>
        api.get<RateLimitRule[]>('/future-enhancements/rate-limits/'),
    createRateLimit: (data: { endpoint_pattern: string; max_requests: number; window_seconds: number }) =>
        api.post<RateLimitRule>('/future-enhancements/rate-limits/', data),
    updateRateLimit: (ruleId: string, data: { endpoint_pattern?: string; max_requests?: number; window_seconds?: number; is_active?: boolean }) =>
        api.put<RateLimitRule>(`/future-enhancements/rate-limits/${ruleId}`, data),
    deleteRateLimit: (ruleId: string) =>
        api.delete(`/future-enhancements/rate-limits/${ruleId}`),

    // Carbon metrics
    listCarbonMetrics: () =>
        api.get<CarbonMetricsRecord[]>('/future-enhancements/carbon/metrics'),
    recordCarbonMetrics: (data: { period_start: string; period_end: string; gpu_hours: number; cpu_hours: number; estimated_kwh: number; estimated_co2_kg: number; training_runs: number; inference_count: number }) =>
        api.post<CarbonMetricsRecord>('/future-enhancements/carbon/metrics', data),
    getCarbonSummary: () =>
        api.get<CarbonMetricsSummary>('/future-enhancements/carbon/summary'),

    // S27: Current capabilities
    getCurrentCapabilities: () =>
        api.get<CurrentCapabilitiesResponse>('/future-enhancements/capabilities/current'),

    // Next-gen production blueprint
    getNextGenBlueprint: () =>
        api.get<NextGenBlueprintResponse>('/future-enhancements/blueprint/next-gen'),

    // Runtime registry and benchmark baseline
    getRuntimeModelRegistry: () =>
        api.get<RuntimeModelRegistryResponse>('/future-enhancements/runtime-registry'),
    updateRuntimeModelRegistry: (data: RuntimeModelRegistryUpdate) =>
        api.put<RuntimeModelRegistryResponse>('/future-enhancements/runtime-registry', data),
    getBaselineBenchmarkSummary: () =>
        api.get<BenchmarkSummaryResponse>('/future-enhancements/benchmark/summary'),
    runBaselineBenchmark: (sampleSize = 30) =>
        api.post<BenchmarkSummaryResponse>('/future-enhancements/benchmark/run', undefined, {
            params: { sample_size: sampleSize },
        }),
    getMlflowRegistry: () =>
        api.get<MLflowRegistryResponse>('/future-enhancements/mlflow/registry'),
    getMlflowHealthSummary: () =>
        api.get<MLflowPromotionHealthSummary>('/future-enhancements/mlflow/health-summary'),
    getMlflowPromotions: (limit = 20) =>
        api.get<ModelPromotionRecord[]>('/future-enhancements/mlflow/promotions', { params: { limit } }),
    promoteMlflowModel: (data: ModelPromotionRequest) =>
        api.post<ModelPromotionResponse>('/future-enhancements/mlflow/promote', data),
    getStreamHealth: (staleAfterSeconds = 90, probeMode = false, probeTimeoutSeconds = 4) =>
        api.get<StreamHealthItem[]>('/future-enhancements/streams/health', {
            params: {
                stale_after_seconds: staleAfterSeconds,
                probe_mode: probeMode,
                probe_timeout_seconds: probeTimeoutSeconds,
            },
        }),
    searchCrossCameraReid: (data?: {
        camera_id?: string;
        visitor_id?: string;
        lookback_minutes?: number;
        limit?: number;
        min_camera_count?: number;
        min_sightings?: number;
        min_avg_confidence?: number;
        min_reid_score?: number;
    }) =>
        api.post<CrossCameraReidResponse>('/future-enhancements/reid/cross-camera/search', data || {}),
    syncCrossCameraMovements: (data?: {
        camera_id?: string;
        visitor_id?: string;
        lookback_minutes?: number;
        limit?: number;
        min_camera_count?: number;
        min_sightings?: number;
        min_avg_confidence?: number;
        min_reid_score?: number;
        overwrite_existing?: boolean;
    }) =>
        api.post<CrossCameraMovementSyncResponse>('/future-enhancements/reid/cross-camera/sync', data || {}),
    listCrossCameraMovements: (params?: { visitor_id?: string; camera_id?: string; limit?: number }) =>
        api.get<CrossCameraMovementListResponse>('/future-enhancements/reid/cross-camera/movements', { params }),
    queryAnalytics: (query: string, lookbackHours = 24) =>
        api.post<NLAnalyticsQueryResponse>('/future-enhancements/analytics/query', {
            query,
            lookback_hours: lookbackHours,
        }),
    runPoseEstimate: (data: VisionInferenceRequest) =>
        api.post<PoseEstimateResponse>('/future-enhancements/vision/pose-estimate', data),
    runActionInference: (data: ActionInferRequest) =>
        api.post<ActionInferResponse>('/future-enhancements/vision/action-infer', data),
    analyzeBehavior: (data: BehaviorAnalyzeRequest) =>
        api.post<BehaviorAnalysisResponse>('/future-enhancements/behavior/analyze', data),
    listBehaviorEvents: (params?: { limit?: number; event_type?: string; severity?: string; reviewed?: boolean; min_anomaly_score?: number }) =>
        api.get<BehaviorEventListResponse>('/future-enhancements/behavior/events', { params }),
    listContinuousLearningSignals: (params?: { limit?: number; status?: string; min_priority?: string }) =>
        api.get<ContinuousLearningSignalListResponse>('/future-enhancements/continuous-learning/signals', { params }),
    queueContinuousLearningSignals: (data: ContinuousLearningQueueRequest) =>
        api.post<ContinuousLearningQueueResponse>('/future-enhancements/continuous-learning/signals/queue', data),
    getVisionHistory: (params?: { event_type?: string; camera_id?: string; lookback_hours?: number; limit?: number }) =>
        api.get<VisionAnalyticsHistoryResponse>('/future-enhancements/vision/history', { params }),

    // S27: Category-specific config
    getAugmentationConfig: () =>
        api.get<AugmentationConfigResponse>('/future-enhancements/config/augmentation'),
    updateAugmentationConfig: (data: { techniques: AugmentationTechniqueConfig[]; quality_checks_enabled: boolean; auto_balance_demographics: boolean }) =>
        api.put<AugmentationConfigResponse>('/future-enhancements/config/augmentation', data),

    getModelArchConfig: () =>
        api.get<ModelArchitectureResponse>('/future-enhancements/config/model-architecture'),
    updateModelArchConfig: (data: Record<string, any>) =>
        api.put<ModelArchitectureResponse>('/future-enhancements/config/model-architecture', data),

    getTrainingStrategyConfig: () =>
        api.get<TrainingStrategyResponse>('/future-enhancements/config/training-strategy'),
    updateTrainingStrategyConfig: (data: Record<string, any>) =>
        api.put<TrainingStrategyResponse>('/future-enhancements/config/training-strategy', data),

    getRobustnessConfig: () =>
        api.get<RobustnessConfigResponse>('/future-enhancements/config/robustness'),
    updateRobustnessConfig: (data: Record<string, any>) =>
        api.put<RobustnessConfigResponse>('/future-enhancements/config/robustness', data),

    getAccuracyBoostConfig: () =>
        api.get<AccuracyBoostResponse>('/future-enhancements/config/accuracy-boost'),
    updateAccuracyBoostConfig: (data: Record<string, any>) =>
        api.put<AccuracyBoostResponse>('/future-enhancements/config/accuracy-boost', data),

    getPerformanceConfig: () =>
        api.get<PerformanceConfigResponse>('/future-enhancements/config/performance'),
    updatePerformanceConfig: (data: Record<string, any>) =>
        api.put<PerformanceConfigResponse>('/future-enhancements/config/performance', data),

    // S27: Priority matrix
    getPriorityMatrix: () =>
        api.get<PriorityMatrixResponse>('/future-enhancements/priority-matrix'),

    // S27: Metrics targets
    getMetricsTargets: () =>
        api.get<MetricsTargetsResponse>('/future-enhancements/metrics/targets'),

    updateBehaviorEvent: (eventId: string, data: BehaviorEventUpdateRequest) =>
        api.patch<BehaviorEventItem>(`/future-enhancements/behavior/events/${eventId}`, data),
    updateLearningSignal: (signalId: string, data: ContinuousLearningSignalUpdateRequest) =>
        api.patch<ContinuousLearningSignalItem>(`/future-enhancements/continuous-learning/signals/${signalId}`, data),
    promoteLearningSignal: (signalId: string, data: ContinuousLearningSignalPromoteRequest = {}) =>
        api.post<ContinuousLearningSignalPromoteResponse>(
            `/future-enhancements/continuous-learning/signals/${signalId}/promote`,
            data,
        ),
};

export const threeDFaceService = {
    capture: (data: ThreeDFaceCapturePayload) => api.post<ThreeDFaceResponse>('/3d-face/capture', data),
    compare: (data: ThreeDFaceComparePayload) => api.post<ThreeDFaceCompareResponse>('/3d-face/compare', data),
    liveness: (faceDataId: string) =>
        api.post<ThreeDFaceLivenessResponse>('/3d-face/liveness-check', { face_data_id: faceDataId }),
    match: (data: { face_id_1: string; face_id_2: string }) =>
        api.post('/3d-face/match', data),
    livenessCheck: (data: { face_id: string }) =>
        api.post('/3d-face/liveness-check', data),
};

// ── Phase 3: Multimodal Learning ────────────────────────────────────────────

export const multimodalService = {
    extract: (data: { visitor_id: string; face_image_path?: string; audio_path?: string; text_data?: string }) =>
        api.post('/multimodal/extract', data),
    configureFusion: (data: { face_weight: number; audio_weight: number; text_weight: number; sensor_weight: number; strategy?: string }) =>
        api.post('/multimodal/fusion-config', data),
    compare: (id1: string, id2: string) =>
        api.get(`/multimodal/compare/${id1}/${id2}`),
};

// ── Phase 3: Advanced Liveness ──────────────────────────────────────────────

export const advancedLivenessService = {
    startChallenge: (data: { visitor_log_id: string; challenge_type?: string; timeout_seconds?: number }) =>
        api.post('/liveness-advanced/start-challenge', data),
    verifyChallenge: (data: { challenge_id: string; video_path: string }) =>
        api.post('/liveness-advanced/verify-challenge', data),
    getMethods: () =>
        api.get('/liveness-advanced/methods'),
};

// ── Phase 3: Federated Learning ─────────────────────────────────────────────

export const federatedService = {
    startRound: (data: { model_type?: string; num_participants?: number }) =>
        api.post('/federated/round/start', data),
    submitUpdate: (data: { round_id: string; participant_id: string; local_accuracy: number; num_samples: number }) =>
        api.post('/federated/client/submit-update', data),
    getRoundStatus: (roundId: string) =>
        api.get(`/federated/round/${roundId}/status`),
};

// ── Phase 3: Emotion & Action Recognition ───────────────────────────────────

export const emotionService = {
    detectEmotion: (data: { detection_log_id: string; image_path: string }) =>
        api.post('/emotion-action/detect-emotion', data),
    detectAction: (data: { detection_log_id: string; video_path: string }) =>
        api.post('/emotion-action/detect-action', data),
    getSummary: (visitorId: string, days?: number) =>
        api.get(`/emotion-action/emotions-summary/${visitorId}`, { params: { days: days || 7 } }),
};

// ── Phase 3: Cross-Camera Re-ID ─────────────────────────────────────────────

export const reidService = {
    trackTransition: (data: {
        visitor_id: string; from_camera_id: string; to_camera_id: string;
        from_detection_log_id: string; to_detection_log_id: string;
        transition_time_seconds: number; reid_confidence: number;
    }) => api.post('/reid/track-transition', data),
    getMovementSummary: (visitorId: string) =>
        api.get(`/reid/movement-summary/${visitorId}`),
};

// ── Phase 3: Edge Deployment ────────────────────────────────────────────────

export const edgeDeployService = {
    exportModel: (data: { model_version_id: string; quantization_type?: string; target_device?: string }) =>
        api.post('/edge/export-model', data),
    deploy: (data: { device_id: string; onnx_model_id: string }) =>
        api.post('/edge/deploy', data),
    getDeviceMetrics: (deviceId: string) =>
        api.get(`/edge/device/${deviceId}/metrics`),
};

// ── Phase 3: Advanced Analytics ─────────────────────────────────────────────

export const advancedAnalyticsService = {
    getBehavior: (visitorId: string, date?: string) =>
        api.get(`/advanced-analytics/behavior/${visitorId}`, { params: { date } }),
    getDailyOrgAnalytics: (date?: string) =>
        api.get('/advanced-analytics/organization/daily', { params: { date } }),
};

// ── Phase 3: Vision Transformer ─────────────────────────────────────────────

export const vitService = {
    embedFace: (data: { detection_log_id: string; image_path: string; layer?: number }) =>
        api.post('/vit/embed-face', data),
    visualizeAttention: (data: { embedding_id: string }) =>
        api.post('/vit/visualize-attention', data),
};

// ── Phase 3: Multi-Spectral & Infrared ──────────────────────────────────────

export const multispectralService = {
    captureThermal: (data: { visitor_id: string; thermal_image_path: string; ambient_temp_c: number }) =>
        api.post('/multispectral/capture-thermal', data),
    captureMultispectral: (data: { visitor_id: string; visible_image_path: string; nir_image_path: string; swir_image_path: string; thermal_image_path: string }) =>
        api.post('/multispectral/capture-multispectral', data),
};

// ── Phase 3: Mobile / PWA ───────────────────────────────────────────────────

export const mobileService = {
    registerPush: (data: { device_token: string; device_type?: string }) =>
        api.post('/mobile/register-push', data),
    syncOffline: (data: { detections: any[] }) =>
        api.post('/mobile/sync-offline', data),
};

// ── Phase 3: Integrations ───────────────────────────────────────────────────

export const integrationsApiService = {
    createWebhook: (data: { url: string; event_types: string[]; auth_type?: string; auth_token?: string }) =>
        api.post('/integrations/webhook', data),
    configureVms: (data: { vms_type: string; api_endpoint: string; credentials: Record<string, string> }) =>
        api.post('/integrations/vms-sync', data),
    configureHr: (data: { hr_system: string; api_endpoint: string }) =>
        api.post('/integrations/hr-sync', data),
};

// ── Phase 3: A/B Testing ────────────────────────────────────────────────────

export const abTestingService = {
    startExperiment: (data: { name: string; model_a_id: string; model_b_id: string; traffic_split_percent?: number }) =>
        api.post('/ab-testing/experiment/start', data),
    getResults: (experimentId: string) =>
        api.get(`/ab-testing/experiment/${experimentId}/results`),
};

// ── Phase 3: Security & Compliance ──────────────────────────────────────────

export const securityApiService = {
    configureLdap: (data: { server_url: string; base_dn: string; bind_dn?: string; bind_password?: string }) =>
        api.post('/security/ldap-config', data),
    rotateKeys: () =>
        api.post('/security/encryption/key-rotation'),
    getComplianceStatus: () =>
        api.get('/security/compliance-status'),
    getAuditReport: (params?: { date_start?: string; date_end?: string }) =>
        api.get('/security/audit-report', { params }),
};

export const syntheticDataService = {
    startGeneration: (totalSamples: number) =>
        api.post<SyntheticGenerationJob>('/synthetic-data/generate', undefined, { params: { total_samples: totalSamples } }),
    getJob: (jobId: string) =>
        api.get<SyntheticGenerationJob>(`/synthetic-data/jobs/${jobId}`),
    cancelJob: (jobId: string) =>
        api.post<SyntheticGenerationJob>(`/synthetic-data/jobs/${jobId}/cancel`),
    listMetrics: (params?: { job_id?: string }) =>
        api.get<SyntheticQualityMetrics[]>('/synthetic-data/metrics', { params }),
};

export const temporalAugmentationService = {
    startJob: (inputVideoPath: string) =>
        api.post<TemporalAugmentationJob>('/temporal-augmentation/augment', undefined, { params: { input_video_path: inputVideoPath } }),
    getJob: (jobId: string) =>
        api.get<TemporalAugmentationJob>(`/temporal-augmentation/jobs/${jobId}`),
    cancelJob: (jobId: string) =>
        api.post<TemporalAugmentationJob>(`/temporal-augmentation/jobs/${jobId}/cancel`),
    listMetrics: (params?: { job_id?: string }) =>
        api.get<TemporalExpressionMetrics[]>('/temporal-augmentation/metrics', { params }),
};
export interface DisasterEvent {
    id: string;
    name: string;
    event_type: string;
    affected_areas: string[];
    starts_at: string;
    ends_at?: string | null;
    status: 'planned' | 'active' | 'closed';
    notes?: string | null;
    created_at?: string | null;
}

export interface MissingPersonBulkImportResult {
    imported: number;
    failed: number;
    errors: Array<{ row: number; error: string }>;
}

export const missingPersonService = {
    listDisasterEvents: (status?: DisasterEvent['status']) =>
        api.get<DisasterEvent[]>('/missing-persons/disaster-events', { params: status ? { status } : undefined }),
    createDisasterEvent: (payload: Omit<DisasterEvent, 'id' | 'status' | 'created_at'>) =>
        api.post<DisasterEvent>('/missing-persons/disaster-events', payload),
    importCases: (file: File, disasterEventId?: string) => {
        const body = new FormData();
        body.append('file', file);
        if (disasterEventId) body.append('disaster_event_id', disasterEventId);
        return api.post<MissingPersonBulkImportResult>('/missing-persons/bulk-import', body);
    },
};

export default api;

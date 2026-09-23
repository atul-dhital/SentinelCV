import {
    api,
    postAuthJson,
    AuthTokenResponse,
    AuthServiceResponse,
} from './core';
import {
    clearAccessToken,
    ensureAccessToken,
    getAccessToken,
    hasAccessToken,
    setAccessToken,
} from '@/lib/authSession';
import type { UserInfo, UserSession } from '@/types/user';

export type { UserInfo, UserSession } from '@/types/user';

// Types (re-exported from api.ts elsewhere)
export interface Organization {
    id: string;
    name: string;
    face_confidence_threshold: number;
    log_retention_days: number;
    created_at: string;
    [key: string]: unknown;
}

export interface AuditLog {
    id: string;
    user_id: string;
    action: string;
    entity_type: string;
    entity_id: string;
    timestamp: string;
    [key: string]: unknown;
}

export interface PaginatedResponse<T> {
    items: T[];
    total: number;
    page: number;
    limit: number;
    pages: number;
    next_cursor?: string | null;
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

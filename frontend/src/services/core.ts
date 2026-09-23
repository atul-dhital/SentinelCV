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

const _rawApiUrl = process.env.NEXT_PUBLIC_API_URL;
if (!_rawApiUrl && process.env.NODE_ENV === 'production') {
    throw new Error('NEXT_PUBLIC_API_URL must be set in production. Refusing to fall back to localhost.');
}

export const API_BASE_URL = _rawApiUrl || 'http://localhost:8000/api/v1';

export const realtimeService = {
    dashboardSocketUrl: (_organizationId?: string) => {
        const apiOrigin = API_BASE_URL.replace('/api/v1', '');
        const wsOrigin = apiOrigin.replace('https://', 'wss://').replace('http://', 'ws://');
        const token = getAccessToken();
        const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
        return `${wsOrigin}/api/v1/ws/dashboard${tokenParam}`;
    },
};

export const api = axios.create({
    baseURL: API_BASE_URL,
    withCredentials: true,
});

export type AuthTokenResponse = {
    access_token: string;
    refresh_token?: string;
    token_type: string;
};

export type AuthServiceResponse<T> = {
    data: T;
};

export type AuthRequestError = Error & {
    status?: number;
    response?: {
        status: number;
        data: unknown;
    };
};

export async function parseAuthResponse<T>(response: Response): Promise<T | null> {
    const rawBody = await response.text();
    if (!rawBody) {
        return null;
    }
    return JSON.parse(rawBody) as T;
}

export async function postAuthJson<T>(path: string, body?: Record<string, unknown>): Promise<AuthServiceResponse<T>> {
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

export async function refreshAccessToken(force = false): Promise<string | null> {
    if (!force && hasAccessToken()) {
        return getAccessToken();
    }

    try {
        const res = await postAuthJson<AuthTokenResponse>('/auth/refresh', {});
        setAccessToken(res.data.access_token);
        return res.data.access_token;
    } catch (err: unknown) {
        const e = err as AuthRequestError;
        if (e?.status === 401 || e?.status === 403) {
            clearAccessToken();
            return null;
        }
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

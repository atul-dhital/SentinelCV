export interface UserInfo {
    id: string;
    email: string;
    full_name: string;
    role: string;
    organization_id: string;
    is_active: boolean;
    created_at: string;
}

export interface UserSession {
    jti: string | null;
    ip_address: string | null;
    user_agent: string | null;
    created_at: string | null;
    last_used_at: string | null;
    expires_at: string;
    is_current: boolean;
}

export type UserRole = "admin" | "staff";

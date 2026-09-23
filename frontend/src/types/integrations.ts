export interface WebhookItem {
    id: string
    organization_id: string
    url: string
    events: string[]
    is_active: boolean
    created_at: string
}

export interface ApiKeyItem {
    id: string
    organization_id: string
    name: string
    key_prefix: string
    permissions: string[]
    is_active: boolean
    last_used_at: string | null
    expires_at: string | null
    created_at: string
}

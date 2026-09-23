import type { Camera, VisitorLog } from '@/services/api'

function extractStreamPrefix(faceImagePath?: string | null): string | null {
    if (!faceImagePath) return null

    const normalized = String(faceImagePath).replace(/\\/g, '/').toLowerCase()
    const filename = normalized.split('/').pop() || ''
    const match = filename.match(/^(rt|rtsp)_([a-z0-9]+)/)

    if (!match) return null
    return `${match[1]}_${match[2]}`
}

export function getStreamIdentityKey(log: VisitorLog): string {
    if (log.visitor_id) {
        return `visitor:${log.visitor_id}`
    }

    if (log.identified && log.visitor_name) {
        return `identified-name:${log.visitor_name.trim().toLowerCase()}`
    }

    const streamPrefix = extractStreamPrefix(log.face_image_path)
    if (streamPrefix) {
        return `unknown-stream:${streamPrefix}`
    }

    if (log.camera_id) {
        return `unknown-camera:${log.camera_id}`
    }

    const ts = new Date(log.timestamp).getTime()
    const bucket = Number.isFinite(ts) ? Math.floor(ts / 15000) : 0
    return `unknown-bucket:${bucket}`
}

export function dedupeStreamLogs(logs: VisitorLog[], limit?: number): VisitorLog[] {
    const seen = new Set<string>()
    const deduped: VisitorLog[] = []

    for (const log of logs) {
        const key = getStreamIdentityKey(log)
        if (seen.has(key)) continue

        seen.add(key)
        deduped.push(log)

        if (typeof limit === 'number' && deduped.length >= limit) {
            break
        }
    }

    return deduped
}

/**
 * Where a detection came from, for display.
 *
 * Shared so the dashboard stream and the live-activities feed cannot drift:
 * a browser-webcam log has no camera_id, so keying on that alone renders it
 * as "Unknown source" in one view and "Webcam (browser)" in the other.
 */
export function getSourceLabel(log: VisitorLog, cameras: Camera[]): string {
    if (log.camera_id) {
        const camera = cameras.find((item) => item.id === log.camera_id)
        if (camera) return camera.location ? `${camera.name} - ${camera.location}` : camera.name
        return `Camera ${log.camera_id.slice(0, 8).toUpperCase()}`
    }
    if (log.source_video === 'live_camera') return 'Webcam (browser)'
    if (log.source_video) return `Video: ${log.source_video.split(/[\/]/).pop()}`
    return 'Unknown source'
}

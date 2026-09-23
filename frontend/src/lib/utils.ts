import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { getAccessToken } from '@/lib/authSession';

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export function getStaticMediaUrl(path?: string | null) {
    if (!path) return null;

    const raw = String(path).trim();
    if (!raw) return null;

    if (
        raw.startsWith('http://') ||
        raw.startsWith('https://') ||
        raw.startsWith('blob:') ||
        raw.startsWith('data:')
    ) {
        return raw;
    }

    const normalized = raw.replace(/\\/g, '/');
    const baseUrl = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1')
        .replace(/\/api\/v1\/?$/, '')
        .replace(/\/+$/, '');

    if (normalized.startsWith('/static/')) {
        return appendMediaToken(`${baseUrl}${normalized}`);
    }

    if (normalized.startsWith('static/')) {
        return appendMediaToken(`${baseUrl}/${normalized}`);
    }

    const staticIndex = normalized.toLowerCase().indexOf('/static/');
    if (staticIndex >= 0) {
        return appendMediaToken(`${baseUrl}${normalized.slice(staticIndex)}`);
    }

    const faceImagesIndex = normalized.toLowerCase().indexOf('/face_images/');
    if (faceImagesIndex >= 0) {
        return appendMediaToken(`${baseUrl}/static${normalized.slice(faceImagesIndex)}`);
    }

    return appendMediaToken(`${baseUrl}/static/${normalized.replace(/^\/+/, '')}`);
}

function appendMediaToken(url: string) {
    const token = getAccessToken();
    if (!token) return url;
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}token=${encodeURIComponent(token)}`;
}

export function getStaticMediaCandidates(...paths: Array<string | null | undefined>) {
    const urls: string[] = [];
    const seen = new Set<string>();

    for (const path of paths) {
        const url = getStaticMediaUrl(path);
        if (!url || seen.has(url)) continue;
        seen.add(url);
        urls.push(url);
    }

    return urls;
}

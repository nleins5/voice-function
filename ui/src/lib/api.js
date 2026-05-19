/**
 * Centralized API client for the AI Gateway.
 * 
 * In PRODUCTION (Vercel): The gateway secret is injected server-side by Vercel's
 * route headers. The browser never sees or sends the secret.
 * 
 * In DEVELOPMENT (local): The VITE_GATEWAY_KEY env var is used as a fallback
 * so local dev can still authenticate against a remote or local backend.
 */

export const API_BASE = import.meta.env.VITE_API_BASE || '';
const GATEWAY_KEY = import.meta.env.VITE_GATEWAY_KEY || '';

/**
 * Wrapper around fetch that:
 * 1. Prepends API_BASE to the path
 * 2. In dev mode, injects X-Gateway-Key if VITE_GATEWAY_KEY is set
 * 3. Merges any additional headers from the caller
 */
export async function apiFetch(path, options = {}) {
    const url = `${API_BASE}${path}`;
    const headers = {
        ...(options.headers || {}),
    };

    // Only inject gateway key in dev mode (in production Vercel handles it)
    if (GATEWAY_KEY) {
        headers['X-Gateway-Key'] = GATEWAY_KEY;
    }

    return fetch(url, {
        ...options,
        headers,
    });
}

/**
 * Convenience: JSON POST request with gateway auth.
 */
export async function apiPost(path, body) {
    return apiFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
}

/**
 * Convenience: JSON GET request with gateway auth.
 */
export async function apiGet(path) {
    return apiFetch(path);
}

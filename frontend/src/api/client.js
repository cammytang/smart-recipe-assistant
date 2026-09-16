const base = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, status, retryAfter = 0) {
    super(message)
    this.status = status
    this.retryAfter = retryAfter
  }
}

export async function apiFetch(path, options = {}) {
  const response = await fetch(`${base}${path}`, {
    ...options, credentials: 'include',
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
  })
  if (!response.ok) {
    let data
    try { data = await response.json() } catch { /* Non-JSON service errors. */ }
    const retryAfter = Number(response.headers.get('Retry-After')) || 0
    throw new ApiError(data?.error?.message || `请求失败（${response.status}）`, response.status, retryAfter)
  }
  return response
}

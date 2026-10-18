// Every backend call lives here. Routes and bodies follow contracts/api.md: collections come
// wrapped in objects ({cameras}, {zones}, {alerts, total}) and are unwrapped here, so the rest
// of the app works with plain arrays.
import type { Alert, Camera, CameraStatus, CompileResult, Decision, Rule, Zone } from './types'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${method} ${path} failed (${res.status}) ${detail(text)}`.trim())
  }
  const type = res.headers.get('content-type') ?? ''
  if (!type.includes('application/json')) {
    // e.g. the dev server answering with index.html because the /api proxy isn't active
    throw new Error(`${method} ${path} did not return JSON; is the backend running on :8000?`)
  }
  return res.json() as Promise<T>
}

// FastAPI errors look like {"detail": "..."} or {"detail": [{msg, loc}, ...]}; show the message.
function detail(text: string): string {
  try {
    const d = JSON.parse(text)?.detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) return d.map((e) => e?.msg ?? '').filter(Boolean).join('; ')
  } catch {
    // not JSON
  }
  return text.slice(0, 200)
}

export const api = {
  getCameras: async () => (await request<{ cameras: Camera[] }>('GET', '/api/cameras')).cameras,
  putCameras: async (cameras: Camera[]) => (await request<{ cameras: Camera[] }>('PUT', '/api/cameras', { cameras })).cameras,

  getZones: async () => (await request<{ zones: Zone[] }>('GET', '/api/zones')).zones,
  putZones: async (zones: Zone[]) => (await request<{ zones: Zone[] }>('PUT', '/api/zones', { zones })).zones,

  compilePolicy: (prompt: string) => request<CompileResult>('POST', '/api/policy/compile', { prompt }),
  getPolicy: async () => (await request<{ rules: Rule[] }>('GET', '/api/policy')).rules,
  putPolicy: async (rules: Rule[]) => (await request<{ rules: Rule[] }>('PUT', '/api/policy', { rules })).rules,

  startMonitor: () => request<{ running: boolean }>('POST', '/api/monitor/start'),
  stopMonitor: () => request<{ running: boolean }>('POST', '/api/monitor/stop'),
  getMonitor: () => request<{ running: boolean; cameras: CameraStatus[] }>('GET', '/api/monitor'),

  getAlerts: async (limit = 200) => (await request<{ alerts: Alert[]; total: number }>('GET', `/api/alerts?limit=${limit}`)).alerts,
  decide: (id: string, decision: Decision) =>
    request<Alert>('POST', `/api/alerts/${encodeURIComponent(id)}/decision`, { decision }),
}

export const streamUrl = (cameraId: string) => `/api/stream/${encodeURIComponent(cameraId)}`
export const snapshotUrl = (cameraId: string) => `/api/snapshot/${encodeURIComponent(cameraId)}`

// created_at is an RFC3339 string; the UI's relative times work in unix seconds.
export const createdSeconds = (alert: Alert) => Date.parse(alert.created_at) / 1000

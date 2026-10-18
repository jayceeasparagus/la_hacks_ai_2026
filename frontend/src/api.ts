// Every backend call lives here. Routes follow person3-frontend.md until contracts/api.md lands.
import type { Alert, Camera, CompileResult, Decision, Rule, Zone } from './types'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${method} ${path} failed (${res.status}) ${text}`)
  }
  const type = res.headers.get('content-type') ?? ''
  return (type.includes('application/json') ? res.json() : undefined) as Promise<T>
}

export const api = {
  getCameras: () => request<Camera[]>('GET', '/api/cameras'),
  putCameras: (cameras: Camera[]) => request<Camera[]>('PUT', '/api/cameras', cameras),

  getZones: () => request<Zone[]>('GET', '/api/zones'),
  putZones: (zones: Zone[]) => request<Zone[]>('PUT', '/api/zones', zones),

  compilePolicy: (text: string) => request<CompileResult>('POST', '/api/policy/compile', { text }),
  putPolicy: (text: string, rules: Rule[]) => request<void>('PUT', '/api/policy', { text, rules }),

  startMonitor: () => request<void>('POST', '/api/monitor/start'),
  stopMonitor: () => request<void>('POST', '/api/monitor/stop'),

  getAlerts: () => request<Alert[]>('GET', '/api/alerts'),
  decide: (id: string, decision: Decision) =>
    request<Alert>('POST', `/api/alerts/${encodeURIComponent(id)}/decision`, { decision }),
}

export const streamUrl = (cameraId: string) => `/api/stream/${encodeURIComponent(cameraId)}`
export const snapshotUrl = (cameraId: string) => `/api/snapshot/${encodeURIComponent(cameraId)}`

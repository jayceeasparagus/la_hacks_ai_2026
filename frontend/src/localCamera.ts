// Browser webcam preview for local testing. When the backend is the mock server (it answers
// /api/info with {mock: true}), cameras whose source is "webcam:N" play this device's camera
// directly instead of the mock's placeholder frames. With the real backend, feeds use its
// annotated MJPEG stream and none of this runs.
import { useEffect, useState } from 'react'

let mockCheck: Promise<boolean> | null = null

export function isMockBackend(): Promise<boolean> {
  mockCheck ??= fetch('/api/info')
    .then((r) => (r.ok ? r.json() : null))
    .then((info) => Boolean(info?.mock))
    .catch(() => false)
  return mockCheck
}

const webcamIndex = (source: string): number | null => {
  const m = /^webcam:(\d+)$/.exec(source.trim())
  return m ? Number(m[1]) : null
}

// One getUserMedia call per device, shared by every feed showing it.
const streams = new Map<number, Promise<MediaStream>>()

async function openWebcam(index: number): Promise<MediaStream> {
  let pending = streams.get(index)
  if (!pending) {
    pending = (async () => {
      // labels and ids are only listed after permission, so ask once first
      const first = await navigator.mediaDevices.getUserMedia({ video: { width: 960 }, audio: false })
      const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput')
      const wanted = devices[index]
      const firstId = first.getVideoTracks()[0]?.getSettings().deviceId
      if (!wanted || wanted.deviceId === firstId) return first // missing index falls back to the default camera
      first.getTracks().forEach((t) => t.stop())
      return navigator.mediaDevices.getUserMedia({ video: { deviceId: { exact: wanted.deviceId }, width: 960 }, audio: false })
    })()
    pending.catch(() => streams.delete(index))
    streams.set(index, pending)
  }
  return pending
}

export function useBrowserWebcam(source: string): { stream: MediaStream | null; checked: boolean } {
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    let cancelled = false
    const index = webcamIndex(source)
    isMockBackend().then(async (mock) => {
      if (!mock || index === null || !navigator.mediaDevices) {
        if (!cancelled) setChecked(true)
        return
      }
      try {
        const s = await openWebcam(index)
        if (!cancelled) setStream(s)
      } catch {
        // permission denied or no camera: fall back to the backend stream
      } finally {
        if (!cancelled) setChecked(true)
      }
    })
    return () => {
      cancelled = true
    }
  }, [source])

  return { stream, checked }
}

// Video elements by camera id, so an alert can grab the footage it fired on as evidence.
const videos = new Map<string, HTMLVideoElement>()

// Each registered camera keeps its last few seconds as small JPEG frames, so an alert's
// snippet can start a moment before the detection.
const SNIPPET_FPS = 4
const SNIPPET_BEFORE_S = 3
const SNIPPET_AFTER_S = 1.5
const SNIPPET_WIDTH = 480
const buffers = new Map<string, string[]>()

function grab(v: HTMLVideoElement, width: number, quality: number): string | null {
  if (!v.videoWidth) return null
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = Math.round((v.videoHeight / v.videoWidth) * width)
  canvas.getContext('2d')?.drawImage(v, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', quality)
}

// Returns an unregister function. Only the element that registered can unregister itself, so
// a feed unmounting never cuts off another feed still showing the same camera.
export function registerVideo(cameraId: string, el: HTMLVideoElement): () => void {
  videos.set(cameraId, el)
  const keep = SNIPPET_FPS * SNIPPET_BEFORE_S
  const timer = window.setInterval(() => {
    if (videos.get(cameraId) !== el) return
    const frame = grab(el, SNIPPET_WIDTH, 0.6)
    if (!frame) return
    const buf = buffers.get(cameraId) ?? []
    buf.push(frame)
    if (buf.length > keep) buf.shift()
    buffers.set(cameraId, buf)
  }, 1000 / SNIPPET_FPS)
  return () => {
    window.clearInterval(timer)
    if (videos.get(cameraId) === el) videos.delete(cameraId)
  }
}

// The few seconds around an alert: the buffered frames before it plus a moment after.
// Resolves to [] when this camera isn't playing in this browser (e.g. the real backend's stream).
export function captureSnippet(cameraId: string): Promise<string[]> {
  const v = videos.get(cameraId)
  if (!v) return Promise.resolve([])
  const before = [...(buffers.get(cameraId) ?? [])]
  return new Promise((resolve) => {
    const after: string[] = []
    const t = window.setInterval(() => {
      const frame = grab(v, SNIPPET_WIDTH, 0.6)
      if (frame) after.push(frame)
      if (after.length >= SNIPPET_FPS * SNIPPET_AFTER_S) {
        window.clearInterval(t)
        resolve([...before, ...after])
      }
    }, 1000 / SNIPPET_FPS)
  })
}

export const snippetFps = SNIPPET_FPS
export const snippetAfterFrames = SNIPPET_FPS * SNIPPET_AFTER_S

export function captureFrame(cameraId: string): string | null {
  const v = videos.get(cameraId)
  return v ? grab(v, v.videoWidth, 0.8) : null
}

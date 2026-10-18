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

// Video elements by camera id, so an alert can grab the frame it fired on as evidence.
const videos = new Map<string, HTMLVideoElement>()

export function registerVideo(cameraId: string, el: HTMLVideoElement | null) {
  if (el) videos.set(cameraId, el)
  else videos.delete(cameraId)
}

export function captureFrame(cameraId: string): string | null {
  const v = videos.get(cameraId)
  if (!v || !v.videoWidth) return null
  const canvas = document.createElement('canvas')
  canvas.width = v.videoWidth
  canvas.height = v.videoHeight
  canvas.getContext('2d')?.drawImage(v, 0, 0)
  return canvas.toDataURL('image/jpeg', 0.8)
}

// The picture inside every monitor: this browser's webcam when testing against the mock,
// otherwise the backend's MJPEG stream (an <img> renders MJPEG natively). The stream only
// exists while monitoring (503 otherwise), so until then this shows the camera's snapshot,
// refreshed every few seconds; only if the snapshot fails too is the camera reported lost.
import { useEffect, useRef, useState } from 'react'
import { snapshotUrl, streamUrl } from '../api'
import { registerVideo, useBrowserWebcam } from '../localCamera'
import type { Camera } from '../types'

interface Props {
  camera: Camera
  attempt?: number
  dimmed?: boolean
  onError?: () => void
}

const SNAPSHOT_REFRESH_MS = 3000

export default function LiveVideo({ camera, attempt = 0, dimmed, onError }: Props) {
  const { stream, checked } = useBrowserWebcam(camera.source)
  const videoRef = useRef<HTMLVideoElement>(null)
  const [still, setStill] = useState(false) // the stream failed: show snapshots instead
  const [frame, setFrame] = useState(0)

  useEffect(() => {
    const el = videoRef.current
    if (!el || !stream) return
    el.srcObject = stream
    return registerVideo(camera.id, el)
  }, [stream, camera.id])

  // a retry from the parent (e.g. after monitoring starts) tries the live stream again
  useEffect(() => setStill(false), [attempt, camera.id])

  useEffect(() => {
    if (!still) return
    const t = window.setInterval(() => setFrame((n) => n + 1), SNAPSHOT_REFRESH_MS)
    return () => window.clearInterval(t)
  }, [still])

  const cls = `h-full w-full object-cover transition-opacity duration-700 ${dimmed ? 'opacity-30' : 'opacity-100'}`

  if (!checked) return null
  if (stream) return <video ref={videoRef} autoPlay muted playsInline className={cls} />
  if (still) {
    return (
      <img
        src={`${snapshotUrl(camera.id)}?f=${frame}`}
        alt={`${camera.name} snapshot`}
        onError={onError}
        className={cls}
      />
    )
  }
  return (
    <img
      key={attempt}
      src={`${streamUrl(camera.id)}?a=${attempt}`}
      alt={`${camera.name} live feed`}
      onError={() => setStill(true)}
      className={cls}
    />
  )
}

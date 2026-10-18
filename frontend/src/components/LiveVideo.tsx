// The picture inside every monitor: this browser's webcam when testing against the mock,
// otherwise the backend's MJPEG stream (an <img> renders MJPEG natively).
import { useEffect, useRef } from 'react'
import { streamUrl } from '../api'
import { registerVideo, useBrowserWebcam } from '../localCamera'
import type { Camera } from '../types'

interface Props {
  camera: Camera
  attempt?: number
  dimmed?: boolean
  onError?: () => void
}

export default function LiveVideo({ camera, attempt = 0, dimmed, onError }: Props) {
  const { stream, checked } = useBrowserWebcam(camera.source)
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    const el = videoRef.current
    if (!el || !stream) return
    el.srcObject = stream
    return registerVideo(camera.id, el)
  }, [stream, camera.id])

  const cls = `h-full w-full object-cover transition-opacity duration-700 ${dimmed ? 'opacity-30' : 'opacity-100'}`

  if (!checked) return null
  if (stream) return <video ref={videoRef} autoPlay muted playsInline className={cls} />
  return (
    <img
      key={attempt}
      src={`${streamUrl(camera.id)}?a=${attempt}`}
      alt={`${camera.name} live feed`}
      onError={onError}
      className={cls}
    />
  )
}

// Draw and name zones on one camera's snapshot. Drag to draw a rectangle, or click to add
// polygon points and click the first point to close the shape. Coords are saved normalized.
import { useEffect, useRef, useState } from 'react'
import type { Camera, Zone } from '../types'
import LiveVideo from './LiveVideo'

type Pt = [number, number]

interface Props {
  camera: Camera
  zones: Zone[] // this camera's zones
  onSave: (zones: Zone[]) => void
  onClose: () => void
}

const CLOSE_DIST = 0.025
const DRAG_DIST = 0.015

const slug = (s: string) => s.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'zone'

export default function ZoneEditor({ camera, zones: initial, onSave, onClose }: Props) {
  const [zones, setZones] = useState<Zone[]>(initial)
  const [draft, setDraft] = useState<Pt[]>([])
  const [drag, setDrag] = useState<{ start: Pt; end: Pt } | null>(null)
  const [hover, setHover] = useState<Pt | null>(null)
  const surface = useRef<SVGSVGElement>(null)
  const down = useRef<Pt | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') draft.length ? setDraft([]) : onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [draft.length, onClose])

  const toPoint = (e: React.PointerEvent): Pt => {
    const box = surface.current!.getBoundingClientRect()
    const x = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width))
    const y = Math.min(1, Math.max(0, (e.clientY - box.top) / box.height))
    return [x, y]
  }

  const addZone = (polygon: Pt[]) => {
    const taken = new Set(zones.map((z) => z.id))
    let n = zones.length + 1
    while (taken.has(`${camera.id}_zone_${n}`)) n++
    setZones([...zones, { id: `${camera.id}_zone_${n}`, name: `Zone ${n}`, camera_id: camera.id, polygon }])
  }

  const onPointerDown = (e: React.PointerEvent) => {
    down.current = toPoint(e)
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    const p = toPoint(e)
    setHover(p)
    const start = down.current
    if (start && draft.length === 0 && Math.hypot(p[0] - start[0], p[1] - start[1]) > DRAG_DIST) {
      setDrag({ start, end: p })
    }
  }

  const onPointerUp = (e: React.PointerEvent) => {
    const p = toPoint(e)
    const start = down.current
    down.current = null
    if (drag && start) {
      const [x1, y1] = [Math.min(start[0], p[0]), Math.min(start[1], p[1])]
      const [x2, y2] = [Math.max(start[0], p[0]), Math.max(start[1], p[1])]
      setDrag(null)
      addZone([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
      return
    }
    if (draft.length >= 3 && Math.hypot(p[0] - draft[0][0], p[1] - draft[0][1]) < CLOSE_DIST) {
      addZone(draft)
      setDraft([])
      return
    }
    setDraft([...draft, p])
  }

  const rename = (id: string, name: string) => setZones(zones.map((z) => (z.id === id ? { ...z, name } : z)))

  const save = () => {
    // ids follow the names so rules compiled from text ("emergency exit") can find them
    const used = new Set<string>()
    const named = zones.map((z) => {
      let id = slug(z.name)
      while (used.has(id)) id = `${id}_2`
      used.add(id)
      return { ...z, id }
    })
    onSave(named)
  }

  const pts = (poly: Pt[]) => poly.map(([x, y]) => `${x},${y}`).join(' ')

  return (
    <div className="toast-in fixed inset-0 z-50 flex items-center justify-center bg-black p-10" onClick={onClose}>
      <div className="flex w-full max-w-[1280px] gap-8" onClick={(e) => e.stopPropagation()}>
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="flex items-baseline justify-between">
            <span className="font-display text-[22px] font-medium tracking-[-0.02em] text-text">Zones on {camera.name}</span>
            <span className="text-[14px] text-muted">Drag for a rectangle, or click points and close on the first one. Esc cancels.</span>
          </div>
          <div className="relative aspect-video overflow-hidden rounded-md bg-panel">
            <LiveVideo camera={camera} />
            <svg
              ref={surface}
              className="absolute inset-0 h-full w-full cursor-crosshair touch-none"
              viewBox="0 0 1 1"
              preserveAspectRatio="none"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerLeave={() => setHover(null)}
            >
              {zones.map((z) => (
                <polygon key={z.id} points={pts(z.polygon)} fill="rgba(45, 79, 150,0.12)" stroke="#F1EEE6" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
              ))}
              {drag && (
                <rect
                  x={Math.min(drag.start[0], drag.end[0])}
                  y={Math.min(drag.start[1], drag.end[1])}
                  width={Math.abs(drag.end[0] - drag.start[0])}
                  height={Math.abs(drag.end[1] - drag.start[1])}
                  fill="rgba(45, 79, 150,0.12)"
                  stroke="#2D4F96"
                  strokeWidth={1.5}
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {draft.length > 0 && (
                <polyline
                  points={pts(hover ? [...draft, hover] : draft)}
                  fill="none"
                  stroke="#2D4F96"
                  strokeWidth={1.5}
                  strokeDasharray="6 5"
                  vectorEffect="non-scaling-stroke"
                />
              )}
            </svg>
            {/* points drawn in px so they stay round on a stretched viewBox */}
            {draft.map(([x, y], i) => (
              <div
                key={i}
                className={`pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-full ${i === 0 ? 'h-3.5 w-3.5 border-2 border-accent bg-black' : 'h-2 w-2 bg-accent'}`}
                style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
              />
            ))}
            {zones.map((z) => (
              <span
                key={z.id}
                className="pointer-events-none absolute text-[13px] font-medium text-text"
                style={{ left: `${z.polygon[0][0] * 100}%`, top: `calc(${z.polygon[0][1] * 100}% - 18px)` }}
              >
                {z.name}
              </span>
            ))}
          </div>
        </div>

        <aside className="flex w-[300px] shrink-0 flex-col gap-4 pt-7">
          {zones.length === 0 && <p className="text-[15px] text-muted">No zones yet. Draw one on the frame.</p>}
          {zones.map((z) => (
            <div key={z.id} className="flex items-center gap-2">
              <input className="field flex-1" value={z.name} onChange={(e) => rename(z.id, e.target.value)} aria-label="Zone name" />
              <button className="btn-quiet px-3" onClick={() => setZones(zones.filter((x) => x.id !== z.id))} aria-label={`Delete ${z.name}`}>
                Delete
              </button>
            </div>
          ))}
          <div className="mt-auto flex gap-2">
            <button className="btn-quiet flex-1" onClick={onClose}>Cancel</button>
            <button className="btn-primary flex-1 justify-center py-2.5 text-[15px]" onClick={save}>Save zones</button>
          </div>
        </aside>
      </div>
    </div>
  )
}

// The blue circle drawn around whatever a rule is watching, with a short note beside it.
// bbox is normalized [x1, y1, x2, y2]. The circle draws itself in, then the note fades up.
import { useLayoutEffect, useRef, useState } from 'react'

interface Props {
  bbox: [number, number, number, number]
  title: string
  detail?: string
  small?: boolean
}

// a loose hand-drawn loop in a 100x100 box; it overshoots its start like a real pen stroke
const LOOP = [
  [28, 92], [6, 78], [2, 30], [40, 10], [72, -4], [102, 22], [97, 58], [93, 88], [60, 100], [36, 95], [26, 93], [20, 88], [18, 82],
]

export default function Marker({ bbox, title, detail, small }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const [x1, y1, x2, y2] = bbox
  const pad = 0.035
  const left = Math.max(0, x1 - pad)
  const top = Math.max(0, y1 - pad * 1.6)
  const width = Math.min(1, x2 + pad) - left
  const height = Math.min(1, y2 + pad * 1.6) - top
  // keep the note inside the frame: put it on whichever side has more room
  const noteOnLeft = x2 > (small ? 0.5 : 0.7)

  const bx = left * size.w
  const by = top * size.h
  const bw = width * size.w
  const bh = height * size.h
  const p = LOOP.map(([x, y]) => [bx + (x / 100) * bw, by + (y / 100) * bh])
  const d =
    `M${p[0][0]} ${p[0][1]} ` +
    [1, 4, 7, 10].map((i) => `C${p[i][0]} ${p[i][1]} ${p[i + 1][0]} ${p[i + 1][1]} ${p[i + 2][0]} ${p[i + 2][1]}`).join(' ')

  return (
    <div ref={ref} className="pointer-events-none absolute inset-0">
      {size.w > 0 && (
        <svg className="absolute inset-0 overflow-visible" width={size.w} height={size.h}>
          <path className="marker-draw" pathLength={1} d={d} fill="none" stroke="#8FB2FF" strokeWidth={small ? 2.5 : 3.5} strokeLinecap="round" />
        </svg>
      )}
      <div
        className="marker-note absolute flex -rotate-3 flex-col"
        style={
          noteOnLeft
            ? { right: `${(1 - left) * 100 + 1}%`, top: `${top * 100 - 4}%`, alignItems: 'flex-end' }
            : { left: `${(left + width) * 100 + 1}%`, top: `${top * 100 - 4}%` }
        }
      >
        <span
          className={`whitespace-nowrap font-semibold italic tracking-[-0.01em] text-accent ${small ? 'text-[15px] leading-5' : 'text-[22px] leading-7'}`}
        >
          {title}
        </span>
        {detail && (
          <span className={`whitespace-nowrap italic text-accent ${small ? 'text-[13px] leading-4' : 'text-[17px] leading-6'}`}>
            {detail}
          </span>
        )}
      </div>
    </div>
  )
}

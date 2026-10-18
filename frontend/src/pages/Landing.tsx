// Landing: the name, one line, and a wall of monitors. The monitors power on one by one;
// move the cursor over the wall and a lens glides after it, and whichever monitor it rests
// on circles what that camera has noticed.
import { useEffect, useRef, useState } from 'react'
import type { Page } from '../App'
import Marker from '../components/Marker'
import Stars from '../components/Stars'
import Wordmark from '../components/Wordmark'
import { clock } from '../format'

interface WallFeed {
  id: string
  name: string
  light: string // where the stand-in footage is brightest
  bbox: [number, number, number, number]
  title: string
  detail: string
}

const WALL: WallFeed[] = [
  { id: 'cam_entrance', name: 'Main entrance', light: '52% 40%', bbox: [0.44, 0.4, 0.58, 0.66], title: 'bag, probably opaque', detail: 'sent for review' },
  { id: 'cam_exit', name: 'Emergency exit', light: '46% 44%', bbox: [0.26, 0.56, 0.4, 0.84], title: 'bag blocking the exit', detail: '5.4 s, flagged' },
  { id: 'cam_lobby', name: 'Lobby', light: '38% 50%', bbox: [0.2, 0.46, 0.34, 0.72], title: 'clear bag', detail: 'all good' },
  { id: 'cam_dock', name: 'Loading dock', light: '60% 46%', bbox: [0.56, 0.5, 0.72, 0.8], title: 'chair by the door', detail: '2.1 s, watching' },
]

const BOOT_MS = 350 // first monitor powers on after the headline settles
const BOOT_STEP_MS = 160

export default function Landing({ go }: { go: (p: Page) => void }) {
  const wallRef = useRef<HTMLDivElement>(null)
  const lensRef = useRef<HTMLDivElement>(null)
  const starsRef = useRef<HTMLDivElement>(null)
  const target = useRef<{ x: number; y: number } | null>(null)
  const [lensOn, setLensOn] = useState(false)
  const [focused, setFocused] = useState(1) // exit monitor until the cursor moves
  const [booted, setBooted] = useState(false)
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000)
    const b = window.setTimeout(() => setBooted(true), BOOT_MS + BOOT_STEP_MS * WALL.length + 500)
    return () => {
      window.clearInterval(t)
      window.clearTimeout(b)
    }
  }, [])

  // the lens eases toward the cursor instead of snapping, so it feels like a physical glass
  useEffect(() => {
    let raf = 0
    const pos = { x: 0, y: 0 }
    let seeded = false
    const loop = () => {
      const t = target.current
      const el = lensRef.current
      if (!t) seeded = false
      if (t && el) {
        if (!seeded) {
          // start where the cursor entered, not from the corner
          pos.x = t.x
          pos.y = t.y
          seeded = true
        }
        pos.x += (t.x - pos.x) * 0.18
        pos.y += (t.y - pos.y) * 0.18
        el.style.transform = `translate(${pos.x}px, ${pos.y}px) translate(-50%, -50%)`
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])

  // stars drift a few pixels against the mouse for a little depth
  const onPageMove = (e: React.PointerEvent) => {
    const dx = (e.clientX / window.innerWidth - 0.5) * -14
    const dy = (e.clientY / window.innerHeight - 0.5) * -10
    if (starsRef.current) starsRef.current.style.transform = `translate(${dx}px, ${dy}px)`
  }

  const onWallMove = (e: React.PointerEvent) => {
    const box = wallRef.current!.getBoundingClientRect()
    const x = e.clientX - box.left
    const y = e.clientY - box.top
    target.current = { x, y }
    setLensOn(true)
    const col = x < box.width / 2 ? 0 : 1
    const row = y < box.height / 2 ? 0 : 1
    setFocused(row * 2 + col)
  }

  return (
    <div className="relative min-h-full overflow-hidden bg-ink" onPointerMove={onPageMove}>
      <div ref={starsRef} className="absolute -inset-4 transition-transform duration-700 ease-out">
        <Stars />
      </div>

      <header className="rise relative z-10 flex items-center justify-between px-16 py-8">
        <Wordmark size={24} />
        <nav className="flex items-center gap-10 text-[17px] text-muted">
          <a href="#how" className="transition hover:text-text">how it works</a>
          <a href="https://github.com" className="transition hover:text-text">github</a>
          <button onClick={() => go('setup')} className="text-text">get started</button>
        </nav>
      </header>

      <main className="relative z-10 grid min-h-[calc(100vh-96px)] grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] items-center gap-16 px-16 pb-16">
        <section className="flex flex-col gap-8">
          <span className="label rise" style={{ '--d': '60ms' } as React.CSSProperties}>
            Policy-aware camera monitoring
          </span>
          <h1
            className="rise text-[clamp(84px,9vw,140px)] font-semibold leading-[0.92] tracking-[-0.055em]"
            style={{ '--d': '120ms' } as React.CSSProperties}
          >
            <span className="text-text">policy</span>
            <span className="text-accent">lens</span>
          </h1>
          <p
            className="rise max-w-[560px] text-balance text-[24px] leading-[36px] text-[#C9C6BF]"
            style={{ '--d': '220ms' } as React.CSSProperties}
          >
            Tell any camera what matters, in a sentence. It watches. You decide.
          </p>
          <div className="rise" style={{ '--d': '320ms' } as React.CSSProperties}>
            <button className="btn-primary group" onClick={() => go('setup')}>
              get started
              <span className="transition-transform duration-300 group-hover:translate-x-1">
                <Arrow />
              </span>
            </button>
          </div>
        </section>

        <section
          ref={wallRef}
          onPointerMove={onWallMove}
          onPointerLeave={() => {
            target.current = null
            setLensOn(false)
          }}
          className="relative grid cursor-none grid-cols-2 gap-2"
        >
          {WALL.map((feed, i) => (
            <div
              key={feed.id}
              className="power-on relative aspect-video overflow-hidden rounded-[3px] bg-panel"
              style={{ '--d': `${BOOT_MS + i * BOOT_STEP_MS}ms` } as React.CSSProperties}
            >
              <div
                className={`absolute inset-0 transition-[filter] duration-500 ${focused === i ? 'brightness-110' : 'brightness-75'}`}
                style={{ background: `radial-gradient(ellipse 75% 80% at ${feed.light}, #4a4a49 0%, #232322 58%, #101010 100%)` }}
              />
              <div className="grain absolute inset-0" />
              <div className="absolute inset-x-0 top-0 flex justify-between px-3 py-2">
                <span className="label text-[10px] text-text">CAM {String(i + 1).padStart(2, '0')}</span>
                <span className="label text-[10px] text-text/70">LIVE · {clock(now)}</span>
              </div>
              <span className="absolute bottom-2 left-3 text-[14px] font-medium text-text">{feed.name}</span>
              {booted && focused === i && (
                <Marker key={`${i}-${focused}`} bbox={feed.bbox} title={feed.title} detail={feed.detail} small />
              )}
            </div>
          ))}

          <div
            ref={lensRef}
            className={`pointer-events-none absolute left-0 top-0 h-48 w-48 rounded-full border-[1.5px] border-[#F1EEE6] bg-accent/[0.06] transition-opacity duration-300 ${lensOn ? 'opacity-100' : 'opacity-0'}`}
          />
        </section>
      </main>
    </div>
  )
}

export function Arrow() {
  return (
    <svg width="22" height="14" viewBox="0 0 22 14" aria-hidden="true">
      <path d="M1 7 H20 M14 1.5 L20.5 7 L14 12.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

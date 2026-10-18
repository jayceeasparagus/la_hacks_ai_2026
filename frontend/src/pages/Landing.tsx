// Landing: the name, one line, and a loose cluster of monitors. The monitors power on one by
// one and drift slightly; a lens glides after the cursor, and whichever monitor it rests on
// circles what that camera has noticed. Below, "how it works" plays a three-step walkthrough
// when it scrolls into view.
import { useEffect, useRef, useState } from 'react'
import type { Page } from '../App'
import Marker from '../components/Marker'
import Stars from '../components/Stars'
import Wordmark from '../components/Wordmark'
import { clock } from '../format'
import { DEMO_POLICY } from '../rules'
import { useInView } from '../useInView'

export const REPO_URL = 'https://github.com/jayceeasparagus/la_hacks_ai_2026'

interface WallFeed {
  id: string
  name: string
  video: string // stock clip under public/footage, shown in CCTV black and white
  bbox: [number, number, number, number]
  title: string
  detail: string
  depth: number // scales the parallax as the cursor moves
}

// A 2x2 wall of monitors, like the bank of screens in a security office.
const WALL: WallFeed[] = [
  { id: 'cam_exit', name: 'Emergency exit', video: '/footage/exit.mp4', bbox: [0.3, 0.56, 0.44, 0.84], title: 'Bag blocking the exit', detail: '5.4 s, flagged', depth: 1 },
  { id: 'cam_lobby', name: 'Lobby', video: '/footage/lobby.mp4', bbox: [0.5, 0.36, 0.64, 0.66], title: 'Clear bag', detail: 'All good', depth: 0.8 },
  { id: 'cam_entrance', name: 'Main entrance', video: '/footage/entrance.mp4', bbox: [0.12, 0.48, 0.26, 0.76], title: 'Bag, probably opaque', detail: 'Sent for review', depth: 0.9 },
  { id: 'cam_dock', name: 'Loading dock', video: '/footage/dock.mp4', bbox: [0.5, 0.42, 0.66, 0.74], title: 'Chair by the door', detail: '2.1 s, watching', depth: 0.7 },
]

const BOOT_MS = 350
const BOOT_STEP_MS = 160

export default function Landing({ go }: { go: (p: Page) => void }) {
  const clusterRef = useRef<HTMLDivElement>(null)
  const tileRefs = useRef<(HTMLDivElement | null)[]>([])
  const lensRef = useRef<HTMLDivElement>(null)
  const starsRef = useRef<HTMLDivElement>(null)
  const target = useRef<{ x: number; y: number } | null>(null)
  const [lensOn, setLensOn] = useState(false)
  const [lensSize, setLensSize] = useState(176) // px, follows the size of the monitor underneath
  const [focused, setFocused] = useState(0) // exit monitor until the cursor moves
  const [booted, setBooted] = useState(false)
  const [tilt, setTilt] = useState({ x: 0, y: 0 }) // -1..1 from the cursor position
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
    let seeded = false
    const pos = { x: 0, y: 0 }
    const loop = () => {
      const t = target.current
      const el = lensRef.current
      if (!t) seeded = false
      if (t && el) {
        if (!seeded) {
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

  const onPageMove = (e: React.PointerEvent) => {
    const x = (e.clientX / window.innerWidth - 0.5) * 2
    const y = (e.clientY / window.innerHeight - 0.5) * 2
    setTilt({ x, y })
    if (starsRef.current) starsRef.current.style.transform = `translate(${x * -7}px, ${y * -5}px)`
  }

  // the lens only shows while the cursor is over a monitor, never in the gaps between them
  const onClusterMove = (e: React.PointerEvent) => {
    const box = clusterRef.current!.getBoundingClientRect()
    const hit = WALL.map((_, i) => i).find((i) => {
      const r = tileRefs.current[i]?.getBoundingClientRect()
      return r && e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom
    })
    if (hit === undefined) {
      target.current = null
      setLensOn(false)
      return
    }
    target.current = { x: e.clientX - box.left, y: e.clientY - box.top }
    const r = tileRefs.current[hit]!.getBoundingClientRect()
    setLensSize(Math.round(r.height * 0.62))
    setLensOn(true)
    setFocused(hit)
  }

  return (
    <div className="relative min-h-full overflow-x-hidden bg-ink" onPointerMove={onPageMove}>
      <div ref={starsRef} className="pointer-events-none fixed -inset-4 transition-transform duration-700 ease-out">
        <Stars />
      </div>

      <header className="rise relative z-40 flex items-center justify-between px-16 py-8">
        <Wordmark size={24} />
        <nav className="flex items-center gap-10 text-[17px] text-muted">
          <a href="#how" className="transition hover:text-text">How it works</a>
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="transition hover:text-text">GitHub</a>
          <button onClick={() => go('setup')} className="text-text">Get started</button>
        </nav>
      </header>

      <main className="relative z-10 grid min-h-[calc(100vh-96px)] grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)] items-center gap-14 pb-10 pl-16 pr-16">
        <section className="relative z-20 flex flex-col gap-10">
          <h1
            className="rise font-display text-[clamp(76px,9vw,136px)] font-semibold leading-[0.95] tracking-[-0.035em]"
            style={{ '--d': '80ms' } as React.CSSProperties}
          >
            <span className="text-text">Watch</span>
            <span className="text-accent">Dog</span>
          </h1>
          <p
            className="rise max-w-[600px] text-balance text-[30px] leading-[42px] text-[#C9C6BF]"
            style={{ '--d': '200ms' } as React.CSSProperties}
          >
            Tell any camera what matters, in a sentence. It watches. You decide.
          </p>
          <div className="rise flex items-center gap-8" style={{ '--d': '300ms' } as React.CSSProperties}>
            <button className="btn-primary group px-8 py-4 text-[19px]" onClick={() => go('setup')}>
              Get started
              <span className="transition-transform duration-300 group-hover:translate-x-1">
                <Arrow />
              </span>
            </button>
            <a href="#how" className="text-[19px] text-muted transition hover:text-text">
              See how it works
            </a>
          </div>
        </section>

        <section
          ref={clusterRef}
          onPointerMove={onClusterMove}
          onPointerLeave={() => {
            target.current = null
            setLensOn(false)
          }}
          className="relative z-10 grid w-full grid-cols-2 gap-3"
        >
          {WALL.map((feed, i) => (
            <div
              key={feed.id}
              ref={(el) => (tileRefs.current[i] = el)}
              className="relative cursor-none transition-transform duration-700 ease-out"
              style={{ transform: `translate(${tilt.x * feed.depth * -6}px, ${tilt.y * feed.depth * -4}px)` }}
            >
              <div
                className="float"
                style={{ '--float-t': `${7 + i * 1.3}s`, '--float-d': `${-i * 1.7}s` } as React.CSSProperties}
              >
                <div
                  className={`power-on relative aspect-video overflow-hidden rounded-xl bg-panel ring-1 ring-black transition-[filter] duration-500 ${focused === i ? 'brightness-110' : 'brightness-[0.7]'}`}
                  style={{ '--d': `${BOOT_MS + i * BOOT_STEP_MS}ms` } as React.CSSProperties}
                >
                  <Footage src={feed.video} offset={i * 1.7} />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/10 to-black/45" />
                  <div className="grain absolute inset-0" />
                  <span className="absolute left-3 top-2 font-mono text-[10px] tracking-label text-text/70">
                    CAM {String(i + 1).padStart(2, '0')}
                  </span>
                  <span className="absolute right-3 top-2 font-mono text-[10px] tracking-label text-text/70">{clock(now)}</span>
                  <span className="absolute bottom-2 left-3 text-[14px] font-medium text-text">{feed.name}</span>
                  {booted && focused === i && (
                    <Marker key={`${i}-${focused}`} bbox={feed.bbox} title={feed.title} detail={feed.detail} small />
                  )}
                </div>
              </div>
            </div>
          ))}

          <div
            ref={lensRef}
            className="pointer-events-none absolute left-0 top-0 z-40"
          >
            <div
              className={`rounded-full border-[1.5px] border-[#F1EEE6] bg-accent/[0.05] transition-all duration-300 ease-out ${lensOn ? 'scale-100 opacity-100' : 'scale-75 opacity-0'}`}
              style={{ width: lensSize, height: lensSize }}
            />
          </div>
        </section>
      </main>

      <HowItWorks />

      <footer className="relative z-10 flex items-center justify-between px-16 pb-12 pt-6 text-[15px] text-muted">
        <Wordmark size={18} />
        <span>Built at LA Hacks 2026</span>
        <a href={REPO_URL} target="_blank" rel="noreferrer" className="transition hover:text-text">
          github.com/jayceeasparagus/la_hacks_ai_2026
        </a>
      </footer>
    </div>
  )
}

const STEP_RULES = [
  { name: 'Bags should be clear', where: 'Main entrance', when: 'review' },
  { name: 'Pro cameras get a look', where: 'Main entrance', when: 'review' },
  { name: 'Keep the exit clear', where: 'Emergency exit · after 5 s', when: 'urgent' },
]

// The three steps play in order: the policy types itself, the rules appear, the camera circles a bag.
function HowItWorks() {
  const [ref, inView] = useInView<HTMLElement>(0.3)
  const [typed, setTyped] = useState(0)
  const done = typed >= DEMO_POLICY.length

  useEffect(() => {
    if (!inView || done) return
    const t = window.setTimeout(() => setTyped((n) => Math.min(DEMO_POLICY.length, n + 3)), 22)
    return () => window.clearTimeout(t)
  }, [inView, typed, done])

  const [stage, setStage] = useState(0) // 1: rules shown, 2: camera flags the bag
  useEffect(() => {
    if (!done) return
    const a = window.setTimeout(() => setStage(1), 250)
    const b = window.setTimeout(() => setStage(2), 1300)
    return () => {
      window.clearTimeout(a)
      window.clearTimeout(b)
    }
  }, [done])

  return (
    <section id="how" ref={ref} className="relative z-10 px-16 pb-28 pt-24">
      <div className="mb-16 flex items-end justify-between gap-10">
        <h2 className="font-display text-[48px] font-semibold leading-none tracking-[-0.04em]">How it works</h2>
        <p className="max-w-[420px] text-right text-[16px] leading-6 text-muted">
          It never identifies people and never acts on its own. Every alert waits for a person to decide.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-14">
        <Step n={1} title="Write the rules down" body="Plain English, the way you'd brief someone on their first shift.">
          <p className="min-h-[168px] text-[17px] leading-[28px] text-text">
            {DEMO_POLICY.slice(0, typed)}
            {inView && <span className="caret" />}
          </p>
        </Step>

        <Step n={2} title="They become rules you can check" body="Each one names a zone, a timing and how urgent it is. Nothing runs until you say so.">
          <ul className="flex min-h-[168px] flex-col">
            {STEP_RULES.map((r, i) =>
              stage >= 1 ? (
                <li
                  key={r.name}
                  className="rise flex items-baseline justify-between gap-4 border-b border-line py-3"
                  style={{ '--d': `${i * 140}ms` } as React.CSSProperties}
                >
                  <span className="flex flex-col">
                    <span className="text-[16px] text-text">{r.name}</span>
                    <span className="text-[13px] text-muted">{r.where}</span>
                  </span>
                  <span className={`text-[13px] capitalize ${r.when === 'urgent' ? 'text-accent-soft' : 'text-muted'}`}>{r.when}</span>
                </li>
              ) : null,
            )}
          </ul>
        </Step>

        <Step n={3} title="It watches. You decide." body="Only what breaks a rule reaches you, with the clip that shows it.">
          <div className="relative aspect-video overflow-hidden rounded-[4px] bg-panel">
            <Footage src="/footage/exit.mp4" />
            <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/10 to-black/40" />
            <div className="grain absolute inset-0" />
            <span className="absolute left-3 top-2 font-mono text-[10px] tracking-label text-text">CAM 02</span>
            {stage >= 2 && <Marker bbox={[0.3, 0.55, 0.44, 0.85]} title="Bag blocking the exit" detail="5.4 s, flagged" small />}
          </div>
        </Step>
      </div>
    </section>
  )
}

function Step({ n, title, body, children }: { n: number; title: string; body: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <span className="font-display text-[15px] font-medium text-accent-soft">{n}</span>
        <h3 className="font-display text-[22px] font-medium tracking-[-0.02em] text-text">{title}</h3>
        <p className="text-[15px] leading-[22px] text-muted">{body}</p>
      </div>
      {children}
    </div>
  )
}

// A looping stock clip styled like a security feed. offset starts each one at a different
// point so the wall doesn't loop in sync.
function Footage({ src, offset = 0 }: { src: string; offset?: number }) {
  return (
    <video
      src={src}
      autoPlay
      muted
      loop
      playsInline
      preload="auto"
      onLoadedMetadata={(e) => {
        const v = e.currentTarget
        if (v.duration) v.currentTime = offset % v.duration
      }}
      className="absolute inset-0 h-full w-full object-cover [filter:grayscale(1)_contrast(1.1)_brightness(0.7)]"
    />
  )
}

export function Arrow() {
  return (
    <svg width="22" height="14" viewBox="0 0 22 14" aria-hidden="true">
      <path d="M1 7 H20 M14 1.5 L20.5 7 L14 12.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

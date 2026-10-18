// Landing: one full-screen security monitor. It clicks on like an old CRT, then the name and
// one line appear over the picture. The feed cycles through the cameras with a quick static
// cut. Below, "how it works" plays a three-step
// walkthrough when it scrolls into view.
import { useEffect, useRef, useState } from 'react'
import type { Page } from '../App'
import Stars from '../components/Stars'
import Wordmark from '../components/Wordmark'
import { clock } from '../format'
import { DEMO_POLICY } from '../rules'
import { useInView } from '../useInView'

export const REPO_URL = 'https://github.com/jayceeasparagus/la_hacks_ai_2026'

interface Channel {
  name: string
  video: string // stock clip under public/footage, shown in CCTV black and white
}

// The channels the monitor flips through, like a guard cycling cameras.
const CHANNELS: Channel[] = [
  { name: 'Emergency exit', video: '/footage/exit.mp4' },
  { name: 'Main entrance', video: '/footage/entrance.mp4' },
  { name: 'Loading dock', video: '/footage/dock.mp4' },
]

const POWER_ON_MS = 900 // the CRT snaps on, then the title fades in
const CHANNEL_MS = 7000
const CUT_MS = 160

export default function Landing({ go }: { go: (p: Page) => void }) {
  const starsRef = useRef<HTMLDivElement>(null)
  const [channel, setChannel] = useState(0)
  const [cutting, setCutting] = useState(false)
  const [on, setOn] = useState(false)
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const clockTimer = window.setInterval(() => setNow(new Date()), 1000)
    const powerTimer = window.setTimeout(() => setOn(true), POWER_ON_MS)
    const channelTimer = window.setInterval(() => {
      setCutting(true)
      window.setTimeout(() => {
        setChannel((c) => (c + 1) % CHANNELS.length)
        setCutting(false)
      }, CUT_MS)
    }, CHANNEL_MS)
    return () => {
      window.clearInterval(clockTimer)
      window.clearTimeout(powerTimer)
      window.clearInterval(channelTimer)
    }
  }, [])

  const onPageMove = (e: React.PointerEvent) => {
    const x = (e.clientX / window.innerWidth - 0.5) * 2
    const y = (e.clientY / window.innerHeight - 0.5) * 2
    if (starsRef.current) starsRef.current.style.transform = `translate(${x * -7}px, ${y * -5}px)`
  }

  const live = CHANNELS[channel]

  return (
    <div className="relative min-h-full overflow-x-hidden bg-ink" onPointerMove={onPageMove}>
      <div ref={starsRef} className="pointer-events-none fixed -inset-4 transition-transform duration-700 ease-out">
        <Stars />
      </div>

      {/* the monitor: fills the first screen, with the nav and title laid over the picture */}
      <section className="relative h-screen min-h-[640px] overflow-hidden">
        <div className="crt-on absolute inset-0 bg-black">
          {CHANNELS.map((c, i) => (
            <div key={c.video} className={`absolute inset-0 transition-opacity duration-150 ${i === channel ? 'opacity-100' : 'opacity-0'}`}>
              <Footage src={c.video} offset={i * 2.3} />
            </div>
          ))}
          {/* darken the centre and edges so the title reads over any footage */}
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,0,0,0.72)_0%,rgba(0,0,0,0.45)_45%,rgba(0,0,0,0.8)_100%)]" />
          <div className="grain absolute inset-0" />
          <div className="scan-sweep" style={{ height: '14%' }} />
          {cutting && <div className="static-cut absolute inset-0" />}

          <div className="absolute inset-x-12 bottom-24 flex items-end justify-between font-mono text-[12px] tracking-label text-text/75">
            <span className="flex gap-4">
              <span>CAM {String(channel + 1).padStart(2, '0')}</span>
              <span className="rec-blink text-text">REC</span>
              <span className="text-text">{live.name}</span>
            </span>
            <span>{clock(now)}</span>
          </div>
        </div>

        <header className="rise relative z-40 flex items-center justify-between px-16 py-8">
          <Wordmark size={24} />
          <nav className="flex items-center gap-10 text-[17px] text-muted">
            <a href="#how" className="transition hover:text-text">How it works</a>
            <a href="#examples" className="transition hover:text-text">Examples</a>
            <a href={REPO_URL} target="_blank" rel="noreferrer" className="transition hover:text-text">GitHub</a>
            <button onClick={() => go('setup')} className="text-text">Demo</button>
          </nav>
        </header>

        {on && (
          <div className="pointer-events-none absolute inset-0 z-30 flex flex-col items-center justify-center gap-8 px-12 text-center">
            <h1 className="rise font-display text-[clamp(72px,10vw,168px)] font-bold leading-[0.92] tracking-[-0.045em]">
              <span className="text-text">Watch</span>
              <span className="text-accent">Dog</span>
            </h1>
            <p
              className="rise max-w-[680px] text-balance text-[26px] leading-[36px] text-[#D6D3CC]"
              style={{ '--d': '150ms' } as React.CSSProperties}
            >
              Tell any camera what matters, in a sentence. It watches. You decide.
            </p>
            <div
              className="rise pointer-events-auto flex items-center justify-center gap-8"
              style={{ '--d': '280ms' } as React.CSSProperties}
            >
              <button className="btn-primary group px-8 py-4 text-[19px]" onClick={() => go('setup')}>
                Demo
                <span className="transition-transform duration-300 group-hover:translate-x-1">
                  <Arrow />
                </span>
              </button>
              <a href="#how" className="text-[19px] text-text/80 transition hover:text-text">
                See how it works
              </a>
            </div>
          </div>
        )}

        <div className="absolute inset-x-12 bottom-6 z-30">
          <Ticker />
        </div>
      </section>

      <HowItWorks />

      <SafetyExamples />

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
      <div className="mb-16 flex flex-col items-center gap-4 text-center">
        <h2 className="font-display text-[48px] font-medium leading-none tracking-[-0.03em]">How it works</h2>
        <p className="max-w-[520px] text-[16px] leading-6 text-muted">
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
          <div className="relative aspect-video overflow-hidden bg-panel">
            <Footage src="/footage/exit.mp4" />
            <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/10 to-black/40" />
            <div className="grain absolute inset-0" />
            <span className="absolute left-3 top-2 font-mono text-[10px] tracking-label text-text">CAM 02</span>
            {stage >= 2 && (
              // a plain detection box, the way the backend's annotated stream draws them
              <div className="chip-in absolute border-2 border-accent-soft" style={{ left: '30%', top: '55%', width: '14%', height: '30%' }}>
                <span className="absolute -top-5 left-0 whitespace-nowrap bg-black/70 px-1.5 font-mono text-[10px] tracking-label text-accent-soft">
                  BACKPACK 5.4 S
                </span>
              </div>
            )}
          </div>
        </Step>
      </div>
    </section>
  )
}

// Real runs, rendered by demo/render_ppe_examples.py: Person 1's detector finds each worker, and the
// hard-hat and hi-vis-vest checks are Gemini's answers on that worker's clearest crop. The boxes and
// verdicts are baked into the video, so this section needs no backend.
const SAFETY_EXAMPLES = [
  {
    video: '/examples/construction_site.mp4',
    poster: '/examples/construction_site.jpg',
    place: 'Construction site',
    rule: 'Everyone in the construction zone wears a hard hat and a hi-vis vest.',
    found: '4 workers checked. 3 in full gear; one is wearing a baseball cap instead of a hard hat.',
  },
  {
    video: '/examples/warehouse.mp4',
    poster: '/examples/warehouse.jpg',
    place: 'Warehouse',
    rule: 'Everyone on the warehouse floor wears a hard hat and a hi-vis vest.',
    found: '3 workers checked. None in a hard hat or hi-vis vest: caps, a beanie and ordinary jackets.',
  },
]

function SafetyExamples() {
  return (
    <section id="examples" className="relative z-10 px-16 pb-28 pt-8">
      <div className="mb-12 flex items-end justify-between gap-10">
        <div className="flex flex-col gap-3">
          <span className="font-display text-[15px] font-medium text-accent-soft">Examples</span>
          <h2 className="font-display text-[48px] font-semibold leading-none tracking-[-0.04em]">Site safety, checked</h2>
        </div>
        <p className="max-w-[460px] text-right text-[16px] leading-6 text-muted">
          One sentence turns any site camera into a safety check. Each worker gets a hard-hat and a hi-vis-vest
          check; it never identifies who anyone is, and every flag goes to a person.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-10">
        {SAFETY_EXAMPLES.map((ex) => (
          <figure key={ex.video} className="flex flex-col gap-5">
            <div className="relative aspect-video overflow-hidden rounded-xl bg-panel ring-1 ring-black">
              <video
                src={ex.video}
                poster={ex.poster}
                autoPlay
                muted
                loop
                playsInline
                preload="metadata"
                className="absolute inset-0 h-full w-full object-cover"
              />
            </div>
            <figcaption className="flex flex-col gap-2">
              <span className="font-display text-[22px] font-medium tracking-[-0.02em] text-text">{ex.place}</span>
              <span className="text-[16px] leading-6 text-[#C9C6BF]">"{ex.rule}"</span>
              <span className="text-[15px] leading-[22px] text-muted">{ex.found}</span>
            </figcaption>
          </figure>
        ))}
      </div>

      <p className="mt-8 text-[13px] leading-5 text-muted">
        Green: gear seen. Amber: gear not seen, sent for review. Verdicts come from Gemini on each worker's
        clearest frame and can be wrong, which is why a person confirms every flag. Footage: Pexels 5434220 and 4281236.
      </p>
    </section>
  )
}

function Step({ n, title, body, children }: { n: number; title: string; body: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col items-center gap-2 text-center">
        <span className="font-display text-[15px] font-medium text-accent-soft">{n}</span>
        <h3 className="font-display text-[22px] font-medium tracking-[-0.03em] text-text">{title}</h3>
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

// A running log of what the cameras noticed, scrolling like a control-room ticker. The list is
// drawn twice so the loop is seamless.
const LOG = [
  ['CAM 01', 'Bag left in the exit doorway', 'Flagged'],
  ['CAM 03', 'Opaque bag at the main entrance', 'Sent for review'],
  ['CAM 02', 'Clear bag', 'No alert'],
  ['CAM 04', 'Chair by the loading door', 'Watching'],
  ['CAM 01', 'Person passing through the exit', 'Ignored'],
  ['CAM 03', 'Professional camera at the entrance', 'Sent for review'],
]

function Ticker() {
  const items = [...LOG, ...LOG]
  return (
    <div
      className="rise relative w-full overflow-hidden border-y border-white/10 py-3 [mask-image:linear-gradient(90deg,transparent,black_12%,black_88%,transparent)]"
      style={{ '--d': '900ms' } as React.CSSProperties}
      aria-hidden="true"
    >
      <div className="ticker flex w-max gap-12 whitespace-nowrap font-mono text-[12px] tracking-[0.04em]">
        {items.map(([cam, what, result], i) => (
          <span key={i} className="flex gap-3">
            <span className="text-dim">{cam}</span>
            <span className="text-text/80">{what}</span>
            <span className={result === 'Flagged' ? 'text-accent-soft' : 'text-muted'}>{result}</span>
          </span>
        ))}
      </div>
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

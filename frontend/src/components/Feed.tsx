// One camera monitor: the live stream with a broadcast-style readout on top.
// If the stream drops, it shows SIGNAL LOST and keeps retrying without touching other feeds.
// Boxes and labels are drawn on the backend's annotated stream; this overlay only shows
// each rule's timer and phase.
import { useEffect, useState } from 'react'
import { clock } from '../format'
import type { Camera, CameraStatus, Rule, RulePhase, RuleState } from '../types'
import LiveVideo from './LiveVideo'

interface Props {
  camera: Camera
  index: number
  status?: CameraStatus
  ruleStates?: RuleState[]
  rules?: Rule[]
  large?: boolean
  onClick?: () => void
}

const PHASE_LABEL: Partial<Record<RulePhase, string>> = { verifying: 'checking', alerted: 'flagged', compliant: 'ok' }

export default function Feed({ camera, index, status, ruleStates = [], rules = [], large, onClick }: Props) {
  const [broken, setBroken] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const t = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(t)
  }, [])

  useEffect(() => {
    if (!broken) return
    const t = window.setTimeout(() => {
      setBroken(false)
      setAttempt((a) => a + 1)
    }, 3000)
    return () => window.clearTimeout(t)
  }, [broken])

  const offline = broken || status?.status === 'offline'
  const alerting = ruleStates.some((s) => s.phase === 'alerted')
  const camNo = String(index + 1).padStart(2, '0')
  const ruleName = (id: string) => {
    const name = rules.find((r) => r.id === id)?.name ?? id.replace(/_/g, ' ')
    return name.charAt(0).toUpperCase() + name.slice(1)
  }

  return (
    <div
      onClick={onClick}
      className={`group relative aspect-video overflow-hidden bg-panel ${onClick ? 'cursor-pointer transition duration-300 hover:-translate-y-0.5 hover:brightness-110' : ''}`}
    >
      {!broken && <LiveVideo camera={camera} attempt={attempt} dimmed={offline} onError={() => setBroken(true)} />}

      {/* soft inner glow while a rule is past its threshold on this camera */}
      <div
        className={`pointer-events-none absolute inset-0 transition-opacity duration-700 ${alerting ? 'opacity-100' : 'opacity-0'}`}
        style={{ boxShadow: 'inset 0 0 120px rgba(45, 79, 150,0.28)' }}
      />

      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between bg-gradient-to-b from-black/60 to-transparent px-4 pb-6 pt-3">
        <span className="label whitespace-nowrap text-text">
          CAM {camNo}
          {large && ` · ${camera.id}`}
        </span>
        <span className="label whitespace-nowrap text-text/80">
          {offline
            ? 'SIGNAL LOST · RETRYING'
            : large
              ? `LIVE · ${status ? status.fps.toFixed(1) : '--'} FPS · ${clock(now)}`
              : 'LIVE'}
        </span>
      </div>

      {offline && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 px-6 text-center">
          <span className="text-[15px] text-text">No signal from {camera.name}</span>
          {large && status?.error && <span className="text-[13px] text-muted">{status.error}</span>}
        </div>
      )}

      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-4 bg-gradient-to-t from-black/70 to-transparent px-4 pb-3 pt-10">
        <span className={`${large ? 'text-[22px]' : 'text-[16px]'} font-medium tracking-[-0.01em] text-text`}>
          {camera.name}
        </span>
        <div className="flex flex-col items-end gap-2">
          {ruleStates.map((s) => {
            const pct = Math.min(1, s.elapsed_seconds / s.duration_seconds)
            const reached = s.phase === 'alerted' || pct >= 1
            const phase = PHASE_LABEL[s.phase]
            return (
              <div key={`${s.rule_id}-${s.track_id}`} className="chip-in w-56 rounded-md bg-black/70 px-3 py-2 backdrop-blur-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-[13px] text-text">{ruleName(s.rule_id)}</span>
                  <span className={`font-mono text-[12px] ${reached ? 'text-accent-soft' : 'text-text'}`}>
                    {phase ?? `${s.elapsed_seconds.toFixed(1)} / ${s.duration_seconds.toFixed(0)} s`}
                  </span>
                </div>
                <div className="mt-1.5 h-[3px] w-full rounded bg-line">
                  <div
                    className={`h-[3px] rounded transition-[width] duration-200 ${reached ? 'bg-accent' : 'bg-text'}`}
                    style={{ width: `${pct * 100}%` }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

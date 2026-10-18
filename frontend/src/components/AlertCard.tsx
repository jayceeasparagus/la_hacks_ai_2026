// One alert in the sidebar: evidence, hedged wording, and the operator's decision buttons.
// The system never acts on its own; an alert only changes when a person decides.
import { useState } from 'react'
import { percent, relativeTime } from '../format'
import type { Alert, Decision } from '../types'

interface Props {
  alert: Alert
  cameraName: string
  isNew?: boolean // just arrived: slide in and pulse once
  shortcuts?: boolean // show C / D / U key hints (top card only)
  resolving?: Decision | null // decided a moment ago; show the result before it moves away
  onDecide: (decision: Decision) => Promise<void>
}

const DECISIONS: { value: Decision; label: string; key: string }[] = [
  { value: 'confirm', label: 'confirm', key: 'C' },
  { value: 'dismiss', label: 'dismiss', key: 'D' },
  { value: 'unclear', label: 'unsure', key: 'U' },
]

const RESOLVED: Record<Decision, string> = { confirm: 'Confirmed', dismiss: 'Dismissed', unclear: 'Marked unsure' }

const RESULT: Record<string, string> = { confirmed: 'confirmed', dismissed: 'dismissed', unclear: 'marked unsure' }

export default function AlertCard({ alert, cameraName, isNew, shortcuts, resolving, onDecide }: Props) {
  const [busy, setBusy] = useState(false)
  const urgent = alert.severity === 'urgent'
  const open = alert.status === 'open'

  if (!open) {
    return (
      <div className="chip-in flex shrink-0 items-baseline justify-between gap-3 py-1.5 text-[14px]">
        <span className="truncate text-muted">{alert.title}</span>
        <span className="shrink-0 font-mono text-[11px] uppercase tracking-label text-dim">{RESULT[alert.status]}</span>
      </div>
    )
  }

  const decide = async (d: Decision) => {
    setBusy(true)
    try {
      await onDecide(d)
    } finally {
      setBusy(false)
    }
  }

  const tone = urgent ? 'bg-accent text-accent-ink' : 'bg-raised text-text'
  const sub = urgent ? 'text-accent-ink/75' : 'text-muted'
  const secondaryBtn = urgent ? 'bg-accent-ink/10 hover:bg-accent-ink/20' : 'bg-line hover:bg-[#2a2a2e]'
  const primaryBtn = urgent ? 'bg-accent-ink text-[#F1EEE6]' : 'bg-[#F1EEE6] text-black'

  return (
    <article
      className={`relative flex shrink-0 flex-col gap-3 overflow-hidden rounded-xl p-3 transition duration-500 ${tone} ${isNew ? (urgent ? 'card-flash' : 'card-in') : ''} ${resolving ? 'scale-[0.98] opacity-80' : ''}`}
    >
      <Evidence alert={alert} />
      {resolving && (
        <div className="toast-in absolute inset-0 z-10 flex items-center justify-center bg-black/55 backdrop-blur-[2px]">
          <span className="flex items-center gap-2 text-[18px] font-semibold text-[#F1EEE6]">
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
              <path className="marker-draw" pathLength={1} d="M3 9.5 L7.5 14 L15 4.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {RESOLVED[resolving]}
          </span>
        </div>
      )}
      <div className="flex flex-col gap-1 px-1">
        <span className={`font-mono text-[11px] font-medium uppercase tracking-label ${sub}`}>
          {cameraName} · {relativeTime(alert.created_at)}
        </span>
        <span className="text-[18px] font-semibold leading-[23px] tracking-[-0.01em]">{alert.title}</span>
        <span className={`text-[14px] leading-[19px] ${sub}`}>{alert.observation}</span>
        <span className={`pt-1 font-mono text-[11px] ${sub}`}>
          {alert.rule_name} · {percent(alert.confidence)} sure
        </span>
      </div>
      <div className="flex gap-1.5">
        {DECISIONS.map((d, i) => (
          <button
            key={d.value}
            disabled={busy || Boolean(resolving)}
            onClick={() => decide(d.value)}
            className={`flex h-10 flex-1 items-center justify-center gap-1.5 rounded-full text-[14px] font-medium transition active:scale-95 disabled:opacity-50 ${i === 0 ? primaryBtn : secondaryBtn}`}
          >
            {d.label}
            {shortcuts && <kbd className="font-mono text-[10px] opacity-55">{d.key}</kbd>}
          </button>
        ))}
      </div>
    </article>
  )
}

function Evidence({ alert }: { alert: Alert }) {
  const box = alert.bbox
  return (
    <div className="relative aspect-video overflow-hidden rounded-md bg-black">
      {alert.evidence_clip ? (
        <video src={alert.evidence_clip} autoPlay muted loop playsInline className="h-full w-full object-cover" />
      ) : alert.evidence_image ? (
        <img src={alert.evidence_image} alt="Evidence frame" className="h-full w-full object-cover" />
      ) : null}
      {box && !alert.evidence_clip && (
        <div
          className="absolute rounded-sm border-2 border-[#F1EEE6]"
          style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }}
        />
      )}
    </div>
  )
}

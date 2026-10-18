// One alert in the sidebar: evidence, hedged wording, and the operator's decision buttons.
// The system never acts on its own; an alert only changes when a person decides.
import { useState } from 'react'
import { createdSeconds } from '../api'
import { percent, relativeTime } from '../format'
import type { Alert, Decision } from '../types'
import Snippet from './Snippet'

interface Props {
  alert: Alert
  cameraName: string
  isNew?: boolean // just arrived: slide in and pulse once
  shortcuts?: boolean // show C / D / U key hints (top card only)
  resolving?: Decision | null // decided a moment ago; show the result before it moves away
  snippet?: { frames: string[]; detectAt: number } // footage around the alert, recorded in this browser
  onDecide: (decision: Decision) => Promise<void>
}

const DECISIONS: { value: Decision; label: string; key: string }[] = [
  { value: 'confirmed', label: 'Confirm', key: 'C' },
  { value: 'dismissed', label: 'Dismiss', key: 'D' },
  { value: 'unclear', label: 'Unsure', key: 'U' },
]

const RESULT: Record<Decision, string> = { confirmed: 'Confirmed', dismissed: 'Dismissed', unclear: 'Marked unsure' }

export default function AlertCard({ alert, cameraName, isNew, shortcuts, resolving, snippet, onDecide }: Props) {
  const [busy, setBusy] = useState(false)
  const urgent = alert.severity === 'urgent'
  const open = alert.status === 'open'

  if (!open) {
    return (
      <div className="chip-in flex shrink-0 items-center gap-3 py-1.5 text-[14px]">
        {(snippet?.frames[snippet.detectAt] ?? alert.evidence_image_url) && (
          <img
            src={snippet?.frames[snippet.detectAt] ?? alert.evidence_image_url!}
            alt=""
            className="h-9 w-16 shrink-0 object-cover"
          />
        )}
        <span className="min-w-0 flex-1 truncate text-muted">{alert.title}</span>
        <span className="shrink-0 text-[13px] text-dim">{alert.decision ? RESULT[alert.decision] : 'Reviewed'}</span>
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

  return (
    <article
      className={`relative flex shrink-0 flex-col gap-3 border-b border-line pb-5 transition duration-500 ${isNew ? 'card-in' : ''} ${resolving ? 'opacity-60' : ''}`}
    >
      <div className={`relative ${isNew && urgent ? 'card-flash' : ''}`}>
        <Evidence alert={alert} snippet={snippet} />
        {resolving && (
          <div className="toast-in absolute inset-0 z-10 flex items-center justify-center bg-black/60">
            <span className="flex items-center gap-2 text-[17px] font-medium text-[#F1EEE6]">
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                <path className="marker-draw" pathLength={1} d="M3 9.5 L7.5 14 L15 4.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {RESULT[resolving]}
            </span>
          </div>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-[13px] text-muted">
          <span className={urgent ? 'text-accent-soft' : 'text-text'}>{urgent ? 'Urgent' : 'Review'}</span> · {cameraName} ·{' '}
          {relativeTime(createdSeconds(alert))}
        </span>
        <span className="text-[18px] font-medium leading-[23px] tracking-[-0.01em] text-text">{alert.title}</span>
        <span className="text-[14px] leading-[19px] text-muted">{alert.observation}</span>
        <span className="pt-0.5 text-[13px] text-dim">
          {alert.rule_name} · {percent(alert.confidence)} sure
        </span>
      </div>
      <div className="flex gap-2">
        {DECISIONS.map((d, i) => (
          <button
            key={d.value}
            disabled={busy || Boolean(resolving)}
            onClick={() => decide(d.value)}
            className={`flex h-10 flex-1 items-center justify-center gap-1.5 rounded-full text-[14px] transition active:scale-95 disabled:opacity-50 ${
              i === 0 ? 'bg-[#F1EEE6] font-medium text-black hover:bg-white' : 'border border-line text-text hover:border-muted'
            }`}
          >
            {d.label}
            {shortcuts && <kbd className="font-mono text-[10px] opacity-50">{d.key}</kbd>}
          </button>
        ))}
      </div>
    </article>
  )
}

function Evidence({ alert, snippet }: { alert: Alert; snippet?: Props['snippet'] }) {
  const image = alert.evidence_image_url
  const clip = alert.evidence_clip_url
  if (!snippet && !clip && !image) {
    if (alert.evidence_status !== 'pending') return null
    return (
      <div className="flex aspect-video items-center justify-center rounded-[4px] bg-black text-[13px] text-muted">
        Saving evidence…
      </div>
    )
  }
  // the backend draws the box on its own evidence; only frames captured in this browser need one
  const box = image?.startsWith('data:') && !clip ? alert.bbox : null
  return (
    <div className="relative aspect-video overflow-hidden bg-black">
      {snippet ? (
        <Snippet frames={snippet.frames} detectAt={snippet.detectAt} />
      ) : clip ? (
        <video src={clip} poster={image ?? undefined} autoPlay muted loop playsInline className="h-full w-full object-cover" />
      ) : (
        <img src={image!} alt="Evidence frame" className="h-full w-full object-cover" />
      )}
      {box && (
        <div
          className="absolute rounded-sm border-2 border-[#F1EEE6]"
          style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }}
        />
      )}
    </div>
  )
}

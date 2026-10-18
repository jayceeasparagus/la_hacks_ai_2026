// Watch: the video wall plus a sidebar of what the system noticed.
// Click a small feed to make it the big one. Open urgent alerts stay pinned on top.
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Page } from '../App'
import { api } from '../api'
import AlertCard from '../components/AlertCard'
import Feed from '../components/Feed'
import Wordmark from '../components/Wordmark'
import { captureFrame } from '../localCamera'
import { loadPolicy } from '../rules'
import type { Alert, Camera, Decision } from '../types'
import { useLive } from '../useLive'

type Tab = 'open' | 'reviewed'

export default function Watch({ go }: { go: (p: Page) => void }) {
  const rules = useMemo(() => loadPolicy()?.rules ?? [], [])
  const [cameras, setCameras] = useState<Camera[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [tab, setTab] = useState<Tab>('open')
  const [cameraFilter, setCameraFilter] = useState<string>('all')
  const [toast, setToast] = useState<Alert | null>(null)
  const [fresh, setFresh] = useState<Set<string>>(new Set()) // arrived in the last few seconds
  const [resolving, setResolving] = useState<Record<string, Decision>>({})
  const [, tick] = useState(0)

  useEffect(() => {
    api.getCameras().then((c) => {
      setCameras(c)
      setSelected((s) => s ?? c.find((x) => x.id === 'cam_exit')?.id ?? c[0]?.id ?? null)
    })
    api.getAlerts().then(setAlerts).catch(() => {})
    const t = window.setInterval(() => tick((n) => n + 1), 15000) // refresh "2 min ago"
    return () => window.clearInterval(t)
  }, [])

  const onAlert = useCallback((incoming: Alert, isUpdate: boolean) => {
    let alert = incoming
    if (!isUpdate) {
      // testing with this browser's webcam: keep the real frame the alert fired on as evidence
      const frame = captureFrame(alert.camera_id)
      if (frame) alert = { ...alert, evidence_image: frame }
      setToast(alert)
      setFresh((f) => new Set(f).add(alert.id))
      window.setTimeout(() => setFresh((f) => {
        const next = new Set(f)
        next.delete(alert.id)
        return next
      }), 3000)
    }
    setAlerts((prev) => {
      const old = prev.find((a) => a.id === alert.id)
      if (old?.evidence_image?.startsWith('data:')) alert = { ...alert, evidence_image: old.evidence_image }
      return [alert, ...prev.filter((a) => a.id !== alert.id)]
    })
  }, [])

  const live = useLive(onAlert)

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 5000)
    return () => window.clearTimeout(t)
  }, [toast])

  const openCount = alerts.filter((a) => a.status === 'open').length
  useEffect(() => {
    document.title = openCount ? `(${openCount}) policylens` : 'policylens'
  }, [openCount])

  // show the decision on the card for a moment, then move it to reviewed
  const decide = async (id: string, decision: Decision) => {
    setResolving((r) => ({ ...r, [id]: decision }))
    try {
      const updated = await api.decide(id, decision)
      await new Promise((r) => window.setTimeout(r, 900))
      setAlerts((prev) => prev.map((a) => (a.id === id ? { ...updated, evidence_image: a.evidence_image } : a)))
    } finally {
      setResolving(({ [id]: _, ...rest }) => rest)
    }
  }

  const stop = async () => {
    await api.stopMonitor().catch(() => {})
    go('setup')
  }

  const cameraName = (id: string) => cameras.find((c) => c.id === id)?.name ?? id
  const visible = alerts
    .filter((a) => (tab === 'open' ? a.status === 'open' : a.status !== 'open'))
    .filter((a) => cameraFilter === 'all' || a.camera_id === cameraFilter)
    .sort((a, b) => {
      const pin = Number(b.severity === 'urgent') - Number(a.severity === 'urgent')
      return tab === 'open' && pin !== 0 ? pin : b.created_at - a.created_at
    })

  const top = tab === 'open' ? visible.find((a) => !resolving[a.id]) : undefined

  // C / D / U decide the top alert, so an operator can keep their eyes on the video
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (!top || e.metaKey || e.ctrlKey || e.altKey || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)) return
      const decision = ({ c: 'confirm', d: 'dismiss', u: 'unclear' } as const)[e.key.toLowerCase() as 'c' | 'd' | 'u']
      if (decision) decide(top.id, decision)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const main = cameras.find((c) => c.id === selected)
  const others = cameras.filter((c) => c.id !== selected)
  const indexOf = (id: string) => cameras.findIndex((c) => c.id === id)
  const onlineCount = cameras.filter((c) => live.cameras[c.id]?.online).length

  return (
    <div className="flex h-full flex-col bg-ink">
      <header className="flex shrink-0 items-center justify-between px-8 py-5">
        <Wordmark size={22} onClick={() => go('landing')} />
        <div className="flex items-center gap-7 text-[17px]">
          <span className="label">
            {live.connected ? `${onlineCount} of ${cameras.length} cameras live` : 'Reconnecting…'}
          </span>
          <button className="text-muted hover:text-text" onClick={() => go('setup')}>edit policy</button>
          <button className="text-text" onClick={stop}>stop</button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 gap-8 px-8 pb-8">
        <section className="flex min-w-0 flex-1 flex-col gap-3 overflow-y-auto">
          {main && (
            <div key={main.id} className="chip-in">
              <Feed
                camera={main}
                index={indexOf(main.id)}
                status={live.cameras[main.id]}
                ruleStates={live.ruleStates[main.id]}
                rules={rules}
                large
              />
            </div>
          )}
          <div className="grid grid-cols-3 gap-3">
            {others.map((cam) => (
              <Feed
                key={cam.id}
                camera={cam}
                index={indexOf(cam.id)}
                status={live.cameras[cam.id]}
                ruleStates={live.ruleStates[cam.id]}
                rules={rules}
                onClick={() => setSelected(cam.id)}
              />
            ))}
          </div>
          {cameras.length === 0 && <p className="text-muted">No cameras connected. Add one in setup.</p>}
        </section>

        <aside className="flex w-[340px] shrink-0 flex-col gap-4">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[36px] font-semibold leading-none tracking-[-0.04em]">Noticed</h2>
            <span className="label">{openCount ? `${openCount} need you` : 'all clear'}</span>
          </div>
          <div className="flex items-center gap-2">
            {(['open', 'reviewed'] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-full px-3.5 py-1.5 text-[14px] ${tab === t ? 'bg-raised text-text' : 'text-muted hover:text-text'}`}
              >
                {t}
              </button>
            ))}
            <select
              value={cameraFilter}
              onChange={(e) => setCameraFilter(e.target.value)}
              className="ml-auto rounded-full bg-raised px-3 py-1.5 text-[14px] text-text outline-none"
              aria-label="Filter by camera"
            >
              <option value="all">all cameras</option>
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div className="-m-3 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
            {visible.length === 0 && (
              <p className="pt-2 text-[15px] text-muted">{tab === 'open' ? 'Nothing needs you right now.' : 'No decisions yet.'}</p>
            )}
            {visible.map((a) => (
              <AlertCard
                key={a.id}
                alert={a}
                cameraName={cameraName(a.camera_id)}
                isNew={fresh.has(a.id)}
                shortcuts={a.id === top?.id}
                resolving={resolving[a.id] ?? null}
                onDecide={(d) => decide(a.id, d)}
              />
            ))}
          </div>
        </aside>
      </div>

      {toast && (
        <div className="toast-in fixed left-1/2 top-5 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full bg-[#F1EEE6] px-5 py-2.5 text-[15px] text-black">
          <span className="font-mono text-[11px] font-semibold uppercase tracking-label">{toast.severity}</span>
          <span className="font-medium">{toast.title}</span>
          <span className="text-black/60">· {cameraName(toast.camera_id)}</span>
        </div>
      )}
    </div>
  )
}

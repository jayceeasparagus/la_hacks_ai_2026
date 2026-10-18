// Demo: type a policy and watch it apply to the example cameras at once. The sentence compiles
// to rules, the rules go live on every camera (PUT /api/policy swaps them in while monitoring),
// and the backend's annotated streams show each person with their gear checks. Alerts arrive
// on the right for a person to confirm or dismiss. Run the backend with the site safety scene:
//   POLICYLENS_SCENE=../demo/scenes/site_safety.json uvicorn app.main:app --port 8000
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { Page } from '../App'
import { api, createdSeconds } from '../api'
import AlertCard from '../components/AlertCard'
import Feed from '../components/Feed'
import Wordmark from '../components/Wordmark'
import { objectsLabel } from '../format'
import { ruleCondition } from '../rules'
import type { Alert, Camera, CompileResult, Decision, Rule, RuleState, Zone } from '../types'
import { useLive } from '../useLive'

const EXAMPLES = [
  'Workers at the construction site need to wear a vest and a helmet.',
  'Everyone must wear a hard hat.',
  'Hi-vis vests are required for everyone on the floor.',
]

type Phase = 'idle' | 'compiling' | 'applying'

// One card per requirement: a policy that covers two cameras compiles to one rule per camera.
interface RuleGroup {
  key: string
  rules: Rule[]
}

function groupRules(rules: Rule[]): RuleGroup[] {
  const groups: RuleGroup[] = []
  for (const rule of rules) {
    const key = JSON.stringify([rule.name, rule.type, rule.attribute, rule.objects, rule.duration_seconds, rule.severity])
    const group = groups.find((g) => g.key === key)
    if (group) group.rules.push(rule)
    else groups.push({ key, rules: [rule] })
  }
  return groups
}

// Cameras are judged as a whole frame here, so no wording mentions zones.
function condition(rule: Rule): string {
  if (rule.type === 'persistent_object') {
    return `A ${objectsLabel(rule.objects)} stays in view for ${rule.duration_seconds} s or more`
  }
  return ruleCondition(rule)
}

export default function Demo({ go }: { go: (p: Page) => void }) {
  const [cameras, setCameras] = useState<Camera[]>([])
  const [zones, setZones] = useState<Zone[]>([])
  const [rules, setRules] = useState<Rule[]>([])
  const [text, setText] = useState('')
  const [result, setResult] = useState<CompileResult | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [fresh, setFresh] = useState<Set<string>>(new Set())
  const [resolving, setResolving] = useState<Record<string, Decision>>({})
  const [streamEpoch, setStreamEpoch] = useState(0)

  // The cameras play on a loop, so monitoring starts as soon as the page opens, and again
  // whenever the socket reconnects (for example after the backend restarted).
  const load = useCallback(() => {
    Promise.all([api.getCameras(), api.getZones(), api.getPolicy()])
      .then(([c, z, r]) => {
        setCameras(c)
        setZones(z)
        setRules(r)
        if (!c.length) {
          setError('No cameras are set up. Start the backend with POLICYLENS_SCENE=../demo/scenes/site_safety.json.')
          return
        }
        setError(null)
        return api.startMonitor()
      })
      .catch((e) => setError(`Can't reach the backend on :8000. ${(e as Error).message}`))
    api.getAlerts().then(setAlerts).catch(() => {})
  }, [])

  useEffect(load, [load])

  const onAlert = useCallback((incoming: Alert, isUpdate: boolean) => {
    setAlerts((prev) => [incoming, ...prev.filter((a) => a.id !== incoming.id)])
    if (isUpdate) return
    setFresh((f) => new Set(f).add(incoming.id))
    window.setTimeout(() => setFresh((f) => {
      const next = new Set(f)
      next.delete(incoming.id)
      return next
    }), 3000)
  }, [])

  const live = useLive(onAlert, load)

  // The MJPEG stream only exists while monitoring: reconnect the feeds whenever it (re)starts.
  useEffect(() => {
    if (live.running) setStreamEpoch((n) => n + 1)
  }, [live.running])

  const busy = phase !== 'idle'

  const apply = async (policy: string) => {
    if (!policy.trim() || busy) return
    setText(policy)
    setPhase('compiling')
    setError(null)
    try {
      const compiled = await api.compilePolicy(policy)
      setResult(compiled)
      if (!compiled.rules.length) return // nothing to watch for: the current rules keep running
      setPhase('applying')
      setRules(await api.putPolicy(compiled.rules))
      await api.startMonitor() // idempotent; the rules are already live if it was running
    } catch (e) {
      setError(`Couldn't apply the policy. ${(e as Error).message}`)
    } finally {
      setPhase('idle')
    }
  }

  const replaceRules = async (next: Rule[]) => {
    setError(null)
    try {
      setRules(await api.putPolicy(next))
    } catch (e) {
      setError(`Couldn't update the rules. ${(e as Error).message}`)
    }
  }

  const decide = async (id: string, decision: Decision) => {
    setResolving((r) => ({ ...r, [id]: decision }))
    try {
      const updated = await api.decide(id, decision)
      await new Promise((r) => window.setTimeout(r, 900))
      setAlerts((prev) => prev.map((a) => (a.id === id ? updated : a)))
    } finally {
      setResolving(({ [id]: _, ...rest }) => rest)
    }
  }

  const cameraName = (id: string) => cameras.find((c) => c.id === id)?.name ?? id
  const cameraOfZone = (zoneId: string) => zones.find((z) => z.id === zoneId)?.camera_id ?? ''
  const groups = useMemo(() => groupRules(rules), [rules])
  const onlineCount = cameras.filter((c) => live.cameras[c.id]?.status === 'online').length

  // Alerts from these cameras only (the store may hold alerts from other scenes); open ones first.
  const shown = alerts
    .filter((a) => cameras.some((c) => c.id === a.camera_id))
    .sort((a, b) => Number(b.status === 'open') - Number(a.status === 'open') || createdSeconds(b) - createdSeconds(a))
  const openCount = shown.filter((a) => a.status === 'open').length

  return (
    <div className="flex min-h-full flex-col bg-ink lg:h-full">
      <header className="flex shrink-0 items-center justify-between gap-4 px-4 py-5 sm:px-8">
        <Wordmark size={22} onClick={() => go('landing')} />
        <span className="text-[15px] text-muted">
          {!live.connected ? 'Connecting…' : `${onlineCount} of ${cameras.length} cameras live`}
        </span>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-8 px-4 pb-8 sm:px-8 lg:grid-cols-[360px_minmax(0,1fr)_320px]">
        {/* The policy: one sentence in, rule cards out. */}
        <section className="flex min-h-0 flex-col gap-6 lg:overflow-y-auto">
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault()
              apply(text)
            }}
          >
            <label htmlFor="policy" className="text-[15px] text-muted">
              What should these cameras watch for?
            </label>
            <textarea
              id="policy"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  apply(text)
                }
              }}
              rows={4}
              placeholder="Workers need to wear a hard hat and a hi-vis vest."
              className="resize-none rounded-md border border-line bg-panel px-4 py-3 text-[21px] leading-[29px] tracking-[-0.01em] text-text outline-none placeholder:text-dim focus:border-muted"
            />
            <button type="submit" className="btn-primary self-start" disabled={busy || !text.trim()}>
              {phase === 'compiling' ? 'Reading the policy…' : phase === 'applying' ? 'Applying…' : 'Apply policy'}
            </button>
            <div className="flex flex-col items-start gap-1.5">
              <span className="text-[13px] text-dim">Or try one of these</span>
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  disabled={busy}
                  onClick={() => apply(example)}
                  className="text-left text-[14px] leading-5 text-muted underline-offset-4 transition hover:text-text hover:underline disabled:opacity-50"
                >
                  {example}
                </button>
              ))}
            </div>
          </form>

          {error && <p className="text-[14px] leading-5 text-accent-soft">{error}</p>}

          <div className="flex flex-col gap-3">
            <div className="flex items-baseline justify-between">
              <h2 className="text-[17px] font-medium text-text">Watching for</h2>
              {rules.length > 0 && (
                <button className="text-[13px] text-dim transition hover:text-text" onClick={() => replaceRules([])}>
                  Clear all
                </button>
              )}
            </div>
            {groups.length === 0 && (
              <p className="text-[14px] leading-5 text-muted">
                Nothing yet. The cameras are already running; apply a policy and every camera checks it straight away.
              </p>
            )}
            <ul className="flex flex-col">
              {groups.map((group) => {
                const rule = group.rules[0]
                const covered = [...new Set(group.rules.map((r) => cameraName(cameraOfZone(r.zone))))]
                return (
                  <li key={group.key} className="chip-in flex items-start gap-3 border-b border-line py-3.5">
                    <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="text-[16px] text-text">{rule.name}</span>
                      <span className="text-[14px] leading-5 text-muted">{condition(rule)}</span>
                      <span className="pt-1 text-[13px] text-dim">
                        {rule.severity === 'urgent' ? 'Urgent' : 'Needs review'} on {covered.join(' and ')}
                      </span>
                    </div>
                    <button
                      className="shrink-0 rounded-full px-2 py-1 text-[13px] text-dim transition hover:text-text"
                      aria-label={`Stop watching for ${rule.name}`}
                      onClick={() => replaceRules(rules.filter((r) => !group.rules.includes(r)))}
                    >
                      Remove
                    </button>
                  </li>
                )
              })}
            </ul>
            {result && (result.warnings.length > 0 || result.unsupported.length > 0) && (
              <ul className="flex flex-col gap-1.5 text-[14px] leading-5 text-muted">
                {[...result.unsupported, ...result.warnings].map((note) => (
                  <li key={note}>{note}</li>
                ))}
                {result.rules.length === 0 && <li className="text-dim">The rules above are still running.</li>}
              </ul>
            )}
          </div>
        </section>

        {/* The cameras: annotated streams with a box and gear checks per person. */}
        <section className="flex min-h-0 flex-col gap-5 lg:overflow-y-auto">
          {cameras.map((cam, i) => (
            <div key={cam.id} className="flex flex-col gap-2">
              <Feed key={`${cam.id}-${streamEpoch}`} camera={cam} index={i} status={live.cameras[cam.id]} large />
              <CameraSummary states={live.ruleStates[cam.id] ?? []} watching={rules.some((r) => cameraOfZone(r.zone) === cam.id)} />
            </div>
          ))}
        </section>

        {/* What the cameras noticed: a person decides every alert. */}
        <aside className="flex min-h-0 flex-col gap-4">
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-[28px] font-semibold leading-none tracking-[-0.04em]">Noticed</h2>
            <span className="text-[14px] text-muted">{openCount ? `${openCount} need you` : 'All clear'}</span>
          </div>
          <div className="-m-3 flex min-h-0 flex-1 flex-col gap-5 p-3 lg:overflow-y-auto">
            {shown.length === 0 && (
              <p className="pt-1 text-[15px] leading-6 text-muted">
                Missing gear shows up here with a picture of the moment, for you to confirm or dismiss.
              </p>
            )}
            {shown.map((a) => (
              <AlertCard
                key={a.id}
                alert={a}
                cameraName={cameraName(a.camera_id)}
                isNew={fresh.has(a.id)}
                resolving={resolving[a.id] ?? null}
                onDecide={(d) => decide(a.id, d)}
              />
            ))}
          </div>
        </aside>
      </div>
    </div>
  )
}

// A one-line readout under each video: how many people are being checked right now.
function CameraSummary({ states, watching }: { states: RuleState[]; watching: boolean }) {
  if (!watching) return <span className="text-[13px] text-dim">No rules on this camera</span>
  const people = new Set(states.map((s) => s.track_id))
  const flagged = new Set(states.filter((s) => s.phase === 'alerted').map((s) => s.track_id))
  if (!people.size) return <span className="text-[13px] text-dim">Watching; nobody in view</span>
  return (
    <span className="text-[13px] text-muted">
      Checking {people.size} {people.size === 1 ? 'person' : 'people'}
      {flagged.size > 0 && `, ${flagged.size} flagged for review`}
    </span>
  )
}

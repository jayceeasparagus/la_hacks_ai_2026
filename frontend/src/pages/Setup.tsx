// Setup: write the policy, check what it compiled to, connect cameras and draw their zones,
// then start watching. Nothing runs until the operator confirms the rules.
import { useEffect, useState } from 'react'
import type { Page } from '../App'
import { api } from '../api'
import LiveVideo from '../components/LiveVideo'
import ZoneEditor from '../components/ZoneEditor'
import Wordmark from '../components/Wordmark'
import { DEMO_POLICY, loadPolicy, ruleCondition, savePolicy } from '../rules'
import type { Camera, CompileResult, Rule, Severity, Zone } from '../types'
import { Arrow } from './Landing'

const MAX_CAMERAS = 3
const SEVERITIES: Severity[] = ['info', 'review', 'urgent']

export default function Setup({ go }: { go: (p: Page) => void }) {
  const saved = loadPolicy()
  const [cameras, setCameras] = useState<Camera[]>([])
  const [zones, setZones] = useState<Zone[]>([])
  const [editing, setEditing] = useState<Camera | null>(null)
  const [adding, setAdding] = useState(false)
  const [text, setText] = useState(saved?.text || DEMO_POLICY)
  const [result, setResult] = useState<CompileResult | null>(saved ? { rules: saved.rules, warnings: [], unsupported: [] } : null)
  const [rules, setRules] = useState<Rule[]>(saved?.rules ?? [])
  const [compiling, setCompiling] = useState(false)
  const [compileCount, setCompileCount] = useState(0)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.getCameras(), api.getZones()])
      .then(([c, z]) => {
        setCameras(c)
        setZones(z)
      })
      .catch((e) => setError(`Can't reach the backend. ${e.message}`))
  }, [])

  const compile = async () => {
    setCompiling(true)
    setError(null)
    try {
      const r = await api.compilePolicy(text)
      setResult(r)
      setRules(r.rules)
      setCompileCount((n) => n + 1)
    } catch (e) {
      setError(`Couldn't read the policy. ${(e as Error).message}`)
    } finally {
      setCompiling(false)
    }
  }

  const saveCameras = async (next: Camera[]) => {
    setCameras(next)
    try {
      await api.putCameras(next)
    } catch (e) {
      setError(`Couldn't save cameras. ${(e as Error).message}`)
    }
  }

  const saveZones = async (camera: Camera, cameraZones: Zone[]) => {
    const next = [...zones.filter((z) => z.camera_id !== camera.id), ...cameraZones]
    setZones(next)
    setEditing(null)
    try {
      await api.putZones(next)
    } catch (e) {
      setError(`Couldn't save zones. ${(e as Error).message}`)
    }
  }

  const updateRule = (id: string, patch: Partial<Rule>) => setRules(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)))

  const start = async () => {
    setStarting(true)
    setError(null)
    try {
      await api.putPolicy(text, rules)
      await api.startMonitor()
      savePolicy(text, rules)
      go('watch')
    } catch (e) {
      setError(`Couldn't start monitoring. ${(e as Error).message}`)
      setStarting(false)
    }
  }

  const where = (rule: Rule) => {
    const zone = zones.find((z) => z.id === rule.zone)
    const cam = cameras.find((c) => c.id === zone?.camera_id)
    const zoneName = zone?.name ?? rule.zone.replace(/_/g, ' ')
    return cam && cam.name.toLowerCase() !== zoneName.toLowerCase() ? `${zoneName} on ${cam.name}` : zoneName
  }
  const enabledCount = rules.filter((r) => r.enabled).length

  return (
    <div className="min-h-full bg-ink">
      <header className="flex items-center justify-between px-16 py-8">
        <Wordmark size={24} onClick={() => go('landing')} />
        <nav className="flex items-center gap-6 text-[17px]">
          <span className="text-text">Connect</span>
          <span className="text-dim">→</span>
          <span className="text-text">Write</span>
          <span className="text-dim">→</span>
          <span className="text-dim">Watch</span>
        </nav>
      </header>

      <main className="mx-auto grid max-w-[1320px] grid-cols-[minmax(0,1fr)_360px] gap-24 px-16 pb-24 pt-6">
        {/* the policy, written like a document */}
        <section className="rise flex flex-col">
          <h1 className="font-display text-[56px] font-semibold leading-[1.05] tracking-[-0.045em]">
            What matters <span className="text-accent">here?</span>
          </h1>

          <div className="mt-10">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) compile()
              }}
              rows={5}
              className="w-full resize-none bg-transparent text-[26px] leading-[40px] text-text caret-accent outline-none placeholder:text-dim"
              placeholder="Describe the rules for this space."
              aria-label="Policy"
            />
            <div className="relative h-px w-full overflow-hidden bg-line">{compiling && <div className="reading-bar" />}</div>
            <div className="mt-4 flex items-center justify-between">
              <span className="text-[14px] text-muted">{compiling ? 'Reading your policy…' : '⌘ Enter to read it'}</span>
              <button className="btn-primary py-2.5 text-[15px]" onClick={compile} disabled={compiling || !text.trim()}>
                {result ? 'Read again' : 'Read it'}
              </button>
            </div>
          </div>

          {result && (
            <div className="mt-16 flex flex-col">
              <h2 className="mb-2 font-display text-[22px] font-medium tracking-[-0.02em]">
                It will watch for {rules.length === 1 ? 'one thing' : `${rules.length} things`}
              </h2>
              <ul className="flex flex-col">
                {rules.map((rule, i) => (
                  <RuleRow
                    key={`${compileCount}-${rule.id}`}
                    index={i}
                    rule={rule}
                    where={where(rule)}
                    onChange={(patch) => updateRule(rule.id, patch)}
                  />
                ))}
                {result.unsupported.map((u, i) => (
                  <li
                    key={`${compileCount}-${u}`}
                    className="rise flex gap-5 border-b border-line py-5"
                    style={{ '--d': `${(rules.length + i) * 110}ms` } as React.CSSProperties}
                  >
                    <span className="w-6 shrink-0 pt-0.5 font-mono text-[13px] text-dim">—</span>
                    <span className="flex flex-col gap-1">
                      <span className="text-[17px] text-muted">Can't watch for this</span>
                      <span className="text-[14px] leading-5 text-dim">{u}</span>
                    </span>
                  </li>
                ))}
              </ul>
              {result.warnings.map((w) => (
                <p key={w} className="mt-4 text-[14px] text-muted">
                  {w}
                </p>
              ))}
            </div>
          )}

          <div className="mt-12 flex items-center justify-between gap-6">
            <span className="text-[14px] text-muted">{error}</span>
            <button className="btn-primary group" onClick={start} disabled={starting || enabledCount === 0}>
              {starting ? 'Starting…' : 'Start watching'}
              <span className="transition-transform duration-300 group-hover:translate-x-1">
                <Arrow />
              </span>
            </button>
          </div>
        </section>

        {/* cameras, beside the policy */}
        <aside className="rise flex flex-col gap-6 self-start pt-3" style={{ '--d': '120ms' } as React.CSSProperties}>
          <div className="flex items-baseline justify-between">
            <h2 className="font-display text-[22px] font-medium tracking-[-0.02em]">Cameras</h2>
            <span className="text-[14px] text-muted">
              {cameras.length} of {MAX_CAMERAS}
            </span>
          </div>
          {cameras.map((cam, i) => {
            const camZones = zones.filter((z) => z.camera_id === cam.id)
            return (
              <div key={cam.id} className="flex flex-col gap-2.5">
                <button
                  onClick={() => setEditing(cam)}
                  className="group relative aspect-video overflow-hidden rounded-[4px] bg-panel text-left"
                  aria-label={`Draw zones on ${cam.name}`}
                >
                  <LiveVideo camera={cam} />
                  <svg className="absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none">
                    {camZones.map((z) => (
                      <polygon
                        key={z.id}
                        points={z.polygon.map((p) => p.join(',')).join(' ')}
                        fill="rgba(45, 79, 150,0.08)"
                        stroke="#F1EEE6"
                        strokeWidth={1.2}
                        vectorEffect="non-scaling-stroke"
                      />
                    ))}
                  </svg>
                  <span className="absolute left-2.5 top-2 font-mono text-[10px] tracking-label text-text">
                    CAM {String(i + 1).padStart(2, '0')}
                  </span>
                  <span className="absolute inset-0 flex items-center justify-center bg-black/55 text-[15px] text-text opacity-0 transition duration-300 group-hover:opacity-100">
                    Draw zones
                  </span>
                </button>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-[16px] text-text">{cam.name}</span>
                  <button
                    className="shrink-0 text-[13px] text-dim transition hover:text-text"
                    onClick={() => saveCameras(cameras.filter((c) => c.id !== cam.id))}
                  >
                    Remove
                  </button>
                </div>
                <span className="-mt-2 truncate text-[13px] text-muted">
                  {camZones.length ? camZones.map((z) => z.name).join(', ') : 'No zones yet'} ·{' '}
                  <span className="font-mono text-[12px]">{cam.source}</span>
                </span>
              </div>
            )
          })}
          {adding ? (
            <AddCamera
              existing={cameras}
              onAdd={(c) => {
                saveCameras([...cameras, c])
                setAdding(false)
              }}
              onCancel={() => setAdding(false)}
            />
          ) : (
            cameras.length < MAX_CAMERAS && (
              <button className="self-start text-[15px] text-muted transition hover:text-text" onClick={() => setAdding(true)}>
                + Connect another camera
              </button>
            )
          )}
        </aside>
      </main>

      {editing && (
        <ZoneEditor
          camera={editing}
          zones={zones.filter((z) => z.camera_id === editing.id)}
          onSave={(z) => saveZones(editing, z)}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

// One compiled rule. Every rule gets the same row and the same controls.
function RuleRow({ index, rule, where, onChange }: { index: number; rule: Rule; where: string; onChange: (p: Partial<Rule>) => void }) {
  const timing = rule.type === 'persistent_object' ? 'Alert after' : 'Check after'
  return (
    <li
      className={`rise flex items-start gap-5 border-b border-line py-5 transition-opacity duration-300 ${rule.enabled ? '' : 'opacity-40'}`}
      style={{ '--d': `${index * 110}ms` } as React.CSSProperties}
    >
      <span className="w-6 shrink-0 pt-1 font-mono text-[13px] text-dim">{String(index + 1).padStart(2, '0')}</span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="text-[17px] text-text">{rule.name}</span>
        <span className="text-[14px] leading-5 text-muted">
          {ruleCondition(rule)} · {where}
        </span>
        <div className="mt-3 flex flex-wrap items-center gap-x-8 gap-y-3 text-[14px]">
          <div className="flex items-center gap-2 text-muted">
            {timing}
            <span className="flex items-center rounded-full border border-line">
              <button
                className="px-2.5 py-1 text-muted transition hover:text-text"
                onClick={() => onChange({ duration_seconds: Math.max(0.5, rule.duration_seconds - 0.5) })}
                aria-label="Fewer seconds"
              >
                −
              </button>
              <span className="w-10 text-center font-mono text-[13px] text-text">{rule.duration_seconds} s</span>
              <button
                className="px-2.5 py-1 text-muted transition hover:text-text"
                onClick={() => onChange({ duration_seconds: rule.duration_seconds + 0.5 })}
                aria-label="More seconds"
              >
                +
              </button>
            </span>
          </div>
          <div className="flex items-center gap-1" role="radiogroup" aria-label="Severity">
            {SEVERITIES.map((s) => (
              <button
                key={s}
                role="radio"
                aria-checked={rule.severity === s}
                onClick={() => onChange({ severity: s })}
                className={`rounded-full border px-3 py-1 capitalize transition ${
                  rule.severity === s
                    ? `border-line ${s === 'urgent' ? 'text-accent-soft' : 'text-text'}`
                    : 'border-transparent text-dim hover:text-muted'
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>
      <Toggle on={rule.enabled} onChange={(on) => onChange({ enabled: on })} label={rule.name} />
    </li>
  )
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (on: boolean) => void; label: string }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      aria-label={`${on ? 'Turn off' : 'Turn on'} ${label}`}
      onClick={() => onChange(!on)}
      className={`relative mt-1 h-6 w-10 shrink-0 rounded-full border transition ${on ? 'border-transparent bg-[#F1EEE6]' : 'border-line bg-transparent'}`}
    >
      <span
        className={`absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full transition-all duration-300 ${on ? 'left-[20px] bg-black' : 'left-[3px] bg-dim'}`}
      />
    </button>
  )
}

function AddCamera({ existing, onAdd, onCancel }: { existing: Camera[]; onAdd: (c: Camera) => void; onCancel: () => void }) {
  const [name, setName] = useState('')
  const [source, setSource] = useState('')
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || !source.trim()) return
    let id = `cam_${name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_')}`
    while (existing.some((c) => c.id === id)) id += '_2'
    onAdd({ id, name: name.trim(), source: source.trim() })
  }
  const field = 'border-b border-line bg-transparent py-2 text-[15px] text-text outline-none placeholder:text-dim focus:border-muted'
  return (
    <form onSubmit={submit} className="rise flex flex-col gap-3">
      <input className={field} placeholder="Name, e.g. Side door" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      <input
        className={`${field} font-mono text-[13px]`}
        placeholder="webcam:1 or http://phone-ip:8080/video"
        value={source}
        onChange={(e) => setSource(e.target.value)}
      />
      <div className="flex gap-5 pt-1 text-[15px]">
        <button type="submit" className="text-text">Connect</button>
        <button type="button" className="text-muted hover:text-text" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

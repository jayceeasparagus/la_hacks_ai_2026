// Setup: connect cameras and draw their zones, write the policy, review what it compiled to,
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

  const zoneName = (id: string) => zones.find((z) => z.id === id)?.name ?? id.replace(/_/g, ' ')
  const zoneCamera = (id: string) => cameras.find((c) => c.id === zones.find((z) => z.id === id)?.camera_id)

  return (
    <div className="min-h-full bg-ink">
      <header className="flex items-center justify-between px-16 py-8">
        <Wordmark size={24} onClick={() => go('landing')} />
        <nav className="flex items-center gap-6 text-[17px]">
          <span className="text-text">connect</span>
          <span className="text-dim">→</span>
          <span className="text-text">write</span>
          <span className="text-dim">→</span>
          <span className="text-dim">watch</span>
        </nav>
      </header>

      <main className="mx-auto flex max-w-[1320px] flex-col gap-12 px-16 pb-20">
        <h1 className="rise text-[64px] font-semibold leading-none tracking-[-0.045em]">
          What matters <span className="text-accent">here?</span>
        </h1>

        <div className="grid grid-cols-[440px_minmax(0,1fr)] gap-14">
          {/* cameras */}
          <section className="rise flex flex-col gap-5" style={{ '--d': '100ms' } as React.CSSProperties}>
            <span className="label">Your cameras</span>
            <div className="grid grid-cols-2 gap-4">
              {cameras.map((cam, i) => {
                const camZones = zones.filter((z) => z.camera_id === cam.id)
                return (
                  <div key={cam.id} className="flex flex-col gap-2">
                    <button
                      onClick={() => setEditing(cam)}
                      className="group relative aspect-video overflow-hidden rounded-md bg-panel text-left"
                      aria-label={`Draw zones on ${cam.name}`}
                    >
                      <LiveVideo camera={cam} />
                      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none">
                        {camZones.map((z) => (
                          <polygon
                            key={z.id}
                            points={z.polygon.map((p) => p.join(',')).join(' ')}
                            fill="rgba(143,178,255,0.08)"
                            stroke="#F1EEE6"
                            strokeWidth={1.2}
                            vectorEffect="non-scaling-stroke"
                          />
                        ))}
                      </svg>
                      <span className="label absolute left-2 top-2 text-[10px] text-text">CAM {String(i + 1).padStart(2, '0')}</span>
                      <span className="absolute inset-0 flex items-center justify-center bg-black/60 text-[14px] text-text opacity-0 transition group-hover:opacity-100">
                        Draw zones
                      </span>
                    </button>
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate text-[15px] text-text">{cam.name}</span>
                        <span className="truncate font-mono text-[11px] text-dim">
                          {camZones.length} zone{camZones.length === 1 ? '' : 's'} · {cam.source}
                        </span>
                      </div>
                      <button
                        className="text-[13px] text-dim hover:text-text"
                        onClick={() => saveCameras(cameras.filter((c) => c.id !== cam.id))}
                        aria-label={`Remove ${cam.name}`}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
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
                <button className="self-start text-[15px] text-muted hover:text-text" onClick={() => setAdding(true)}>
                  + connect another camera
                </button>
              )
            )}
          </section>

          {/* policy */}
          <section className="rise flex flex-col gap-8" style={{ '--d': '180ms' } as React.CSSProperties}>
            <div className="relative flex flex-col overflow-hidden rounded-xl border border-line bg-panel">
              {compiling && <div className="scan-line" />}
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) compile()
                }}
                rows={5}
                className="resize-none bg-transparent px-8 pt-7 text-[24px] leading-[36px] text-text outline-none placeholder:text-dim"
                placeholder="Describe the rules for this space, the way you'd brief a new staff member."
                aria-label="Policy"
              />
              <div className="flex items-center justify-end gap-4 px-6 pb-5 pt-2">
                <button className="btn-primary py-2.5 text-[15px]" onClick={compile} disabled={compiling || !text.trim()}>
                  {compiling ? 'reading…' : result ? 'read again' : 'read it'}
                  <span className="font-mono text-[12px] text-black/50">⌘↵</span>
                </button>
              </div>
            </div>

            {result && (
              <div className="flex flex-col gap-4">
                <span className="label text-accent">It will watch for</span>
                <div className="grid grid-cols-3 gap-4">
                  {rules.map((rule, i) => (
                    <RuleCard
                      key={`${compileCount}-${rule.id}`}
                      delay={i * 110}
                      rule={rule}
                      zone={zoneName(rule.zone)}
                      camera={zoneCamera(rule.zone)?.name}
                      onChange={(patch) => updateRule(rule.id, patch)}
                    />
                  ))}
                  {result.unsupported.map((u, i) => (
                    <div
                      key={`${compileCount}-${u}`}
                      className="rise flex flex-col gap-2 rounded-lg border border-dashed border-line p-4"
                      style={{ '--d': `${(rules.length + i) * 110}ms` } as React.CSSProperties}
                    >
                      <span className="label">Can't watch for this</span>
                      <span className="text-[14px] leading-5 text-muted">{u}</span>
                    </div>
                  ))}
                </div>
                {result.warnings.map((w) => (
                  <p key={w} className="text-[14px] text-muted">
                    <span className="label mr-2 text-text">Note</span>
                    {w}
                  </p>
                ))}
              </div>
            )}

            <div className="flex items-center justify-between gap-6">
              <span className="text-[14px] text-muted">{error}</span>
              <button className="btn-primary" onClick={start} disabled={starting || rules.filter((r) => r.enabled).length === 0}>
                {starting ? 'starting…' : 'start watching'} <Arrow />
              </button>
            </div>
          </section>
        </div>
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

function RuleCard({
  rule,
  zone,
  camera,
  delay,
  onChange,
}: {
  rule: Rule
  zone: string
  camera?: string
  delay: number
  onChange: (p: Partial<Rule>) => void
}) {
  const urgent = rule.severity === 'urgent'
  const base = urgent ? 'bg-accent text-accent-ink' : 'bg-panel text-text border border-line'
  const sub = urgent ? 'text-accent-ink/70' : 'text-muted'
  return (
    <div
      className={`rise flex flex-col gap-3 rounded-lg p-4 transition-[filter] duration-300 ${base} ${rule.enabled ? '' : 'opacity-60 grayscale'}`}
      style={{ '--d': `${delay}ms` } as React.CSSProperties}
    >
      <span className={`font-mono text-[11px] font-medium uppercase tracking-label ${sub}`}>
        {camera ?? zone} · {rule.severity}
      </span>
      <div className="flex flex-col gap-1">
        <span className="text-[16px] font-semibold leading-5">{rule.name}</span>
        <span className={`text-[13px] leading-[18px] ${sub}`}>{ruleCondition(rule)}</span>
      </div>
      <div className={`mt-auto flex items-center gap-2 text-[13px] ${sub}`}>
        {rule.type === 'persistent_object' && (
          <label className="flex items-center gap-1">
            <input
              type="number"
              min={1}
              step={0.5}
              value={rule.duration_seconds}
              onChange={(e) => onChange({ duration_seconds: Number(e.target.value) || 1 })}
              className="w-12 rounded bg-black/15 px-1.5 py-1 text-center font-mono outline-none"
              aria-label="Seconds before alerting"
            />
            s
          </label>
        )}
        <select
          value={rule.severity}
          onChange={(e) => onChange({ severity: e.target.value as Severity })}
          className="rounded bg-black/15 px-1.5 py-1 outline-none"
          aria-label="Severity"
        >
          <option value="info">info</option>
          <option value="review">review</option>
          <option value="urgent">urgent</option>
        </select>
        <button className="ml-auto underline-offset-2 hover:underline" onClick={() => onChange({ enabled: !rule.enabled })}>
          {rule.enabled ? 'on' : 'off'}
        </button>
      </div>
    </div>
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
  return (
    <form onSubmit={submit} className="flex flex-col gap-2">
      <input className="field" placeholder="Name, e.g. Side door" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      <input className="field font-mono text-[13px]" placeholder="webcam:1 or http://phone-ip:8080/video" value={source} onChange={(e) => setSource(e.target.value)} />
      <div className="flex gap-2">
        <button type="button" className="btn-quiet" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn-quiet bg-[#F1EEE6] text-black hover:bg-white">Connect</button>
      </div>
    </form>
  )
}

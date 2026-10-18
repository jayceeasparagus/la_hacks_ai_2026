// Mock backend on :8000 so the frontend can be built before the FastAPI app exists.
// Implements the routes in src/api.ts with canned data and a scripted demo loop:
// a review alert at the entrance, then an exit obstruction timer that ticks 0 -> 5 s
// and fires an urgent alert at 5.4 s. The loop repeats every 40 s.
// Run with: npm run mock
import express from 'express'
import { createServer } from 'node:http'
import { WebSocketServer } from 'ws'

const PORT = 8000
const CYCLE_SECONDS = 40

let cameras = [
  { id: 'cam_entrance', name: 'Main entrance', source: 'webcam:0' },
  // webcam:1 falls back to the default camera in the browser if there is only one
  { id: 'cam_exit', name: 'Emergency exit', source: 'webcam:1' },
]

let zones = [
  { id: 'main_entrance', name: 'Main entrance', camera_id: 'cam_entrance', polygon: [[0.12, 0.45], [0.88, 0.45], [0.95, 0.98], [0.05, 0.98]] },
  { id: 'emergency_exit', name: 'Emergency exit', camera_id: 'cam_exit', polygon: [[0.36, 0.62], [0.66, 0.62], [0.76, 0.96], [0.27, 0.96]] },
]

const compiledRules = [
  {
    id: 'clear_bag', name: 'Bags should be clear', type: 'object_attribute',
    objects: ['backpack', 'handbag', 'suitcase'], zone: 'main_entrance',
    attribute: { name: 'transparent', expected: true }, duration_seconds: 1, severity: 'review', enabled: true,
  },
  {
    id: 'pro_camera', name: 'Pro cameras need review', type: 'object_attribute',
    objects: ['camera'], zone: 'main_entrance',
    attribute: { name: 'professional', expected: false }, duration_seconds: 1, severity: 'review', enabled: true,
  },
  {
    id: 'blocked_exit', name: 'Keep the exit clear', type: 'persistent_object',
    objects: ['backpack', 'handbag', 'suitcase', 'chair'], zone: 'emergency_exit',
    attribute: null, duration_seconds: 5, severity: 'urgent', enabled: true,
  },
]

let policy = { text: '', rules: compiledRules }
let alerts = []
let monitoring = false
let cycleStart = Date.now()
let cycleCount = 0

const app = express()
app.use(express.json())

// Tells the frontend it may show this browser's webcam for webcam:N sources.
app.get('/api/info', (_req, res) => res.json({ mock: true }))

app.get('/api/cameras', (_req, res) => res.json(cameras))
app.put('/api/cameras', (req, res) => {
  cameras = req.body
  res.json(cameras)
})

app.get('/api/zones', (_req, res) => res.json(zones))
app.put('/api/zones', (req, res) => {
  zones = req.body
  res.json(zones)
})

app.post('/api/policy/compile', (req, res) => {
  const text = String(req.body?.text ?? '').toLowerCase()
  const unsupported = []
  const warnings = []
  if (/weapon|gun|knife/.test(text)) {
    unsupported.push('Concealed weapons: cameras cannot see inside bags or under clothing, so this cannot be monitored.')
  }
  if (/face|recogni|identify/.test(text)) {
    unsupported.push('Identifying people: face recognition is never used.')
  }
  if (text.includes('exit') && !zones.some((z) => z.id === 'emergency_exit')) {
    warnings.push('No zone named "emergency exit" yet. Draw one on the exit camera.')
  }
  setTimeout(() => res.json({ rules: compiledRules, warnings, unsupported }), 900)
})

app.put('/api/policy', (req, res) => {
  policy = req.body
  res.status(204).end()
})

app.post('/api/monitor/start', (_req, res) => {
  if (!monitoring) {
    monitoring = true
    cycleStart = Date.now()
  }
  res.status(204).end()
})
app.post('/api/monitor/stop', (_req, res) => {
  monitoring = false
  res.status(204).end()
})

app.get('/api/alerts', (_req, res) => res.json([...alerts].sort((a, b) => b.created_at - a.created_at)))
app.post('/api/alerts/:id/decision', (req, res) => {
  const alert = alerts.find((a) => a.id === req.params.id)
  if (!alert) return res.status(404).json({ detail: 'alert not found' })
  const map = { confirm: 'confirmed', dismiss: 'dismissed', unclear: 'unclear' }
  alert.status = map[req.body?.decision] ?? alert.status
  broadcast({ type: 'alert_update', alert })
  res.json(alert)
})

// Stand-in camera frames: grainy grayscale SVG scenes. The real backend serves MJPEG
// at the same URL, and <img> renders either.
app.get(['/api/stream/:id', '/api/snapshot/:id'], (req, res) => {
  res.type('image/svg+xml').send(sceneSvg(req.params.id))
})
app.get('/evidence/:file', (req, res) => {
  const cam = req.params.file.startsWith('cam_exit') ? 'cam_exit' : 'cam_entrance'
  res.type('image/svg+xml').send(sceneSvg(cam))
})

function sceneSvg(cameraId) {
  const isExit = cameraId === 'cam_exit'
  const isEntrance = cameraId === 'cam_entrance'
  const t = (Date.now() - cycleStart) / 1000
  const bagInExit = monitoring && isExit && t > 3 && t < 14
  return `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
  <defs>
    <radialGradient id="g" cx="48%" cy="40%" r="75%"><stop offset="0" stop-color="#4b4b4a"/><stop offset="0.6" stop-color="#242423"/><stop offset="1" stop-color="#101010"/></radialGradient>
    <filter id="n"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="${cameraId.length}"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.18"/></feComponentTransfer></filter>
  </defs>
  <rect width="960" height="540" fill="url(#g)"/>
  <path d="M0 330 L960 310 L960 540 L0 540 Z" fill="#1b1b1a"/>
  ${isExit ? `<rect x="400" y="90" width="170" height="232" fill="#0d0d0d" stroke="#3a3a3a" stroke-width="3"/><rect x="440" y="58" width="90" height="22" fill="#2c2c2c"/>` : ''}
  ${isEntrance ? `<rect x="120" y="70" width="300" height="250" fill="#161616" stroke="#333" stroke-width="3"/><rect x="540" y="70" width="300" height="250" fill="#161616" stroke="#333" stroke-width="3"/><rect x="455" y="150" width="46" height="150" rx="20" fill="#2e2e2e"/><circle cx="478" cy="128" r="22" fill="#2e2e2e"/>` : ''}
  ${bagInExit ? `<path d="M450 470 Q448 402 487 396 Q527 402 525 470 Z" fill="#3b3b3b"/><rect x="462" y="420" width="52" height="30" rx="6" fill="#4a4a4a"/>` : ''}
  <rect width="960" height="540" filter="url(#n)"/>
</svg>`
}

const server = createServer(app)
const wss = new WebSocketServer({ server, path: '/ws' })
const broadcast = (msg) => {
  const data = JSON.stringify(msg)
  for (const client of wss.clients) if (client.readyState === 1) client.send(data)
}

function makeAlert(fields) {
  const alert = {
    id: `al_${cycleCount}_${fields.rule_id}`,
    created_at: Date.now() / 1000,
    status: 'open',
    evidence_clip: null,
    ...fields,
  }
  alerts.push(alert)
  broadcast({ type: 'alert', alert })
}

let firedThisCycle = new Set()

setInterval(() => {
  const now = Date.now()
  let t = (now - cycleStart) / 1000
  if (monitoring && t >= CYCLE_SECONDS) {
    cycleStart = now
    cycleCount += 1
    firedThisCycle = new Set()
    t = 0
  }

  for (const cam of cameras) {
    const ruleStates = []
    if (monitoring && cam.id === 'cam_exit' && t > 3 && t < 14) {
      ruleStates.push({
        rule_id: 'blocked_exit', camera_id: cam.id, track_id: 14 + cycleCount, class_name: 'backpack',
        elapsed_seconds: Math.round((t - 3) * 10) / 10, duration_seconds: 5, bbox: [0.46, 0.72, 0.55, 0.88],
      })
    }
    broadcast({
      type: 'state',
      camera: { camera_id: cam.id, online: true, fps: monitoring ? 14.6 + Math.random() * 0.6 : 0 },
      rule_states: ruleStates,
    })
  }

  if (!monitoring) return
  if (t > 2 && !firedThisCycle.has('clear_bag')) {
    firedThisCycle.add('clear_bag')
    makeAlert({
      camera_id: 'cam_entrance', rule_id: 'clear_bag', rule_name: 'Bags should be clear', track_id: 9 + cycleCount,
      severity: 'review', title: 'Bag is probably not clear',
      observation: 'A handbag at the main entrance looks opaque. Worth a quick look.',
      confidence: 0.78, evidence_image: `/evidence/cam_entrance_${cycleCount}.svg`, bbox: [0.5, 0.42, 0.58, 0.58],
    })
  }
  if (t > 8.4 && !firedThisCycle.has('blocked_exit')) {
    firedThisCycle.add('blocked_exit')
    makeAlert({
      camera_id: 'cam_exit', rule_id: 'blocked_exit', rule_name: 'Keep the exit clear', track_id: 14 + cycleCount,
      severity: 'urgent', title: 'Possible blocked exit',
      observation: 'A backpack has probably been sitting in the exit doorway for 5.4 seconds.',
      confidence: 0.91, evidence_image: `/evidence/cam_exit_${cycleCount}.svg`, bbox: [0.46, 0.72, 0.55, 0.88],
    })
  }
}, 200)

server.listen(PORT, () => console.log(`mock backend on http://localhost:${PORT}`))

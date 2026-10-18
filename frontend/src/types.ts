// Mirrors backend/app/models.py. DRAFT: app/models.py and contracts/ are not on main yet,
// so Camera, Zone, Rule, CompileResult and Verdict copy Person 2's temporary models
// (backend/policy/contracts.py), TrackFrame copies Person 1's draft, and Alert, RuleState
// and the WebSocket messages follow the role docs. Update this file when Person 4 lands
// the real contracts; never rename fields here on our own.

export type Severity = 'info' | 'review' | 'urgent'
export type RuleType = 'object_attribute' | 'persistent_object'
export type AttributeName = 'transparent' | 'professional'

export interface Camera {
  id: string
  name: string
  source: string // "webcam:0", a phone stream URL, or a clip path
}

export interface Zone {
  id: string
  name: string
  camera_id: string
  polygon: [number, number][] // normalized 0..1, origin top-left
}

export interface Attribute {
  name: AttributeName
  expected: boolean
}

export interface Rule {
  id: string
  name: string
  type: RuleType
  objects: string[]
  zone: string // zone id
  attribute: Attribute | null
  duration_seconds: number
  severity: Severity
  enabled: boolean
}

export interface CompileResult {
  rules: Rule[]
  warnings: string[]
  unsupported: string[]
}

export interface Track {
  track_id: number
  class_name: string
  conf: number
  bbox: [number, number, number, number] // x1, y1, x2, y2 normalized
}

export type AlertStatus = 'open' | 'confirmed' | 'dismissed' | 'unclear'
export type Decision = 'confirm' | 'dismiss' | 'unclear'

export interface Alert {
  id: string
  camera_id: string
  rule_id: string
  rule_name: string
  track_id: number
  severity: Severity
  title: string // hedged, e.g. "Possible blocked exit"
  observation: string
  confidence: number // 0..1
  created_at: number // unix seconds
  evidence_image: string | null // URL under /evidence
  evidence_clip: string | null
  bbox: [number, number, number, number] | null
  status: AlertStatus
}

// Live progress of a rule on one track, e.g. a bag 3.2 s into a 5 s exit timer.
export interface RuleState {
  rule_id: string
  camera_id: string
  track_id: number
  class_name: string
  elapsed_seconds: number
  duration_seconds: number
  bbox: [number, number, number, number] | null
}

export interface CameraStatus {
  camera_id: string
  online: boolean
  fps: number
}

export type WsMessage =
  | { type: 'state'; camera: CameraStatus; rule_states: RuleState[] }
  | { type: 'alert'; alert: Alert }
  | { type: 'alert_update'; alert: Alert }

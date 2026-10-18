// Mirrors backend/app/models.py and contracts/api.md (the approved contracts). Never rename
// fields here on our own: change the contract first, then this file.

export type Severity = 'review' | 'urgent'
export type RuleType = 'object_attribute' | 'persistent_object'
export type AttributeName = 'transparent' | 'professional' | 'hard_hat' | 'safety_vest'
export type BBox = [number, number, number, number] // x1, y1, x2, y2 normalized 0..1

export interface Camera {
  id: string
  name: string
  source: string // "webcam:0", "url:<stream>", "clip:<path>", "synthetic:<scene>" or "replay:<tracks>"
}

export interface Zone {
  id: string
  camera_id: string
  name: string
  polygon: [number, number][] // normalized 0..1, origin top-left, at least 3 points
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

export type AlertStatus = 'open' | 'reviewed'
export type Decision = 'confirmed' | 'dismissed' | 'unclear'
export type EvidenceStatus = 'pending' | 'ready' | 'unavailable'

export interface Alert {
  id: string
  incident_id: string
  camera_id: string
  rule_id: string
  rule_name: string
  zone_id: string
  track_id: number
  object_class: string
  bbox: BBox
  ts: number // source-relative seconds
  created_at: string // UTC RFC3339
  elapsed_seconds: number
  severity: Severity
  title: string // hedged, e.g. "Possible exit obstruction"
  observation: string
  confidence: number // 0..1
  rule_snapshot: Rule
  evidence_status: EvidenceStatus
  evidence_image_url: string | null
  evidence_clip_url: string | null
  status: AlertStatus
  decision: Decision | null
  decided_at: string | null
}

export type RulePhase = 'timing' | 'verifying' | 'alerted' | 'compliant' | 'cleared'

// Live progress of a rule on one track, e.g. a bag 3.2 s into a 5 s exit timer. Boxes and
// labels are drawn on the backend's annotated stream, so states carry no geometry.
export interface RuleState {
  camera_id: string
  rule_id: string
  track_id: number
  incident_id: string
  ts: number
  elapsed_seconds: number
  duration_seconds: number
  phase: RulePhase
}

export interface CameraStatus {
  camera_id: string
  status: 'online' | 'offline' | 'connecting'
  fps: number
  last_frame_ts: number | null
  error: string | null
}

// Server -> client messages on /ws: always {type, data}.
export type WsMessage =
  | { type: 'snapshot'; data: { running: boolean; cameras: CameraStatus[]; rule_states: RuleState[] } }
  | { type: 'camera_status'; data: CameraStatus }
  | { type: 'state'; data: { camera_id: string; ts: number; rule_states: RuleState[] } }
  | { type: 'alert'; data: Alert }
  | { type: 'alert_updated'; data: Alert }
  | { type: 'monitor_status'; data: { running: boolean } }

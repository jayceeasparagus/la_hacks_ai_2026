// Evidence recorded in this browser (testing against the mock with a local webcam), kept per
// alert. The still frame survives a reload via sessionStorage; the short clip lives in memory
// for this page only, since a few seconds of frames is too big to store.
const KEY = 'policylens.evidence'
const MAX_STILLS = 24 // oldest alerts drop off first, keeping well under the storage limit

export interface Clip {
  frames: string[]
  detectAt: number // index of the frame where the rule fired
}

const clips = new Map<string, Clip>()

function readStills(): Record<string, string> {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? '{}')
  } catch {
    return {}
  }
}

export function saveStill(alertId: string, dataUrl: string) {
  const stills = readStills()
  stills[alertId] = dataUrl
  const ids = Object.keys(stills)
  for (const id of ids.slice(0, Math.max(0, ids.length - MAX_STILLS))) delete stills[id]
  try {
    sessionStorage.setItem(KEY, JSON.stringify(stills))
  } catch {
    // storage full: the still just won't survive a reload
  }
}

export function loadStill(alertId: string): string | null {
  return readStills()[alertId] ?? null
}

export function saveClip(alertId: string, clip: Clip) {
  clips.set(alertId, clip)
}

export function loadClip(alertId: string): Clip | undefined {
  return clips.get(alertId)
}

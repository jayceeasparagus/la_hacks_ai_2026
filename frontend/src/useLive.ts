// WebSocket connection to /ws: live camera status, rule progress and new alerts.
// Messages follow contracts/api.md ({type, data}). A `snapshot` arrives on every (re)connect,
// so state is rebuilt from it; reconnects use backoff so a backend restart never needs a reload.
import { useEffect, useRef, useState } from 'react'
import type { Alert, CameraStatus, RuleState, WsMessage } from './types'

export interface LiveState {
  connected: boolean
  running: boolean
  cameras: Record<string, CameraStatus>
  ruleStates: Record<string, RuleState[]> // keyed by camera_id, finished ('cleared') states dropped
}

const active = (states: RuleState[]) => states.filter((s) => s.phase !== 'cleared')

function byCamera(states: RuleState[]): Record<string, RuleState[]> {
  const out: Record<string, RuleState[]> = {}
  for (const s of active(states)) (out[s.camera_id] ??= []).push(s)
  return out
}

export function useLive(onAlert: (alert: Alert, isUpdate: boolean) => void, onReconnect?: () => void): LiveState {
  const [state, setState] = useState<LiveState>({ connected: false, running: false, cameras: {}, ruleStates: {} })
  const onAlertRef = useRef(onAlert)
  onAlertRef.current = onAlert
  const onReconnectRef = useRef(onReconnect)
  onReconnectRef.current = onReconnect

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry = 0
    let opened = false
    let timer: number | undefined
    let closed = false

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      ws.onopen = () => {
        retry = 0
        setState((s) => ({ ...s, connected: true }))
        // socket delivery isn't the record: after a reconnect, reload alerts over REST
        if (opened) onReconnectRef.current?.()
        opened = true
      }
      ws.onmessage = (event) => {
        let msg: WsMessage
        try {
          msg = JSON.parse(event.data)
        } catch {
          return
        }
        switch (msg.type) {
          case 'snapshot':
            setState((s) => ({
              ...s,
              running: msg.data.running,
              cameras: Object.fromEntries(msg.data.cameras.map((c) => [c.camera_id, c])),
              ruleStates: byCamera(msg.data.rule_states),
            }))
            break
          case 'camera_status':
            setState((s) => ({ ...s, cameras: { ...s.cameras, [msg.data.camera_id]: msg.data } }))
            break
          case 'state':
            setState((s) => ({ ...s, ruleStates: { ...s.ruleStates, [msg.data.camera_id]: active(msg.data.rule_states) } }))
            break
          case 'monitor_status':
            setState((s) => ({ ...s, running: msg.data.running, ...(msg.data.running ? {} : { ruleStates: {} }) }))
            break
          case 'alert':
          case 'alert_updated':
            onAlertRef.current(msg.data, msg.type === 'alert_updated')
            break
        }
      }
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }))
        if (closed) return
        const delay = Math.min(8000, 500 * 2 ** retry++)
        timer = window.setTimeout(connect, delay)
      }
      ws.onerror = () => ws?.close()
    }

    connect()
    return () => {
      closed = true
      window.clearTimeout(timer)
      ws?.close()
    }
  }, [])

  return state
}

// WebSocket connection to /ws: live camera status, rule progress and new alerts.
// Reconnects automatically with backoff so a backend restart never needs a page reload.
import { useEffect, useRef, useState } from 'react'
import type { Alert, CameraStatus, RuleState, WsMessage } from './types'

export interface LiveState {
  connected: boolean
  cameras: Record<string, CameraStatus>
  ruleStates: Record<string, RuleState[]> // keyed by camera_id
}

export function useLive(onAlert: (alert: Alert, isUpdate: boolean) => void): LiveState {
  const [state, setState] = useState<LiveState>({ connected: false, cameras: {}, ruleStates: {} })
  const onAlertRef = useRef(onAlert)
  onAlertRef.current = onAlert

  useEffect(() => {
    let ws: WebSocket | null = null
    let retry = 0
    let timer: number | undefined
    let closed = false

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      ws.onopen = () => {
        retry = 0
        setState((s) => ({ ...s, connected: true }))
      }
      ws.onmessage = (event) => {
        let msg: WsMessage
        try {
          msg = JSON.parse(event.data)
        } catch {
          return
        }
        if (msg.type === 'state') {
          const { camera, rule_states } = msg
          setState((s) => ({
            ...s,
            cameras: { ...s.cameras, [camera.camera_id]: camera },
            ruleStates: { ...s.ruleStates, [camera.camera_id]: rule_states },
          }))
        } else if (msg.type === 'alert' || msg.type === 'alert_update') {
          onAlertRef.current(msg.alert, msg.type === 'alert_update')
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

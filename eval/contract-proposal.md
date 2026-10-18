# Archived initial contract proposal — approved 2026-10-17

This historical draft has been approved. The active definitions now live in
`backend/app/models.py` and `contracts/api.md`. Use those files, not this draft.

No shared contracts exist in this checkout yet. `CLAUDE.md` requires approval for
contract changes. This document and `eval/proposals/models.py` are drafts for
review; no runtime code imports them. After approval, publish the models under
`backend/app/models.py` and the interface documentation and examples in `contracts/`.

## Decisions to approve

1. **Coordinates:** every zone vertex and bounding box uses normalized `[0, 1]`
   coordinates. Boxes are `[x1, y1, x2, y2]`. The bottom-center determines zone
   membership; a point exactly on an edge counts as inside. Polygon configuration
   must reject zero-area and self-intersecting shapes before monitoring.
2. **Camera ownership:** globally unique zone IDs reference one `camera_id`.
   `Rule.zone` references that zone ID (preserving the existing documented name).
   Track IDs are integers unique within one camera session, never across cameras.
3. **Time:** `TrackFrame.ts` is monotonic source-relative seconds. Recorded video
   uses frame index / source FPS; live video uses monotonic seconds since session
   start. Alert `ts` uses the same clock; `created_at` is a UTC RFC3339 timestamp.
   Rewind/reconnect starts a fresh tracking session and resets engine state;
   persisted alerts remain intact. Session reset must also invalidate pending
   verifier jobs so old results cannot appear in the new session.
4. **Rules:** retain `id`, `type`, `objects`, `zone`, `attribute`,
   `duration_seconds`, `severity`; add the display `name` and `enabled` flag needed
   by the frontend. `transparent.expected=true` and `professional.expected=false`.
   Person-down and arbitrary exception conditions remain unsupported.
5. **Verifier:** `Verdict.answer` is strictly `true`, `false`, or `null`.
   Person 2 converts provider `yes/no/unclear` output into these values.
   `null` creates a manual-review alert, never a confirmed violation.
6. **Incident identity:** each new entry after a closed incident gets a fresh
   `incident_id`. Dedup keys include camera, rule and incident, with track IDs
   maintained inside the incident. This supports ID recovery and re-entry.
7. **Timer behavior:** elapsed time is source time since entry, bridging missing
   detections up to 1.0 s. An alert requires an observed in-zone frame at or after
   the threshold, never only missing frames. Longer absence resets the pending
   timer; an alerted incident stays deduplicated until 2.0 s outside/missing.
   Explicitly observed outside-zone time resets a pending timer immediately.
   Unambiguous same-class ID changes within 1.0 s and IoU >= 0.5 may inherit it;
   never merge two simultaneously observed objects. Exactly 1.0 s is tolerated;
   exactly 2.0 s closes. These tolerances are demo heuristics, not proof of unseen
   presence.
8. **Evidence and review:** evidence may be pending, ready or unavailable. An
   urgent alert appears before encoding finishes. Evidence completion updates the
   same alert. Save its rule snapshot, source camera and original observation.
   Human decisions are `confirmed`, `dismissed`, or `unclear`; all mark the alert
   reviewed. Closing an incident is separate from reviewing its alert.

## Proposed HTTP API

All payloads are JSON unless noted. Collection endpoints return objects, not bare
arrays. Validate the entire request before changing configuration. Unknown fields
and invalid values return 422. Referenced unknown cameras/zones are rejected.
Conflicting duplicate IDs or configuration changes while monitoring return 409.
Missing resources return 404. Camera count is capped at three.

| Method | Path | Request | Successful response |
| --- | --- | --- | --- |
| GET | `/api/health` | — | `{status: "ok"}` |
| GET | `/api/cameras` | — | `{cameras: Camera[]}` |
| PUT | `/api/cameras` | `{cameras: Camera[]}` | Same object; replaces entire list |
| GET | `/api/snapshot/{camera_id}` | — | JPEG; 503 if unavailable |
| GET | `/api/stream/{camera_id}` | — | MJPEG stream |
| GET | `/api/zones` | — | `{zones: Zone[]}` |
| PUT | `/api/zones` | `{zones: Zone[]}` | Same object; replaces entire list |
| POST | `/api/policy/compile` | `{prompt: string}` | `CompileResult`; uses saved zones, does not activate |
| GET | `/api/policy` | — | `{rules: Rule[]}` |
| PUT | `/api/policy` | `{rules: Rule[]}` | Same object; activates validated edited rules |
| POST | `/api/monitor/start` | Empty body | `{running: true}`; idempotent |
| POST | `/api/monitor/stop` | Empty body | `{running: false}`; idempotent |
| GET | `/api/monitor` | — | `{running: boolean, cameras: CameraStatus[]}` |
| GET | `/api/alerts` | Optional `camera_id`, `status=open\|reviewed`, `limit`, `offset` | `{alerts: Alert[], total: integer}` |
| GET | `/api/alerts/{id}` | — | `Alert` |
| POST | `/api/alerts/{id}/decision` | `{decision: "confirmed"\|"dismissed"\|"unclear"}` | Updated `Alert` |
| GET | `/evidence/{filename}` | — | Image/video; safe generated basename only |

`CameraStatus` is `{camera_id, status: "online"|"offline"|"connecting", fps,
last_frame_ts: number|null, error: string|null}`. Do not include credentials from
camera URLs in errors or logs. Decision writes retain an audit record; repeating
the same decision is idempotent.

Configuration edits require stopping monitoring for the MVP. Settings persist as
JSON; alerts and decision history persist in SQLite. No authentication or external
notification routes are included.

## Proposed WebSocket API: `/ws`

Server sends `{type, data}` messages:

- `snapshot`: `{running, cameras: CameraStatus[], rule_states: RuleState[]}`
  on connection, so reconnecting clients can reconstruct current state.
- `camera_status`: one `CameraStatus`.
- `state`: `{camera_id, ts, rule_states: RuleState[]}`; complete replacement for
  that camera. Empty list clears its indicators. Throttle UI updates independently
  of engine processing.
- `alert`: a newly created `Alert`.
- `alert_updated`: the complete updated `Alert` for evidence or review changes.
- `monitor_status`: `{running: boolean}`.

Clients reload the alert list via REST after reconnecting. Socket delivery is not
the persistence mechanism. Slow clients must never block camera workers.

## Module boundaries

- Person 1: `VisionPipeline(camera).frames()` yields `(frame, TrackFrame)`;
  per-camera models/trackers; `recent_frames(seconds)` supplies evidence frames.
  `crop(frame, bbox, pad=0.15)` accepts the normalized box and converts to pixels.
- Person 2: `compile_policy(prompt, zones) -> CompileResult` and
  `verify_crop(crop, check) -> Verdict`; checks are `transparent_bag` and
  `professional_camera`.
- Person 4: `RuleEngine(camera_id, zones, rules, ...).update(frame, tf)` returns
  `(list[RuleState], list[Alert])`. Asynchronous completions are polled each update
  and can also be drained when a replay ends. One shared verification scheduler
  owns the global two-calls-per-second limit. Full reset discards stale jobs.
- Person 3 mirrors the approved models in TypeScript and consumes the API above.

## Approval checkpoint

Review `eval/proposals/models.py` plus this proposal. The most consequential
choices for teammates are normalized boxes, `Track.object_class`, source-relative
`ts`, boolean/null verdicts, and the `{type, data}` WebSocket envelope.
Do not promote these drafts into the shared runtime contracts before approval.

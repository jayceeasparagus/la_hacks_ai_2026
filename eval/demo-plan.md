# Person 4 demo and integration checklist

## Ninety-second demonstration

1. **0–20 s: policy.** Enter the documented entrance/exit policy. Show the three
   interpreted rules and explicitly confirm them. In offline mode point out the
   DEMO compiler warning; don't describe the mapping as real Gemini reasoning.
2. **20–35 s: normal behavior.** In the recorded CLI fallback, select clear-bag
   and ordinary-camera canned verdicts. Show zero alerts and say the results are
   a functional test, not classification from the synthetic pictures.
3. **35–55 s: review.** Show an opaque-bag review alert with its camera, rule,
   image and short clip. Confirm or dismiss it and demonstrate that the decision
   remains after an evidence update and backend restart.
4. **55–75 s: temporal reasoning.** Place a bag in the marked exit zone, show
   progress toward five seconds, then exactly one urgent incident. A brief pass
   should stay quiet. In offline mode use the visibly synthetic exit recording.
5. **75–90 s: judgment.** Compile a concealed-object request and show the honest
   unsupported explanation. Explain that an operator decides what to do.

Pitch: **PolicyLens lets organizers program cameras with the rules of their space.
It turns those rules into observable checks, tracks events over time, and brings
evidence to a human who makes the decision.**

## Checkpoints before the final submission

- **Backend checkpoint (implemented):** contracts, engine, storage, API, streaming,
  WebSocket, fake cameras, evidence and a reproducible functional evaluation.
- **Person 1 integration:** load real vision modules; verify normalized tracks,
  stable IDs, live source timestamps, FPS for two cameras and source recovery.
- **Person 2 integration:** run real policy compilation and crop checks, verify
  fallback/unclear paths, and measure actual provider latency and accuracy.
- **Person 3 integration:** run the frontend against port 8000, draw zones from a
  setup snapshot, edit rules, review evidence and reconnect the WebSocket.
- **Full-product rehearsal:** five minutes with actual cameras, representative
  lighting and the UI. The synthetic backend soak is not a substitute for this.
- **Freeze and record:** record the 90-second UI demonstration only after these
  integrations work. Keep recorded real-footage clips and a clearly labeled saved
  demonstration as fallback; do not present canned results as live inference.

No notifications, authentication, cross-camera identity or person-down extension
is needed for the core demonstration. Final UI footage and hardware/model
evaluation remain integration work; no submission video has been claimed here.

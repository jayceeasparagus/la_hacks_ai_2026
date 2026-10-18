# WatchDog frontend

Vite + React + TypeScript + Tailwind. Three screens: landing, setup (cameras, zones, policy,
rule review) and watch (live feeds plus the alert sidebar).

## Run

```
npm install
npm run demo   # mock backend on :8000 + dev server on http://localhost:5173
```

Or run them separately: `npm run mock` and `npm run dev`. Once the FastAPI app is running on
:8000, use `npm run dev` alone. If the dev server logs `ECONNREFUSED ...:8000`, nothing is
running on :8000.

Against the mock, cameras with source `webcam:N` show this browser's webcam (allow camera
access when asked). Against the real backend they show its annotated MJPEG stream.

Vite proxies `/api`, `/ws` and `/evidence` to `:8000`, so the same code talks to the mock or
the real backend.

The mock runs a 40 s demo loop after "start watching": a review alert at the entrance at
about 2 s, then the exit timer ticks 0 -> 5 s and fires an urgent alert at 5.4 s.

## Files

- `src/types.ts` mirrors `backend/app/models.py` (draft until the contracts land).
- `src/api.ts` holds every REST call; `src/useLive.ts` is the auto-reconnecting WebSocket.
- `mock/server.mjs` implements the routes with canned data.

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

declare const process: { env: Record<string, string | undefined> }

// The mock server and the real FastAPI backend both listen on :8000,
// so switching between them needs no code changes. 127.0.0.1 rather than localhost: Node may
// resolve localhost to IPv6 (::1), and uvicorn only listens on IPv4 by default.
const backendPort = process.env.BACKEND_PORT ?? '8000' // override to run a second copy side by side
const backend = `http://127.0.0.1:${backendPort}`

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/evidence': backend,
      '/ws': { target: `ws://127.0.0.1:${backendPort}`, ws: true },
    },
  },
})

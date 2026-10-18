// Three screens: landing -> setup (connect cameras, write the policy, review rules) -> watch,
// plus the live demo (type a policy, watch it apply to the example cameras at once).
// The screen lives in the URL hash so a refresh keeps you where you were.
import { useEffect, useState } from 'react'
import Demo from './pages/Demo'
import Landing from './pages/Landing'
import Setup from './pages/Setup'
import Watch from './pages/Watch'

export type Page = 'landing' | 'setup' | 'watch' | 'demo'

const fromHash = (): Page => {
  const h = location.hash.replace('#/', '')
  return h === 'setup' || h === 'watch' || h === 'demo' ? h : 'landing'
}

export default function App() {
  const [page, setPage] = useState<Page>(fromHash)

  useEffect(() => {
    const onHash = () => setPage(fromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const go = (next: Page) => {
    location.hash = next === 'landing' ? '' : `#/${next}`
    setPage(next)
    window.scrollTo(0, 0)
  }

  if (page === 'setup') return <Setup go={go} />
  if (page === 'watch') return <Watch go={go} />
  if (page === 'demo') return <Demo go={go} />
  return <Landing go={go} />
}

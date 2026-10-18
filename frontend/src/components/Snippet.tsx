// A few seconds of footage around an alert, played as a loop. A thin timeline underneath
// marks the moment the rule fired, so the operator sees what happened just before it.
import { useEffect, useState } from 'react'
import { snippetFps } from '../localCamera'

const HOLD_FRAMES = 3 // pause briefly on the last frame before looping

export default function Snippet({ frames, detectAt }: { frames: string[]; detectAt: number }) {
  const [i, setI] = useState(0)

  useEffect(() => {
    const t = window.setInterval(() => setI((n) => (n + 1) % (frames.length + HOLD_FRAMES)), 1000 / snippetFps)
    return () => window.clearInterval(t)
  }, [frames.length])

  const shown = Math.min(i, frames.length - 1)
  const secondsFromAlert = (shown - detectAt) / snippetFps

  return (
    <>
      <img src={frames[shown]} alt="Footage around the alert" className="h-full w-full object-cover" />
      <span className="absolute left-2 top-2 rounded-sm bg-black/60 px-1.5 py-0.5 font-mono text-[10px] tracking-label text-text">
        {secondsFromAlert >= 0 ? '+' : '−'}
        {Math.abs(secondsFromAlert).toFixed(1)} s
      </span>
      <div className="absolute inset-x-2 bottom-2 h-[3px] rounded-full bg-white/20">
        <div className="h-full rounded-full bg-[#F1EEE6]" style={{ width: `${((shown + 1) / frames.length) * 100}%` }} />
        <div className="absolute -top-[3px] h-[9px] w-[2px] bg-accent" style={{ left: `${(detectAt / frames.length) * 100}%` }} />
      </div>
    </>
  )
}

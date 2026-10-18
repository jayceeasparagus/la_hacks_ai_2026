// Faint, fixed starfield behind a page. Seeded so it looks the same on every load.
import { useMemo } from 'react'

function seeded(seed: number) {
  let s = seed
  return () => {
    s = (s * 16807) % 2147483647
    return s / 2147483647
  }
}

export default function Stars({ count = 140, seed = 7 }: { count?: number; seed?: number }) {
  const stars = useMemo(() => {
    const rand = seeded(seed)
    return Array.from({ length: count }, () => {
      const bright = rand() < 0.07
      return {
        x: rand() * 100,
        y: rand() * 100,
        r: bright ? 1.2 + rand() * 0.6 : 0.4 + rand() * 0.6,
        o: bright ? 0.6 + rand() * 0.3 : 0.15 + rand() * 0.45,
        bright,
      }
    })
  }, [count, seed])

  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
      {stars.map((s, i) => (
        <g key={i}>
          {s.bright && <circle cx={`${s.x}%`} cy={`${s.y}%`} r={s.r * 3} fill="#8FB2FF" fillOpacity={0.08} />}
          <circle cx={`${s.x}%`} cy={`${s.y}%`} r={s.r} fill="#F1EEE6" fillOpacity={s.o} />
        </g>
      ))}
    </svg>
  )
}

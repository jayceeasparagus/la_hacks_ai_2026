export function relativeTime(unixSeconds: number, now = Date.now() / 1000): string {
  const s = Math.max(0, Math.round(now - unixSeconds))
  if (s < 10) return 'just now'
  if (s < 60) return `${s} s ago`
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  return `${Math.round(m / 60)} h ago`
}

export function clock(date = new Date()): string {
  return date.toLocaleTimeString([], { hour12: false })
}

export function percent(x: number): string {
  return `${Math.round(x * 100)}%`
}

// "backpack" -> "Backpack", "handbag/suitcase" lists -> "bag or suitcase"
export function objectsLabel(objects: string[]): string {
  const bags = ['backpack', 'handbag', 'suitcase']
  const names = objects.map((o) => (bags.includes(o) ? 'bag' : o))
  return [...new Set(names)].join(' or ')
}

// True once the element has scrolled into view (and stays true), for scroll-triggered motion.
import { useEffect, useRef, useState } from 'react'

export function useInView<T extends Element>(threshold = 0.35) {
  const ref = useRef<T>(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el || inView) return
    const io = new IntersectionObserver(([entry]) => entry.isIntersecting && setInView(true), { threshold })
    io.observe(el)
    return () => io.disconnect()
  }, [inView, threshold])

  return [ref, inView] as const
}

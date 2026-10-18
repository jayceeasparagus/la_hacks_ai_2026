// The "o" in WatchDog with a Doberman's pointed ears on top. The letter stays real text; the ears
// are a small overlay sitting on its shoulders (positions are in em, measured for IBM Plex Sans
// semibold; the span fixes its own line height so the ears land in the same place at any size).
// The overlay spans the letter's ink, 0.039em to 0.524em, not its tighter text box; its viewBox
// keeps that box's proportions, and each ear's base follows the curve of the o's outer edge.
export default function EaredO() {
  return (
    <span className="relative inline-block" style={{ lineHeight: 0.95 }}>
      o
      <svg
        viewBox="0 0 162 60"
        aria-hidden="true"
        className="pointer-events-none absolute overflow-visible"
        style={{ left: '0.039em', width: '0.485em', top: '0.173em', height: '0.18em' }}
        fill="currentColor"
      >
        <path d="M9 103 C8 70 16 32 31 2 C43 20 53 40 61 58 C43 62 24 78 9 103 Z" />
        <path d="M153 103 C154 70 146 32 131 2 C119 20 109 40 101 58 C119 62 138 78 153 103 Z" />
      </svg>
    </span>
  )
}

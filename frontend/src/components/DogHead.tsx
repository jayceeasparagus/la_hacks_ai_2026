// A Doberman's head from the front: tall pointed ears, a narrow skull and a long muzzle.
// Not used yet: meant for the "o" in the WatchDog headline and the favicon.
export const DOG_EARS = [
  'M27 52 C20 34 18 16 22 2 C33 12 42 26 46 40 Z',
  'M73 52 C80 34 82 16 78 2 C67 12 58 26 54 40 Z',
]
export const DOG_HEAD =
  'M50 28 C70 28 84 40 84 58 C84 72 72 84 63 98 C59 106 55 112 50 112 C45 112 41 106 37 98 C28 84 16 72 16 58 C16 40 30 28 50 28 Z'
export const DOG_EYES = [
  'M31 56 C35 51 42 51 45 56 C41 59 35 59 31 56 Z',
  'M69 56 C65 51 58 51 55 56 C59 59 65 59 69 56 Z',
]
export const DOG_NOSE = { cx: 50, cy: 103, rx: 7.5, ry: 5.5 }

interface Props {
  className?: string
  style?: React.CSSProperties
  cutout?: string // colour of the eyes and nose; the page background so they read as holes
}

export default function DogHead({ className, style, cutout = '#000' }: Props) {
  return (
    <svg viewBox="12 0 76 116" aria-hidden="true" className={className} style={style}>
      <g fill="currentColor">
        {DOG_EARS.map((d) => (
          <path key={d} d={d} />
        ))}
        <path d={DOG_HEAD} />
      </g>
      <g fill={cutout}>
        {DOG_EYES.map((d) => (
          <path key={d} d={d} />
        ))}
        <ellipse {...DOG_NOSE} />
      </g>
    </svg>
  )
}

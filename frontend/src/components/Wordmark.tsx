import EaredO from './EaredO'

export default function Wordmark({ size = 22, onClick }: { size?: number; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="font-display font-semibold tracking-[-0.03em]"
      style={{ fontSize: size, lineHeight: 1 }}
    >
      <span className="text-text">Watch</span>
      <span className="text-accent">
        D<EaredO />g
      </span>
    </button>
  )
}

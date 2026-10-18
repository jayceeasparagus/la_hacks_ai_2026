export default function Wordmark({ size = 22, onClick }: { size?: number; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="font-sans font-semibold tracking-[-0.03em]"
      style={{ fontSize: size, lineHeight: 1 }}
    >
      <span className="text-text">policy</span>
      <span className="text-accent">lens</span>
    </button>
  )
}

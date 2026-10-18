/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#000000',
        panel: '#0B0B0C',
        raised: '#121214',
        line: '#1E1E21',
        text: '#EDEDED',
        muted: '#8A8A8E',
        dim: '#55555A',
        accent: '#8FB2FF',
        'accent-ink': '#0B1020',
      },
      fontFamily: {
        sans: ['"Instrument Sans"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      letterSpacing: {
        label: '0.08em',
      },
    },
  },
  plugins: [],
}

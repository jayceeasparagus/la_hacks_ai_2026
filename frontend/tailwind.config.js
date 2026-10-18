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
        accent: '#2D4F96',
        'accent-soft': '#8EA6D8', // lighter tint for small text over video
        'accent-ink': '#060E1F',
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        display: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      letterSpacing: {
        label: '0.08em',
      },
    },
  },
  plugins: [],
}

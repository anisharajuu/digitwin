/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      colors: {
        // Control-room palette: near-black panels, one cyan accent, and
        // status colours that survive a dimmed plant-floor screen.
        ink: { 900: '#07090d', 800: '#0c1017', 700: '#121824', 600: '#1a2231', 500: '#25304260' },
        line: '#1e2838',
        accent: { DEFAULT: '#22d3ee', dim: '#0e7490' },
        ok: '#34d399',
        warn: '#fbbf24',
        crit: '#fb7185',
        idle: '#64748b',
      },
      keyframes: {
        pulseRing: {
          '0%': { opacity: '0.85', transform: 'scale(1)' },
          '70%': { opacity: '0', transform: 'scale(2.2)' },
          '100%': { opacity: '0', transform: 'scale(2.2)' },
        },
        slideIn: {
          from: { opacity: '0', transform: 'translateY(-6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        pulseRing: 'pulseRing 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        slideIn: 'slideIn 220ms ease-out',
      },
    },
  },
  plugins: [],
}

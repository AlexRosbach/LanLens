import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background: '#0f1117',
        surface: '#1a1d2e',
        surface2: '#252840',
        border: '#2d3152',
        primary: '#6366f1',
        'primary-hover': '#4f46e5',
        'primary-dim': '#6366f120',
        success: '#22c55e',
        'success-dim': '#22c55e20',
        warning: '#f59e0b',
        'warning-dim': '#f59e0b20',
        danger: '#ef4444',
        'danger-dim': '#ef444420',
        'text-base': '#e2e8f0',
        'text-muted': '#94a3b8',
        'text-subtle': '#64748b',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Consolas', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'spin-slow': 'spin 3s linear infinite',
        'fade-in': 'fadeIn 0.2s ease-in-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(-4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}

export default config

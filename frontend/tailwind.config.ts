import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx,js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        canvas: '#020617',
        surface: '#0f172a',
        overlay: '#1e293b',
        'text-strong': '#f8fafc',
        'text-muted': '#94a3b8',
        brand: {
          primary: '#334155',
        },
        status: {
          error: '#f87171',
        },
      },
      spacing: {
        'page': '1.5rem',
        'card': '2rem',
        'element': '1rem',
        'stack': '0.25rem',
      },
      borderRadius: {
        'base': '0.375rem',
      },
    },
  },
  plugins: [],
}

export default config

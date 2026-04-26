import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx,js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Core Palette
        canvas: '#020617',
        background: '#131313',
        surface: {
          DEFAULT: '#0f172a',
          dim: '#131313',
          bright: '#3a3939',
          'container-lowest': '#0e0e0e',
          'container-low': '#1c1b1b',
          container: '#201f1f',
          'container-high': '#2a2a2a',
          'container-highest': '#353535',
          variant: '#353535',
          tint: '#c4c7c9',
        },
        overlay: '#1e293b',
        border: '#334155',
        outline: {
          DEFAULT: '#8e9193',
          variant: '#444749',
        },
        
        // Semantic Colors
        primary: {
          DEFAULT: '#ffffff',
          on: '#2d3133',
          container: '#e0e3e5',
          'on-container': '#626567',
          inverse: '#5c5f61',
          fixed: '#e0e3e5',
          'fixed-dim': '#c4c7c9',
        },
        secondary: {
          DEFAULT: '#b7c8e1',
          on: '#213145',
          container: '#3a4a5f',
          'on-container': '#a9bad3',
          fixed: '#d3e4fe',
          'fixed-dim': '#b7c8e1',
        },
        tertiary: {
          DEFAULT: '#ffffff',
          on: '#32302a',
          container: '#e7e2d9',
          'on-container': '#67645d',
          fixed: '#e7e2d9',
          'fixed-dim': '#cbc6bd',
        },
        error: {
          DEFAULT: '#ffb4ab',
          on: '#690005',
          container: '#93000a',
          'on-container': '#ffdad6',
          red: '#f87171',
        },
        success: {
          green: '#4ade80',
        },
        warning: {
          amber: '#fbbf24',
        },
        info: {
          blue: '#38bdf8',
        },
        
        // Text
        'text-strong': '#f8fafc',
        'text-muted': '#94a3b8',
        'on-surface': '#e5e2e1',
        'on-surface-variant': '#c4c7c9',
      },
      spacing: {
        'page-padding': '1.5rem',
        'stack-gap': '1rem',
        'element-gap': '0.5rem',
        'density-tight': '0.25rem',
        // Legacy
        'page': '1.5rem',
        'card': '2rem',
        'element': '1rem',
        'stack': '0.25rem',
      },
      borderRadius: {
        'sm': '0.125rem',
        'base': '0.375rem',
        'md': '0.375rem',
        'lg': '0.5rem',
        'xl': '0.75rem',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}

export default config

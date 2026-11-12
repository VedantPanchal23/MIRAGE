/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
          950: '#020617',
        },
        surface: {
          DEFAULT: '#ffffff',
          muted: '#f8fafc',
          subtle: '#f1f5f9',
          elevated: '#ffffff',
          dark: '#09090b',
        },
        assurance: {
          verified: '#059669',
          'verified-bg': '#ecfdf5',
          'verified-border': '#a7f3d0',
          uncertain: '#d97706',
          'uncertain-bg': '#fffbeb',
          'uncertain-border': '#fde68a',
          violation: '#dc2626',
          'violation-bg': '#fef2f2',
          'violation-border': '#fecaca',
          executing: '#0284c7',
          'executing-bg': '#f0f9ff',
          'executing-border': '#bae6fd',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        display: ['"Plus Jakarta Sans"', 'Inter', 'sans-serif'],
      },
      boxShadow: {
        'subtle': '0 1px 2px 0 rgba(0, 0, 0, 0.03), 0 1px 3px 0 rgba(0, 0, 0, 0.02)',
        'card': '0 0 0 1px rgba(226, 232, 240, 0.8), 0 2px 4px -1px rgba(0, 0, 0, 0.04)',
        'card-hover': '0 0 0 1px rgba(203, 213, 225, 1), 0 8px 16px -2px rgba(15, 23, 42, 0.06)',
        'elevated': '0 20px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.03)',
      },
      keyframes: {
        'pulse-subtle': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.6' },
        },
        'scan': {
          '0%': { transform: 'translateY(-100%)' },
          '100%': { transform: 'translateY(1000%)' },
        },
      },
      animation: {
        'pulse-subtle': 'pulse-subtle 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'scan': 'scan 4s linear infinite',
      },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        microdose: {
          text: {
            primary: '#19171b',
            secondary: '#0c152a',
            tertiary: '#6b6c71',
          },
          surface: {
            muted: '#ffffff',
            base: '#000000',
            raised: '#f8f8fa',
            dark: '#121113',
          },
          border: '#ededed',
          accent: '#ededed',
          emerald: '#10b981',
        },
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
        sans: ['Geist', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"Geist Mono"', '"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
        display: ['Geist', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
      fontSize: {
        'micro-xs': ['12px', { lineHeight: '18px' }],
        'micro-sm': ['13px', { lineHeight: '20px' }],
        'micro-md': ['14px', { lineHeight: '22px' }],
        'micro-lg': ['16px', { lineHeight: '24px' }],
        'micro-xl': ['18px', { lineHeight: '28px' }],
        'micro-2xl': ['21px', { lineHeight: '30px' }],
        'micro-3xl': ['24px', { lineHeight: '32px' }],
        'micro-4xl': ['26px', { lineHeight: '36px' }],
      },
      borderRadius: {
        'micro-xs': '24px',
        'micro-sm': '32px',
        'micro-md': '100px',
      },
      boxShadow: {
        'microdose-1': 'rgba(14, 15, 43, 0.08) 0px 1px 2px 0px, rgba(66, 39, 92, 0.02) 0px 43px 80px 0px',
        'microdose-2': '0px 8px 18px 0px rgba(25, 53, 217, 0)',
        'microdose-card': '0 2px 8px rgba(14, 15, 43, 0.03), 0 1px 2px rgba(14, 15, 43, 0.02)',
        'microdose-hover': '0 12px 32px -4px rgba(14, 15, 43, 0.06)',
        'subtle': '0 1px 2px 0 rgba(0, 0, 0, 0.03), 0 1px 3px 0 rgba(0, 0, 0, 0.02)',
        'card': '0 0 0 1px rgba(226, 232, 240, 0.8), 0 2px 4px -1px rgba(0, 0, 0, 0.04)',
        'card-hover': '0 0 0 1px rgba(203, 213, 225, 1), 0 8px 16px -2px rgba(15, 23, 42, 0.06)',
        'elevated': '0 20px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.03)',
      },
      transitionTimingFunction: {
        'microdose': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
      transitionDuration: {
        'instant': '200ms',
        'fast': '220ms',
        'normal': '250ms',
        'slow': '300ms',
        'slower': '500ms',
      },
      keyframes: {
        'micro-fade-up': {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'micro-pulse-radar': {
          '0%': { transform: 'scale(0.95)', boxShadow: '0 0 0 0 rgba(16, 185, 129, 0.6)' },
          '70%': { transform: 'scale(1)', boxShadow: '0 0 0 6px rgba(16, 185, 129, 0)' },
          '100%': { transform: 'scale(0.95)', boxShadow: '0 0 0 0 rgba(16, 185, 129, 0)' },
        },
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
        'micro-fade-up': 'micro-fade-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards',
        'micro-radar': 'micro-pulse-radar 2s cubic-bezier(0.16, 1, 0.3, 1) infinite',
        'pulse-subtle': 'pulse-subtle 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'scan': 'scan 4s linear infinite',
      },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "\"SF Pro Display\"",
          "\"SF Pro Text\"",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "\"SF Mono\"",
          "ui-monospace",
          "Menlo",
          "Monaco",
          "monospace",
        ],
      },
      colors: {
        apple: {
          bg: "#fbfbfd",
          surface: "#ffffff",
          subtle: "#f5f5f7",
          border: "#e5e5ea",
          borderStrong: "#d1d1d6",
          text: "#1d1d1f",
          secondary: "#6e6e73",
          muted: "#86868b",
          blue: "#0071e3",
          blueHover: "#0077ed",
          green: "#34c759",
          orange: "#ff9500",
          red: "#ff3b30",
          purple: "#af52de",
        },
      },
      boxShadow: {
        "apple-sm": "0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02)",
        "apple-card": "0 2px 10px rgba(0, 0, 0, 0.04), 0 1px 3px rgba(0, 0, 0, 0.02)",
        "apple-float": "0 14px 34px rgba(0, 0, 0, 0.08), 0 4px 12px rgba(0, 0, 0, 0.03)",
        "apple-modal": "0 24px 60px rgba(0, 0, 0, 0.15), 0 8px 24px rgba(0, 0, 0, 0.05)",
      },
      borderRadius: {
        "2xl": "1.25rem",
        "3xl": "1.5rem",
      },
    },
  },
  plugins: [],
};

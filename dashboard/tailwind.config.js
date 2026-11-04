/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "'JetBrains Mono'",
          "'SF Mono'",
          "ui-monospace",
          "Menlo",
          "monospace",
        ],
        display: [
          "'Space Grotesk'",
          "Inter",
          "sans-serif",
        ],
      },
      colors: {
        // MIRAGE Industrial Design System
        mirage: {
          void: "#050608",
          chassis: "#090a0f",
          surface: "#0f121a",
          surfaceHover: "#151924",
          surfaceElevated: "#1b202e",
          border: "#1e2433",
          borderStrong: "#2d374d",
          borderGlow: "#00f0ff40",
          text: "#f8fafc",
          subtext: "#94a3b8",
          muted: "#64748b",
          // Gate & Telemetry Spectrum
          cyan: "#00f0ff",        // Laser Cyan (Gate 1 Input & Telemetry)
          cyanGlow: "#00f0ff20",
          emerald: "#10b981",     // Cyber Emerald (Gate 2 Context & Verified Outcomes)
          emeraldGlow: "#10b98120",
          amber: "#f59e0b",       // Safety Amber (Gate 3 Action & HITL Quorum)
          amberGlow: "#f59e0b20",
          purple: "#a855f7",      // Quantum Violet (Gate 4 HRS & Neural Scoring)
          purpleGlow: "#a855f720",
          blue: "#3b82f6",        // Deep Cobalt (Gate 5 Reality Verification)
          blueGlow: "#3b82f620",
          crimson: "#ef4444",     // Fail-Closed Red (Rejections, Discrepancies)
          crimsonGlow: "#ef444420",
        },
        // Backward-compatibility bridge mapped to industrial tokens
        apple: {
          bg: "#090a0f",
          surface: "#0f121a",
          subtle: "#151924",
          border: "#1e2433",
          borderStrong: "#2d374d",
          text: "#f8fafc",
          secondary: "#94a3b8",
          muted: "#64748b",
          blue: "#00f0ff",
          blueHover: "#38bdf8",
          green: "#10b981",
          orange: "#f59e0b",
          red: "#ef4444",
          purple: "#a855f7",
        },
      },
      boxShadow: {
        "hud-glow": "0 0 20px -5px rgba(0, 240, 255, 0.25)",
        "hud-glow-amber": "0 0 20px -5px rgba(245, 158, 11, 0.25)",
        "hud-glow-emerald": "0 0 20px -5px rgba(16, 185, 129, 0.25)",
        "hud-glow-crimson": "0 0 20px -5px rgba(239, 68, 68, 0.25)",
        "hud-panel": "0 8px 32px 0 rgba(0, 0, 0, 0.45)",
        "hud-active": "0 0 0 1px rgba(0, 240, 255, 0.4), 0 8px 30px rgba(0, 240, 255, 0.15)",
        "apple-sm": "0 1px 3px rgba(0, 0, 0, 0.3)",
        "apple-card": "0 4px 20px rgba(0, 0, 0, 0.4)",
        "apple-float": "0 14px 34px rgba(0, 0, 0, 0.6)",
        "apple-modal": "0 24px 60px rgba(0, 0, 0, 0.8)",
      },
      backgroundImage: {
        "cyber-grid": "linear-gradient(to right, rgba(30, 36, 51, 0.4) 1px, transparent 1px), linear-gradient(to bottom, rgba(30, 36, 51, 0.4) 1px, transparent 1px)",
        "radial-glow": "radial-gradient(circle at 50% 0%, rgba(0, 240, 255, 0.08) 0%, transparent 60%)",
        "scanner-line": "linear-gradient(90deg, transparent, rgba(0, 240, 255, 0.8), transparent)",
      },
      animation: {
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "scanline": "scanline 8s linear infinite",
        "radar-sweep": "radar 4s linear infinite",
        "beacon": "beacon 2s cubic-bezier(0, 0, 0.2, 1) infinite",
      },
      keyframes: {
        scanline: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(1000%)" },
        },
        radar: {
          "0%": { transform: "rotate(0deg)" },
          "100%": { transform: "rotate(360deg)" },
        },
        beacon: {
          "75%, 100%": { transform: "scale(2)", opacity: "0" },
        },
      },
      borderRadius: {
        "2xl": "0.75rem", // More angular industrial feel
        "3xl": "1.0rem",
      },
    },
  },
  plugins: [],
};

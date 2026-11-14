import React from 'react';

/**
 * World-Class Bespoke Brandmark for MIRAGE
 * 
 * Concept: 
 * "Refracting AI Uncertainty into Verified Reality"
 * 
 * Visual Architecture:
 * - Isometric 3D Refractive Prisms forming a stylized geometric "M"
 * - Deep Obsidian Titanium Monoliths (#090D16 & #1E293B)
 * - Translucent Optical Laser Spine in Emerald (#10B981) cutting through the prism
 * - Precision Diamond Apex representing Ground Truth Verification (Gate 5)
 * - Bespoke High-Craft Typography with geometric letterspacing
 */
export function MirageLogo({ size = 'md', showText = true, className = '' }) {
  const sizeMap = {
    sm: { icon: 26, text: 'text-[15px]', sub: 'text-[8px]' },
    md: { icon: 34, text: 'text-[17px]', sub: 'text-[9px]' },
    lg: { icon: 44, text: 'text-[22px]', sub: 'text-[11px]' },
  };

  const current = sizeMap[size] || sizeMap.md;

  return (
    <div className={`flex items-center gap-3 select-none group ${className}`}>
      {/* Precision Geometric Brandmark */}
      <div 
        className="relative flex items-center justify-center shrink-0"
        style={{ width: current.icon, height: current.icon }}
      >
        <svg 
          viewBox="0 0 48 48" 
          fill="none" 
          xmlns="http://www.w3.org/2000/svg"
          className="w-full h-full transition-transform duration-300 group-hover:scale-105"
        >
          <defs>
            {/* Obsidian Monolith Gradient */}
            <linearGradient id="mirage-obsidian-left" x1="6" y1="6" x2="22" y2="42" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#1E293B" />
              <stop offset="100%" stopColor="#090D16" />
            </linearGradient>

            <linearGradient id="mirage-obsidian-right" x1="26" y1="6" x2="42" y2="42" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#0F172A" />
              <stop offset="100%" stopColor="#020617" />
            </linearGradient>

            {/* Laser Refraction Emerald Core */}
            <linearGradient id="mirage-laser-emerald" x1="16" y1="8" x2="32" y2="40" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#34D399" />
              <stop offset="50%" stopColor="#10B981" />
              <stop offset="100%" stopColor="#059669" />
            </linearGradient>

            {/* Micro Edge Highlight */}
            <linearGradient id="mirage-edge-glow" x1="0" y1="0" x2="48" y2="0" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#38BDF8" stopOpacity="0.8" />
              <stop offset="50%" stopColor="#34D399" stopOpacity="0.9" />
              <stop offset="100%" stopColor="#10B981" stopOpacity="0.4" />
            </linearGradient>

            <filter id="mirage-core-glow" x="12" y="10" width="24" height="28" filterUnits="userSpaceOnUse">
              <feGaussianBlur stdDeviation="1.5" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
          </defs>

          {/* Left Pillar Chevron (Facet of 'M') */}
          <path 
            d="M8 38V14L18 8V32L8 38Z" 
            fill="url(#mirage-obsidian-left)" 
          />
          {/* Left Top Chiseled Edge */}
          <path 
            d="M8 14L18 8L22 11L12 17L8 14Z" 
            fill="#334155" 
            opacity="0.9"
          />

          {/* Right Pillar Chevron (Facet of 'M') */}
          <path 
            d="M40 38V14L30 8V32L40 38Z" 
            fill="url(#mirage-obsidian-right)" 
          />
          {/* Right Top Chiseled Edge */}
          <path 
            d="M40 14L30 8L26 11L36 17L40 14Z" 
            fill="#1E293B" 
            opacity="0.9"
          />

          {/* Central Converging Refractive Prisms (The Core Optical Diamond 'M') */}
          <path 
            d="M24 12L32 24L24 38L16 24L24 12Z" 
            fill="url(#mirage-laser-emerald)" 
            filter="url(#mirage-core-glow)"
          />

          {/* Precision Light Refraction Core (Diagonal Beam) */}
          <path 
            d="M19 24L24 16L29 24L24 33L19 24Z" 
            fill="#A7F3D0" 
            opacity="0.85"
          />

          {/* Verification Apex Focal Dot */}
          <circle 
            cx="24" 
            cy="24" 
            r="2" 
            fill="#FFFFFF" 
          />

          {/* Razor-sharp Optical Axis Stems */}
          <line x1="24" y1="4" x2="24" y2="10" stroke="#10B981" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="24" y1="40" x2="24" y2="44" stroke="#059669" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </div>

      {/* Crafted Brand Typography */}
      {showText && (
        <div className="flex flex-col justify-center leading-none">
          <div className="flex items-center gap-1.5">
            <span className={`font-black ${current.text} tracking-[0.18em] text-slate-950 font-display transition-colors group-hover:text-black`}>
              MIRAGE
            </span>
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <span className={`font-mono ${current.sub} tracking-[0.24em] text-emerald-700 font-bold uppercase`}>
              Assurance
            </span>
            <span className="w-1 h-1 rounded-full bg-emerald-500 animate-pulse" />
          </div>
        </div>
      )}
    </div>
  );
}

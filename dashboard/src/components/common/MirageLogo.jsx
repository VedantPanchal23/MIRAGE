import React from 'react';

/**
 * Custom Bespoke Logo for MIRAGE 3.0
 * Represents the 5 Assurance Gates converging onto a verified reality core.
 * Geometric, precise, modern, high-contrast obsidian & emerald refraction.
 */
export function MirageLogo({ size = 'md', showText = true, className = '' }) {
  const sizeMap = {
    sm: { icon: 24, font: 'text-sm', badge: 'text-[9px]' },
    md: { icon: 30, font: 'text-base', badge: 'text-[10px]' },
    lg: { icon: 38, font: 'text-xl', badge: 'text-xs' },
  };

  const current = sizeMap[size] || sizeMap.md;

  return (
    <div className={`flex items-center gap-2.5 select-none ${className}`}>
      {/* Engineered Geometric Mark */}
      <div 
        className="relative flex items-center justify-center shrink-0"
        style={{ width: current.icon, height: current.icon }}
      >
        <svg 
          viewBox="0 0 36 36" 
          fill="none" 
          xmlns="http://www.w3.org/2000/svg"
          className="w-full h-full drop-shadow-xs"
        >
          {/* Outer Obsidian Shield / Faceted Hexagon */}
          <path 
            d="M18 2L32 9.5V20.5C32 27.5 25.5 32.8 18 34.5C10.5 32.8 4 27.5 4 20.5V9.5L18 2Z" 
            fill="#09090b" 
          />
          {/* Optical Refraction Facet (Left Shading) */}
          <path 
            d="M18 2L4 9.5V20.5C4 27.5 10.5 32.8 18 34.5V2Z" 
            fill="#18181b" 
            opacity="0.85" 
          />
          {/* Inner Converging Assurance Gates Prism (Geometric Core) */}
          <path 
            d="M18 8L27 13.5V20C27 24.5 22.5 28 18 29.5C13.5 28 9 24.5 9 20V13.5L18 8Z" 
            stroke="#27272a" 
            strokeWidth="1.2" 
          />
          {/* Reality Verification Laser Core (Emerald Ground Truth) */}
          <path 
            d="M18 13L23 16.5V20C23 22.5 20.5 24.5 18 25.5C15.5 24.5 13 22.5 13 20V16.5L18 13Z" 
            fill="#10b981" 
          />
          {/* Laser Apex Accent */}
          <circle cx="18" cy="18" r="2.2" fill="#ffffff" />
        </svg>
      </div>

      {showText && (
        <div className="flex items-baseline gap-1.5 leading-none">
          <span className={`font-extrabold ${current.font} tracking-[0.16em] text-slate-900 font-display`}>
            MIRAGE
          </span>
        </div>
      )}
    </div>
  );
}

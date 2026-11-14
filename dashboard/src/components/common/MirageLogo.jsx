import React from 'react';

/**
 * Microdose Studio-Inspired Brandmark for MIRAGE
 * 
 * Aesthetic:
 * - Ultra-refined, quiet luxury, editorial precision
 * - Monochromatic depth (#0c152a & #6b6c71) with emerald focal point
 * - Typography: "mirage" (font-medium #0c152a) + ".assurance" (font-light #6b6c71)
 * - Micro geometric glyph: Minimalist optical refraction prism aperture
 */
export function MirageLogo({ size = 'md', showText = true, className = '' }) {
  const sizeMap = {
    sm: { icon: 20, text: 'text-[15px]', sub: 'text-[15px]' },
    md: { icon: 24, text: 'text-[18px]', sub: 'text-[18px]' },
    lg: { icon: 30, text: 'text-[22px]', sub: 'text-[22px]' },
  };

  const current = sizeMap[size] || sizeMap.md;

  return (
    <div className={`inline-flex items-center gap-2.5 select-none group cursor-pointer ${className}`}>
      {/* Minimalist Microdose-Style Geometric Optical Glyph */}
      <div 
        className="relative flex items-center justify-center shrink-0 transition-transform duration-300 group-hover:scale-105"
        style={{ width: current.icon, height: current.icon }}
      >
        <svg 
          viewBox="0 0 32 32" 
          fill="none" 
          xmlns="http://www.w3.org/2000/svg"
          className="w-full h-full"
        >
          {/* Outer Minimalist Precision Hexagon Ring */}
          <path 
            d="M16 3L27.5 9.5V22.5L16 29L4.5 22.5V9.5L16 3Z" 
            stroke="#0c152a" 
            strokeWidth="1.75" 
            strokeLinejoin="round"
          />
          {/* Inner Optical Refraction Blade */}
          <path 
            d="M16 8L23 16L16 24L9 16L16 8Z" 
            fill="#f4f4f6"
            stroke="#6b6c71" 
            strokeWidth="1.2" 
            strokeLinejoin="round"
          />
          {/* Active Emerald Reality Focal Core */}
          <circle 
            cx="16" 
            cy="16" 
            r="2.5" 
            fill="#10b981" 
          />
        </svg>
      </div>

      {/* Microdose-Style Wordmark: Bold/Medium Brand + Light Extension */}
      {showText && (
        <div className="flex items-baseline leading-none font-sans">
          <span className={`font-semibold tracking-[-0.03em] text-[#0c152a] ${current.text}`}>
            mirage
          </span>
          <span className={`font-light tracking-[-0.03em] text-[#6b6c71] ${current.sub}`}>
            .assurance
          </span>
        </div>
      )}
    </div>
  );
}

import React from 'react';

/**
 * Breadcrumbs: Semantic breadcrumb navigation supporting Schema.org microdata with tactical telemetry style.
 *
 * @param {Array<{label: string, onClick?: () => void, href?: string, current?: boolean}>} items
 */
export default function Breadcrumbs({ items = [] }) {
  if (!items || items.length === 0) return null;

  return (
    <nav
      aria-label="Breadcrumb"
      className="py-2.5 px-1 text-xs font-mono text-mirage-muted flex items-center space-x-2 select-none"
    >
      <ol
        itemScope
        itemType="https://schema.org/BreadcrumbList"
        className="flex items-center space-x-2"
      >
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <li
              key={index}
              itemProp="itemListElement"
              itemScope
              itemType="https://schema.org/ListItem"
              className="flex items-center space-x-2"
            >
              {isLast || item.current ? (
                <span
                  itemProp="name"
                  aria-current="page"
                  className="font-medium text-mirage-cyan cursor-default tracking-wide uppercase"
                >
                  {item.label}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={item.onClick}
                  itemProp="item"
                  className="text-mirage-subtext hover:text-mirage-cyan transition-colors focus:outline-none uppercase"
                >
                  <span itemProp="name">{item.label}</span>
                </button>
              )}
              <meta itemProp="position" content={String(index + 1)} />

              {!isLast && (
                <span className="text-mirage-borderStrong font-mono text-xs select-none" aria-hidden="true">
                  /
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

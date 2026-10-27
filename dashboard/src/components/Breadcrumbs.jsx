import React from 'react';

/**
 * Breadcrumbs: Semantic breadcrumb navigation supporting Schema.org microdata.
 *
 * @param {Array<{label: string, onClick?: () => void, href?: string, current?: boolean}>} items
 */
export default function Breadcrumbs({ items = [] }) {
  if (!items || items.length === 0) return null;

  return (
    <nav
      aria-label="Breadcrumb"
      className="py-3 px-1 text-xs text-apple-gray flex items-center space-x-2"
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
                  className="font-medium text-apple-text cursor-default"
                >
                  {item.label}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={item.onClick}
                  itemProp="item"
                  className="text-apple-subtext hover:text-apple-blue transition-colors focus:outline-none"
                >
                  <span itemProp="name">{item.label}</span>
                </button>
              )}
              <meta itemProp="position" content={String(index + 1)} />

              {!isLast && (
                <svg
                  className="w-3.5 h-3.5 text-apple-gray/60"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth="2"
                  aria-hidden="true"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

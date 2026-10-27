import { useEffect } from 'react';

/**
 * useSEO: Custom hook to set unique document titles, meta descriptions, and canonical tags.
 * Ensures strict compliance with Search Engine optimization and SPA routing standards.
 *
 * @param {string} title - Page title suffix (e.g. 'Enterprise Demo & Inquiries')
 * @param {string} description - Meta description string for SERP snippets
 * @param {string} path - URL path for canonical indexing (e.g. '/contact')
 */
export function useSEO({ title, description, path = '/' }) {
  useEffect(() => {
    // 1. Dynamic Title
    const baseTitle = 'MIRAGE — AI Execution Assurance Platform';
    document.title = title ? `${title} | MIRAGE` : baseTitle;

    // 2. Dynamic Meta Description
    let metaDesc = document.querySelector('meta[name="description"]');
    if (!metaDesc) {
      metaDesc = document.createElement('meta');
      metaDesc.name = 'description';
      document.head.appendChild(metaDesc);
    }
    metaDesc.content = description || 'Control AI before it acts. Verify AI after it acts. Production-grade Five-Gate execution assurance.';

    // 3. Dynamic Canonical Tag
    let canonical = document.querySelector('#canonical-link');
    if (!canonical) {
      canonical = document.createElement('link');
      canonical.id = 'canonical-link';
      canonical.rel = 'canonical';
      document.head.appendChild(canonical);
    }
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    canonical.href = `https://mirage-assurance.com${cleanPath === '/' ? '' : cleanPath}`;
  }, [title, description, path]);
}

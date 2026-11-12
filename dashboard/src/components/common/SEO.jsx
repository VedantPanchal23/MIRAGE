import { useEffect } from 'react';

export function SEO({
  title = 'MIRAGE 3.0 — The AI Execution Assurance Platform',
  description = 'Control AI before it acts. Verify AI after it acts. MIRAGE 3.0 governs identity, capabilities, and independent physical reality verification for autonomous agents.',
  keywords = 'AI assurance, reality verification, AI agent security, tool governance, audit ledger, SOC2 AI',
  canonical = 'https://mirage.assurance.ai/',
}) {
  useEffect(() => {
    // 1. Update Title
    document.title = title.includes('MIRAGE') ? title : `${title} | MIRAGE 3.0`;

    // 2. Helper to set or create meta tag
    const setMeta = (attr, key, val) => {
      let el = document.querySelector(`meta[${attr}="${key}"]`);
      if (!el) {
        el = document.createElement('meta');
        el.setAttribute(attr, key);
        document.head.appendChild(el);
      }
      el.setAttribute('content', val);
    };

    setMeta('name', 'description', description);
    setMeta('name', 'keywords', keywords);
    setMeta('property', 'og:title', title);
    setMeta('property', 'og:description', description);
    setMeta('name', 'twitter:title', title);
    setMeta('name', 'twitter:description', description);

    // 3. Update Canonical link
    let link = document.querySelector('link[rel="canonical"]');
    if (!link) {
      link = document.createElement('link');
      link.setAttribute('rel', 'canonical');
      document.head.appendChild(link);
    }
    link.setAttribute('href', canonical);
  }, [title, description, keywords, canonical]);

  return null;
}

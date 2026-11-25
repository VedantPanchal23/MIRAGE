/**
 * Privacy-first consent-gated telemetry helper.
 * Dispatches conversion/product events only when user grants analytics consent.
 */

const CONSENT_STORAGE_KEY = 'mirage_cookie_consent';

export function getCookieConsent() {
  try {
    const raw = localStorage.getItem(CONSENT_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveCookieConsent({ essential = true, analytics = false }) {
  const value = {
    essential: Boolean(essential),
    analytics: Boolean(analytics),
    updatedAt: new Date().toISOString(),
  };
  try {
    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify(value));
  } catch {
    // ignore storage quota errors
  }
  return value;
}

export function trackEvent(eventName, properties = {}) {
  const consent = getCookieConsent();
  if (!consent?.analytics) {
    return false;
  }
  try {
    if (typeof window !== 'undefined' && typeof window.plausible === 'function') {
      window.plausible(eventName, { props: properties });
    }
    if (typeof window !== 'undefined' && typeof window.gtag === 'function') {
      window.gtag('event', eventName, properties);
    }
  } catch {
    // non-fatal analytics failure
  }
  return true;
}

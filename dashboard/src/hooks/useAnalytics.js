import { useEffect, useCallback } from 'react';

/**
 * useAnalytics: Privacy-preserving client-side telemetry hook.
 * Records route transitions, CTA clicks, Gate inspections, and conversion events.
 */
export function useAnalytics() {
  const trackEvent = useCallback((eventName, properties = {}) => {
    const event = {
      event: eventName,
      timestamp: new Date().toISOString(),
      path: window.location.pathname,
      ...properties,
    };

    // 1. Console instrumentation in development
    if (import.meta.env.DEV) {
      console.log(`[MIRAGE Telemetry] ${eventName}:`, properties);
    }

    // 2. Buffer to session-scoped storage for offline auditing
    try {
      const buffer = JSON.parse(sessionStorage.getItem('mirage_telemetry_buffer') || '[]');
      buffer.push(event);
      if (buffer.length > 50) buffer.shift();
      sessionStorage.setItem('mirage_telemetry_buffer', JSON.stringify(buffer));
    } catch {
      // Ignore storage quota limitations
    }
  }, []);

  const trackPageView = useCallback((pageName) => {
    trackEvent('page_view', { page: pageName, title: document.title });
  }, [trackEvent]);

  return { trackEvent, trackPageView };
}

import React, { useState, useEffect } from 'react';
import { ShieldCheck } from 'lucide-react';
import { getCookieConsent, saveCookieConsent } from '../../utils/analytics';

export function CookieConsent({ onOpenPrivacy = () => {} }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const existing = getCookieConsent();
    if (!existing) {
      setVisible(true);
    }
  }, []);

  if (!visible) return null;

  const handleAcceptAll = () => {
    saveCookieConsent({ essential: true, analytics: true });
    setVisible(false);
  };

  const handleEssentialOnly = () => {
    saveCookieConsent({ essential: true, analytics: false });
    setVisible(false);
  };

  return (
    <aside
      aria-label="Cookie and Privacy Preferences"
      className="fixed bottom-4 left-4 right-4 sm:left-6 sm:right-auto sm:max-w-md z-40 rounded-2xl border border-[#ededed] bg-white p-4 shadow-xl text-xs text-[#19171b]"
    >
      <div className="flex items-start gap-2.5 mb-3">
        <ShieldCheck className="w-4 h-4 text-emerald-700 shrink-0 mt-0.5" />
        <div>
          <div className="font-semibold text-[#0c152a] mb-1">Privacy &amp; Cookie Controls</div>
          <p className="text-[#6b6c71] leading-relaxed">
            Essential session storage keeps authentication and tenant isolation state working. Optional product analytics stays disabled unless you opt in. See our{' '}
            <button
              type="button"
              onClick={onOpenPrivacy}
              className="underline text-[#0c152a] font-medium hover:text-emerald-700"
            >
              Privacy Policy
            </button>
            .
          </p>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={handleEssentialOnly}
          className="px-3.5 py-1.5 rounded-full border border-[#ededed] bg-[#f8f8fa] text-[#0c152a] font-medium hover:bg-[#ededed] transition-colors"
        >
          Essential Only
        </button>
        <button
          type="button"
          onClick={handleAcceptAll}
          className="px-4 py-1.5 rounded-full bg-[#0c152a] text-white font-medium hover:bg-[#19171b] transition-colors"
        >
          Accept Analytics
        </button>
      </div>
    </aside>
  );
}

import React from 'react';
import { useSEO } from '../hooks/useSEO';
import Breadcrumbs from '../components/Breadcrumbs';

export default function NotFoundView({ onNavigateHome, onNavigateApp }) {
  useSEO({
    title: '404 Page Not Found',
    description: 'The requested resource or page was not found on the MIRAGE AI Execution Assurance platform.',
    path: '/404',
  });

  const breadcrumbs = [
    { label: 'Home', onClick: onNavigateHome },
    { label: '404 Not Found', current: true },
  ];

  return (
    <div className="max-w-4xl mx-auto px-4 py-16 text-center">
      <Breadcrumbs items={breadcrumbs} />

      <div className="max-w-md mx-auto mt-8 bg-mirage-surface border border-mirage-border/70 rounded p-8 shadow-sm space-y-4">
        <span className="inline-block px-3 py-1 bg-mirage-muted/10 text-mirage-muted font-mono text-xs rounded-full font-semibold">
          Error 404
        </span>

        <h1 className="text-2xl font-bold tracking-tight text-mirage-text">
          Page or Route Not Found
        </h1>

        <p className="text-xs text-mirage-muted leading-relaxed">
          The requested path does not exist or has been moved. If you were attempting to access an authenticated tenant execution lease, please verify your session credentials.
        </p>

        <div className="pt-4 flex flex-col sm:flex-row items-center justify-center gap-3">
          <button
            onClick={onNavigateHome}
            className="w-full sm:w-auto px-4 py-2 text-xs bg-mirage-cyan text-white rounded font-medium hover:bg-mirage-cyan/90 shadow-sm transition-all"
          >
            Return to Storefront
          </button>
          <button
            onClick={onNavigateApp}
            className="w-full sm:w-auto px-4 py-2 text-xs border border-mirage-border text-mirage-text rounded font-medium hover:bg-mirage-chassis transition-colors"
          >
            Open Operator Dashboard
          </button>
        </div>
      </div>
    </div>
  );
}
